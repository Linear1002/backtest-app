"""総当たりのジョブ(backend/sweeps.py)のテスト。HTTP を通さず、SweepJobs を直接動かす。

計算はスレッド(ThreadPoolExecutor)で動かし、runner を差し替えて、止める・落ちる・失敗するを作る。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool

import pytest
from engine_helpers import make_bars

from backend.sweeps import (
    INTERNAL_ERROR,
    MAX_CHUNK_PAIRS,
    SweepJob,
    SweepJobs,
    SweepSpec,
    chunk_ranges,
)
from engine.reference.sweep import SweepCosts, SweepGrid, run_pairs, validate_sweep

COSTS = SweepCosts(fee_rate=0.001, slippage_rate=0.0005, initial_cash=1_000_000.0)


def spec() -> SweepSpec:
    bars = make_bars([100.0 + (i % 7) - (i % 3) for i in range(40)])
    pairs, segments = validate_sweep(
        bars, bars[0].date, bars[-1].date, SweepGrid(1, 3, 1, 4, 6, 1), COSTS
    )
    return SweepSpec(tuple(bars), segments, COSTS, tuple(pairs))


def thread_jobs(**kwargs) -> SweepJobs:
    return SweepJobs(2, executor_factory=lambda n: ThreadPoolExecutor(max_workers=n), **kwargs)


def wait_finished(job: SweepJob, timeout: float = 10.0) -> SweepJob:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with job.lock:
            if job.status != "running":
                return job
        time.sleep(0.02)
    raise AssertionError("ジョブが時間内に終わりませんでした")


# --- かたまりの分け方 ------------------------------------------------------------------


@pytest.mark.parametrize("total", [1, 2, 7, 16, 17, 105, 999, 2000, 20000])
@pytest.mark.parametrize("workers", [1, 2, 3, 8])
def test_chunks_cover_every_pair_once_and_stay_small(total: int, workers: int) -> None:
    chunks = chunk_ranges(total, workers)
    assert chunks[0][0] == 0 and chunks[-1][1] == total
    for (_, end), (next_first, _) in zip(chunks, chunks[1:], strict=False):
        assert end == next_first  # すき間も重なりもない
    assert all(1 <= end - first <= MAX_CHUNK_PAIRS for first, end in chunks)


def test_chunk_examples() -> None:
    assert chunk_ranges(0, 2) == []
    assert chunk_ranges(1, 2) == [(0, 1)]
    # 105通り・2プロセス:16個くらいに分ける → 7通りずつ
    assert [end - first for first, end in chunk_ranges(105, 2)] == [7] * 15
    # 2,000通り:上限の10通りずつ(中止したときに待つのは、計算中のかたまりの分だけ)
    assert len(chunk_ranges(2000, 4)) == 200


# --- 結果・失敗 ------------------------------------------------------------------------


def test_result_is_built_from_rows_in_combo_order() -> None:
    jobs = thread_jobs()
    s = spec()
    job = wait_finished(jobs.start(s, build=lambda rows: ("built", len(rows))))
    assert job.status == "done" and job.done == len(s.pairs)
    expected = run_pairs(s.bars, s.segments, s.costs, s.pairs).rows
    assert job.rows == expected
    assert job.output == ("built", len(expected))


def test_failure_while_building_the_result_is_an_internal_error() -> None:
    def build(rows):
        raise RuntimeError("boom (internal detail)")

    job = wait_finished(thread_jobs().start(spec(), build=build))
    assert job.status == "failed" and job.error_kind == "internal"
    assert job.error_message == INTERNAL_ERROR and job.output is None


class BrokenOnce(ThreadPoolExecutor):
    """最初の submit で、計算用のプロセスが落ちたときと同じ例外を投げる。"""

    def submit(self, *args, **kwargs):
        raise BrokenProcessPool("計算用のプロセスが落ちた")


def test_broken_executor_is_replaced_for_the_next_job() -> None:
    made: list[ThreadPoolExecutor] = []

    def factory(n: int) -> ThreadPoolExecutor:
        executor = BrokenOnce(max_workers=n) if not made else ThreadPoolExecutor(max_workers=n)
        made.append(executor)
        return executor

    jobs = SweepJobs(2, executor_factory=factory)
    first = wait_finished(jobs.start(spec()))
    assert first.status == "failed" and first.error_kind == "internal"
    second = wait_finished(jobs.start(spec()))
    assert second.status == "done"
    assert len(made) == 2  # 落ちた executor は捨てて、作り直した


# --- 止める ---------------------------------------------------------------------------


def test_shutdown_cancels_running_jobs_and_a_new_executor_is_made_later() -> None:
    release = threading.Event()
    started = threading.Event()

    def runner(bars, segments, costs, pairs, first_index):
        started.set()
        release.wait(timeout=10)
        return run_pairs(bars, segments, costs, pairs, first_index)

    jobs = thread_jobs(runner=runner)
    job = jobs.start(spec())
    assert started.wait(timeout=5)
    jobs.shutdown()
    with job.lock:
        assert job.cancel_requested
    release.set()
    assert wait_finished(job).status == "cancelled"
    # 止めたあとに始めたジョブは、新しい executor で計算する
    assert jobs._executor is None
    assert wait_finished(jobs.start(spec())).status == "done"
    assert jobs._executor is not None

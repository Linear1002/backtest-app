"""総当たりのジョブ(docs/sweep.md 10章)。

総当たりは数秒〜数分かかるので、リクエストはすぐに返し、計算は別のスレッドで進める。
- 組み合わせをいくつかのかたまり(chunk)に分け、CPU のコアの数だけのプロセスで並列に計算する
  (engine.reference.sweep.run_pairs。プロセスを分けるのは、Python のスレッドでは計算が並列にならないため)
- かたまりは小さく(最大 MAX_CHUNK_PAIRS 通り。Python で1秒ほど)する。中止したとき・サーバーを止めるときは、
  計算中のかたまりが終わるまで待つことになるため
- 画面は GET で途中経過(終わった組み合わせの数)を問い合わせ、終わったら結果を受け取る。DELETE で中止できる
- ジョブはこのプロセスのメモリにだけ持つ(ローカルで1人が使う前提)。終わったジョブは30分で消す
- 画面を閉じるなどして問い合わせが60秒来なくなったジョブは、残りの計算を取り消す

スレッドの決まり:ジョブの欄(status・done・rows・output など)は、リクエストのスレッドと計算を見張るスレッドの
両方から読み書きするので、必ず job.lock の中で読み書きする。ジョブの一覧(self._jobs)は self._lock の中で扱う。
2つのロックを両方とるときは、self._lock → job.lock の順にする(逆の順にとるところを作らない)。
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import (
    FIRST_COMPLETED,
    BrokenExecutor,
    Executor,
    Future,
    ProcessPoolExecutor,
    wait,
)
from dataclasses import dataclass, field
from typing import Any, Literal

from engine.reference.sweep import (
    PairsOutcome,
    Segment,
    SweepCosts,
    SweepRow,
    run_pairs,
)
from engine.reference.types import Bar

logger = logging.getLogger("backend.sweeps")

JobStatus = Literal["running", "done", "failed", "cancelled"]

KEEP_FINISHED_SECONDS = 30 * 60  # 終わったジョブを残しておく時間
ABANDON_SECONDS = 60.0  # この時間、問い合わせがなければ取り消す
MAX_RUNNING_JOBS = 2  # 同時に計算するジョブの数(サーバーを守るため)
CHUNKS_PER_WORKER = (
    8  # 1つのプロセスに渡すかたまりの数の目安(途中経過の細かさと、受け渡しの手間の兼ね合い)
)
MAX_CHUNK_PAIRS = 10  # 1つのかたまりの組み合わせの数の上限(中止・停止の待ち時間を短くするため)

INTERNAL_ERROR = (
    "総当たりの計算中に、想定していないエラーが起きました。"
    "API サーバーのターミナルに出ているエラーを確認してください"
)

PairsRunner = Callable[
    [Sequence[Bar], Sequence[Segment], SweepCosts, Sequence[tuple[int, int]], int], PairsOutcome
]
# 計算が終わったら、組み合わせの順番に並んだ行から、画面に返す結果を作る(routes が渡す)
ResultBuilder = Callable[[tuple[SweepRow, ...]], Any]


class TooManyJobsError(RuntimeError):
    """同時に計算できるジョブの数を超えた。メッセージは画面に出せる日本語。"""


@dataclass(frozen=True)
class SweepSpec:
    """ジョブとして計算する内容(入力チェックを通ったもの)。"""

    bars: tuple[Bar, ...]
    segments: tuple[Segment, ...]
    costs: SweepCosts
    pairs: tuple[tuple[int, int], ...]
    context: Any = None  # 結果を画面の形にするときに使う情報(銘柄など)。ジョブは中身を見ない


@dataclass
class SweepJob:
    id: str
    spec: SweepSpec
    created_at: float
    total: int
    done: int = 0
    status: JobStatus = "running"
    rows: tuple[SweepRow, ...] | None = None
    error_kind: str | None = None  # "input" / "data" / "internal"
    error_message: str | None = None
    elapsed_seconds: float | None = None
    finished_at: float | None = None
    last_polled: float = 0.0
    cancel_requested: bool = False
    output: Any = None  # 画面に返す結果(ResultBuilder が作ったもの)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


def _status_of(job: SweepJob) -> JobStatus:
    with job.lock:
        return job.status


def chunk_ranges(total: int, workers: int) -> list[tuple[int, int]]:
    """組み合わせ 0..total-1 を、(最初の位置, 終わりの位置) のかたまりに分ける(終わりの位置は含まない)。

    プロセス1つあたり CHUNKS_PER_WORKER 個くらいに分ける。ただし1つのかたまりは MAX_CHUNK_PAIRS 通りまで。
    """
    if total <= 0:
        return []
    target = max(1, workers * CHUNKS_PER_WORKER)
    size = min(MAX_CHUNK_PAIRS, max(1, math.ceil(total / target)))
    return [(first, min(first + size, total)) for first in range(0, total, size)]


def default_workers() -> int:
    return max(1, os.cpu_count() or 1)


class SweepJobs:
    """ジョブの一覧と、計算に使うプロセスのまとめ役。API のアプリに1つだけ作る。"""

    def __init__(
        self,
        workers: int | None = None,
        *,
        executor_factory: Callable[[int], Executor] | None = None,
        runner: PairsRunner = run_pairs,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.workers = workers or default_workers()
        self._executor_factory = executor_factory or (lambda n: ProcessPoolExecutor(max_workers=n))
        self._executor: Executor | None = None
        self._runner = runner
        self._clock = clock
        self._jobs: dict[str, SweepJob] = {}
        self._lock = threading.Lock()

    # --- 外から使う ------------------------------------------------------------------

    def start(self, spec: SweepSpec, build: ResultBuilder | None = None) -> SweepJob:
        """ジョブを始める。build は、計算が終わったら(成功したときだけ)行から結果を作る。"""
        with self._lock:
            self._forget_old()
            running = sum(1 for job in self._jobs.values() if _status_of(job) == "running")
            if running >= MAX_RUNNING_JOBS:
                raise TooManyJobsError(
                    "ほかの総当たりを計算しています。終わるか中止してから、もう一度実行してください"
                )
            now = self._clock()
            job = SweepJob(
                id=uuid.uuid4().hex,
                spec=spec,
                created_at=now,
                total=len(spec.pairs),
                last_polled=now,
            )
            self._jobs[job.id] = job
            executor = self._get_executor()
        thread = threading.Thread(
            target=self._run, args=(job, executor, build), name=f"sweep-{job.id[:8]}", daemon=True
        )
        thread.start()
        return job

    def get(self, job_id: str) -> SweepJob | None:
        """ジョブを返す(問い合わせがあったことも記録する)。知らない・消えたジョブは None。"""
        with self._lock:
            self._forget_old()
            job = self._jobs.get(job_id)
        if job is not None:
            with job.lock:
                job.last_polled = self._clock()
        return job

    def cancel(self, job_id: str) -> SweepJob | None:
        job = self.get(job_id)
        if job is not None:
            with job.lock:
                job.cancel_requested = True
        return job

    def shutdown(self) -> None:
        """API サーバーを止めるとき。計算中のジョブは取り消す。

        まだ始まっていないかたまりは取り消す。計算中のかたまり(最大 MAX_CHUNK_PAIRS 通り)は、終わるまで待つことになる。
        """
        with self._lock:
            jobs = list(self._jobs.values())
            executor, self._executor = self._executor, None
        for job in jobs:
            with job.lock:
                job.cancel_requested = True
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    # --- 中身 ----------------------------------------------------------------------

    def _get_executor(self) -> Executor:
        if self._executor is None:
            self._executor = self._executor_factory(self.workers)
        return self._executor

    def _forget_old(self) -> None:
        """終わってから KEEP_FINISHED_SECONDS たったジョブを消す(self._lock の中で呼ぶ)。"""
        now = self._clock()
        old = []
        for job in self._jobs.values():
            with job.lock:
                finished_at = job.finished_at
            if finished_at is not None and now - finished_at > KEEP_FINISHED_SECONDS:
                old.append(job.id)
        for job_id in old:
            del self._jobs[job_id]

    def _should_stop(self, job: SweepJob) -> bool:
        with job.lock:
            abandoned = self._clock() - job.last_polled > ABANDON_SECONDS
            return job.cancel_requested or abandoned

    def _finish(self, job: SweepJob, status: JobStatus, **changes: Any) -> None:
        with job.lock:
            job.status = status
            job.finished_at = self._clock()
            job.elapsed_seconds = job.finished_at - job.created_at
            for key, value in changes.items():
                setattr(job, key, value)

    def _run(self, job: SweepJob, executor: Executor, build: ResultBuilder | None) -> None:
        spec = job.spec
        futures: dict[Future[PairsOutcome], tuple[int, int]] = {}
        try:
            for first, end in chunk_ranges(len(spec.pairs), self.workers):
                if self._should_stop(job):
                    break  # 残りは渡さない(下の while で中止として片づける)
                future = executor.submit(
                    self._runner, spec.bars, spec.segments, spec.costs, spec.pairs[first:end], first
                )
                futures[future] = (first, end)
            outcomes: dict[int, PairsOutcome] = {}
            pending = set(futures)
            while pending:
                if self._should_stop(job):
                    for future in pending:
                        future.cancel()
                    self._finish(job, "cancelled")
                    return
                finished, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                for future in finished:
                    first, end = futures[future]
                    outcomes[first] = future.result()
                    with job.lock:
                        job.done += end - first
        except Exception as error:
            for future in futures:
                future.cancel()
            if isinstance(error, BrokenExecutor):
                # 計算用のプロセスが落ちた(メモリ不足など)。次のジョブでは作り直す
                with self._lock:
                    if self._executor is executor:
                        self._executor = None
            if self._should_stop(job):
                # 中止・サーバーの停止の途中で起きた失敗(止めた executor にかたまりを渡そうとした、など)は、中止として扱う
                self._finish(job, "cancelled")
                return
            logger.exception("総当たりの計算に失敗しました(ジョブ %s)", job.id)
            self._finish(job, "failed", error_kind="internal", error_message=INTERNAL_ERROR)
            return

        # 誤り(docs/sweep.md 5章の7)は、組み合わせの順番でいちばん前のものを報告する(順番に計算したときと同じ)
        failed = [o for o in outcomes.values() if o.error_index is not None]
        if failed:
            first_error = min(failed, key=lambda o: o.error_index)  # type: ignore[arg-type,return-value]
            self._finish(
                job,
                "failed",
                error_kind=first_error.error_kind,
                error_message=first_error.error_message,
            )
            return
        rows: list[SweepRow] = []
        for first in sorted(outcomes):
            rows.extend(outcomes[first].rows)
        try:
            output = build(tuple(rows)) if build is not None else None
        except Exception:
            logger.exception("総当たりの結果をまとめられませんでした(ジョブ %s)", job.id)
            self._finish(job, "failed", error_kind="internal", error_message=INTERNAL_ERROR)
            return
        self._finish(job, "done", rows=tuple(rows), output=output)

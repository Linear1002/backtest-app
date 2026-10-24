"""総当たりの API(POST/GET/DELETE /api/sweeps、docs/sweep.md 10章)のテスト。架空データ(DEMO)だけを使う。

計算は、テストを速くするためにスレッドで動かす(SweepJobs に executor_factory を渡す)。
本物のプロセスで動かすテストも1つだけある(test_process_pool_gives_the_same_result)。
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.api.convert import to_engine_bars
from backend.main import create_app
from backend.marketdata.models import SymbolId
from backend.marketdata.service import MarketDataService
from backend.marketdata.synthetic import DemoDataSource
from backend.settings import Settings
from backend.sweeps import SweepJobs
from engine.reference.sweep import PairsOutcome, SweepCosts, SweepGrid, run_pairs, run_sweep

HOLDOUT = "2025-08-01"


@pytest.fixture(autouse=True)
def cpp_not_built(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "backtest_cpp", None)


def thread_jobs(**kwargs) -> SweepJobs:
    return SweepJobs(2, executor_factory=lambda n: ThreadPoolExecutor(max_workers=n), **kwargs)


def make_client(tmp_path, jobs: SweepJobs | None = None, service=None) -> TestClient:
    return TestClient(
        create_app(Settings(data_dir=tmp_path), service=service, sweeps=jobs or thread_jobs())
    )


@pytest.fixture
def client(tmp_path) -> TestClient:
    return make_client(tmp_path)


def body(**changes) -> dict:
    request = {
        "symbol_id": "DEMO:1003",
        "holdout_start_date": HOLDOUT,
        "grid": {
            "short_min": 3,
            "short_max": 12,
            "short_step": 3,
            "long_min": 15,
            "long_max": 45,
            "long_step": 10,
        },
        "params": {"fee_rate_pct": 0.1, "slippage_rate_pct": 0.05, "initial_cash": 1_000_000},
    }
    for key, value in changes.items():
        if key in ("grid", "params"):
            request[key] = {**request[key], **value}
        else:
            request[key] = value
    return request


def wait_done(client: TestClient, job_id: str, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/api/sweeps/{job_id}").json()
        if status["status"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError("総当たりが時間内に終わりませんでした")


def demo_bars(code: str):
    return to_engine_bars(DemoDataSource().get_daily_bars(SymbolId("DEMO", code)))


# --- メタ情報 ------------------------------------------------------------------------


def test_meta_lists_sweep_engines(client: TestClient) -> None:
    engines = {e["id"]: e for e in client.get("/api/meta").json()["sweep_engines"]}
    assert engines["python"]["available"] and engines["python"]["max_pairs"] == 2000
    assert "2個のプロセス" in engines["python"]["note"]
    assert not engines["cpp"]["available"] and not engines["cuda"]["available"]
    assert engines["cuda"]["max_pairs"] == 20000


# --- 計算して結果を受け取る ------------------------------------------------------------


def test_sweep_runs_and_matches_the_reference(client: TestClient) -> None:
    started = client.post("/api/sweeps", json=body())
    assert started.status_code == 202
    first = started.json()
    assert first["status"] == "running" and first["total"] == 16 and first["result"] is None
    status = wait_done(client, first["id"])
    assert status["status"] == "done" and status["done"] == 16
    assert status["elapsed_ms"] is not None and status["elapsed_ms"] >= 0
    result = status["result"]
    assert result["count"] == 16
    assert result["grid"]["short_values"] == [3, 6, 9, 12]
    assert result["grid"]["long_values"] == [15, 25, 35, 45]
    assert [s["name"] for s in result["segments"]] == ["in_sample", "out_of_sample"]
    assert result["segments"][0]["end_date"] == "2025-07-31"
    assert result["segments"][1]["start_date"] == HOLDOUT

    # 1つ1つの成績は、リファレンスの総当たりとまったく同じ
    bars = demo_bars("1003")
    reference = run_sweep(
        bars,
        bars[0].date,
        bars[-1].date,
        SweepGrid(3, 12, 3, 15, 45, 10),
        SweepCosts(0.001, 0.0005, 1_000_000.0),
        dt.date(2025, 8, 1),
    )
    rows = iter(reference.rows)
    for combo in result["combos"]:
        for segment in ("in_sample", "out_of_sample"):
            row = next(rows)
            assert (row.short_window, row.long_window) == (
                combo["short_window"],
                combo["long_window"],
            )
            assert combo[segment] == dataclasses.asdict(row.metrics)

    rankings = {r["objective"]: r for r in result["rankings"]}
    assert set(rankings) == {"sharpe_ratio", "total_return", "max_drawdown"}
    sharpe = rankings["sharpe_ratio"]
    best = result["combos"][sharpe["best_index"]]
    assert sharpe["order"][0] == sharpe["best_index"]
    defined = [
        c["in_sample"]["sharpe_ratio"]
        for c in result["combos"]
        if c["in_sample"]["sharpe_ratio"] is not None
    ]
    assert best["in_sample"]["sharpe_ratio"] == max(defined)
    assert sharpe["out_of_sample_ranked"] >= 1

    kinds = [n["kind"] for n in result["notes"]]
    assert kinds[:2] == ["trials", "selection_bias"]
    assert "16通り" in result["notes"][0]["message"]
    assert "demo_data" in kinds and "survivorship" not in kinds
    # 検証期間は1年未満(2025-08-01〜2026-07-31 は 245 営業日に届かない)
    assert any(
        n["kind"] == "annualized_reference" and "検証期間" in n["message"] for n in result["notes"]
    )


def test_without_holdout_there_is_only_one_segment(client: TestClient) -> None:
    started = client.post("/api/sweeps", json=body(holdout_start_date=None))
    status = wait_done(client, started.json()["id"])
    result = status["result"]
    assert [s["name"] for s in result["segments"]] == ["in_sample"]
    assert all(c["out_of_sample"] is None for c in result["combos"])
    sharpe = next(r for r in result["rankings"] if r["objective"] == "sharpe_ratio")
    assert sharpe["best_out_of_sample_rank"] is None and sharpe["rank_correlation"] is None
    kinds = [n["kind"] for n in result["notes"]]
    assert "no_holdout" in kinds and "selection_bias" not in kinds


def test_process_pool_gives_the_same_result(tmp_path) -> None:
    """本物のプロセス(ProcessPoolExecutor)で計算しても、同じ結果になる(受け渡しできる形になっている)。"""
    small = {
        "short_min": 5,
        "short_max": 10,
        "short_step": 5,
        "long_min": 20,
        "long_max": 30,
        "long_step": 10,
    }
    with make_client(tmp_path, jobs=SweepJobs(2)) as process_client:
        status = wait_done(
            process_client, process_client.post("/api/sweeps", json=body(grid=small)).json()["id"]
        )
    with make_client(tmp_path / "t") as thread_client:
        expected = wait_done(
            thread_client, thread_client.post("/api/sweeps", json=body(grid=small)).json()["id"]
        )
    assert status["status"] == "done"
    assert status["result"]["combos"] == expected["result"]["combos"]


# --- 入力チェック(docs/sweep.md 5章) ---------------------------------------------------


def errors_of(response) -> dict:
    assert response.status_code == 422, response.json()
    return {e["field"]: e["message"] for e in response.json()["errors"]}


@pytest.mark.parametrize(
    ("grid", "expected"),
    [
        ({"short_min": 0}, {"short_min": "日数と刻みは1以上の整数で入力してください"}),
        ({"short_step": 2.5}, {"short_step": "日数と刻みは1以上の整数で入力してください"}),
        ({"long_max": 1001}, {"long_max": "日数と刻みは1000以下で入力してください"}),
        (
            {"short_min": 20, "short_max": 10},
            {"short_min": "短期の日数の範囲は、最小を最大以下にしてください"},
        ),
        (
            {"long_min": 50, "long_max": 40},
            {"long_min": "長期の日数の範囲は、最小を最大以下にしてください"},
        ),
        (
            {"short_min": 50, "short_max": 60, "long_min": 10, "long_max": 40},
            {
                "grid": "短期の日数が長期の日数より小さい組み合わせがありません。範囲を見直してください"
            },
        ),
    ],
)
def test_grid_errors(client: TestClient, grid: dict, expected: dict) -> None:
    assert errors_of(client.post("/api/sweeps", json=body(grid=grid))) == expected


def test_too_many_pairs_for_the_python_engine(client: TestClient) -> None:
    grid = {
        "short_min": 1,
        "short_max": 100,
        "short_step": 1,
        "long_min": 2,
        "long_max": 200,
        "long_step": 1,
    }
    errors = errors_of(client.post("/api/sweeps", json=body(grid=grid)))
    assert list(errors) == ["grid"]
    assert (
        errors["grid"].startswith("組み合わせが多すぎます(") and "2,000通りまで" in errors["grid"]
    )


def test_grid_and_cost_errors_are_reported_together(client: TestClient) -> None:
    errors = errors_of(
        client.post("/api/sweeps", json=body(grid={"short_min": 0}, params={"fee_rate_pct": 10}))
    )
    assert errors == {
        "short_min": "日数と刻みは1以上の整数で入力してください",
        "fee_rate_pct": "手数料率とスリッページ率は10%未満で入力してください",
    }


@pytest.mark.parametrize(
    ("holdout", "message"),
    [
        ("2022-01-04", "検証期間の開始日は、期間の開始日より後、終了日以前の日付にしてください"),
        ("2026-08-03", "検証期間の開始日は、期間の開始日より後、終了日以前の日付にしてください"),
        (
            "2022-01-06",
            "選ぶ期間(検証期間より前)の営業日が3日未満です。検証期間の開始日を遅くしてください",
        ),
        ("2026-07-30", "検証期間の営業日が3日未満です。検証期間の開始日を早くしてください"),
    ],
)
def test_holdout_errors(client: TestClient, holdout: str, message: str) -> None:
    assert errors_of(client.post("/api/sweeps", json=body(holdout_start_date=holdout))) == {
        "holdout_start_date": message
    }


def test_period_and_request_errors(client: TestClient) -> None:
    reversed_period = body(start_date="2025-06-30", end_date="2025-01-01", holdout_start_date=None)
    assert errors_of(client.post("/api/sweeps", json=reversed_period)) == {
        "start_date": "開始日は終了日より前の日付にしてください"
    }
    assert errors_of(client.post("/api/sweeps", json=body(engine="cuda")))["engine"].startswith(
        "総当たりでは CUDA 版(GPU) はまだ使えません"
    )
    assert "engine" in errors_of(client.post("/api/sweeps", json=body(engine="fortran")))
    assert errors_of(client.post("/api/sweeps", json=body(strategy_id="rsi_reversal"))) == {
        "strategy_id": "この戦略はまだ使えません"
    }
    # 入れ子の欄の名前は、欄の名前だけにする(grid.short_min → short_min)
    assert errors_of(client.post("/api/sweeps", json=body(grid={"short_min": "abc"}))) == {
        "short_min": "数値で入力してください"
    }


class BrokenDemo(DemoDataSource):
    """DEMO:1001 の 2022-10-20 だけ、調整係数が Null の日足を返す。"""

    def get_daily_bars(self, symbol_id, start=None, end=None):
        bars = super().get_daily_bars(symbol_id, start, end)
        if symbol_id.code != "1001":
            return bars
        return [
            dataclasses.replace(b, adj_factor=None) if b.date == dt.date(2022, 10, 20) else b
            for b in bars
        ]


def test_data_anomaly_in_the_longest_load_range_is_rejected_before_running(tmp_path) -> None:
    """いちばん長い長期日数の読み込む範囲にだけある異常も、計算を始める前に 422 にする(5章の6)。"""
    client = make_client(tmp_path, service=MarketDataService([BrokenDemo()]))
    request = body(
        symbol_id="DEMO:1001",
        start_date="2023-01-04",
        end_date="2024-12-30",
        holdout_start_date=None,
        grid={
            "short_min": 5,
            "short_max": 10,
            "short_step": 5,
            "long_min": 20,
            "long_max": 60,
            "long_step": 20,
        },
    )
    response = client.post("/api/sweeps", json=request)
    assert response.status_code == 422
    assert (
        "データに異常がある" in response.json()["detail"]
        and "2022-10-20" in response.json()["detail"]
    )
    # 長期40日までなら、その日は読み込む範囲に入らないので計算できる
    ok = client.post("/api/sweeps", json={**request, "grid": {**request["grid"], "long_max": 40}})
    assert ok.status_code == 202


# --- ジョブ(途中経過・中止・失敗) ------------------------------------------------------


def test_unknown_job_is_404_with_a_japanese_message(client: TestClient) -> None:
    response = client.get("/api/sweeps/nothing")
    assert response.status_code == 404
    assert "見つかりません" in response.json()["detail"]
    assert client.delete("/api/sweeps/nothing").status_code == 404


def blocking_runner(release: threading.Event):
    def runner(bars, segments, costs, pairs, first_index):
        release.wait(timeout=30)
        return run_pairs(bars, segments, costs, pairs, first_index)

    return runner


def test_cancel_stops_the_job(tmp_path) -> None:
    release = threading.Event()
    client = make_client(tmp_path, jobs=thread_jobs(runner=blocking_runner(release)))
    job_id = client.post("/api/sweeps", json=body()).json()["id"]
    assert client.get(f"/api/sweeps/{job_id}").json()["status"] == "running"
    cancelled = client.delete(f"/api/sweeps/{job_id}")
    assert cancelled.status_code == 200
    release.set()
    status = wait_done(client, job_id)
    assert status["status"] == "cancelled" and status["result"] is None


def test_only_two_jobs_run_at_once(tmp_path) -> None:
    release = threading.Event()
    client = make_client(tmp_path, jobs=thread_jobs(runner=blocking_runner(release)))
    first = client.post("/api/sweeps", json=body()).json()["id"]
    second = client.post("/api/sweeps", json=body()).json()["id"]
    third = client.post("/api/sweeps", json=body())
    assert third.status_code == 409
    assert "ほかの総当たりを計算しています" in third.json()["detail"]
    release.set()
    assert wait_done(client, first)["status"] == "done"
    assert wait_done(client, second)["status"] == "done"
    assert client.post("/api/sweeps", json=body()).status_code == 202


def test_failure_reports_the_first_pair_in_combo_order(tmp_path) -> None:
    """計算の途中の誤りは、組み合わせの順番でいちばん前のものを報告する(順番に計算したときと同じ)。"""

    def runner(bars, segments, costs, pairs, first_index):
        # 位置 9 と 3 で誤りがあることにする(かたまりの終わる順番に関係なく、3 を報告する)
        for offset in range(len(pairs)):
            index = first_index + offset
            if index in (3, 9):
                return PairsOutcome(
                    (), index, "data", f"株数が大きすぎて計算できません(位置 {index})"
                )
        return run_pairs(bars, segments, costs, pairs, first_index)

    client = make_client(tmp_path, jobs=thread_jobs(runner=runner))
    status = wait_done(client, client.post("/api/sweeps", json=body()).json()["id"])
    assert status["status"] == "failed" and status["result"] is None
    assert (
        status["error"]["detail"]
        == "データに異常があるため計算できません:株数が大きすぎて計算できません(位置 3)"
    )


def test_unexpected_exception_in_a_worker_is_reported_in_japanese(tmp_path) -> None:
    def runner(*args):
        raise RuntimeError("boom (internal detail)")

    client = make_client(tmp_path, jobs=thread_jobs(runner=runner))
    status = wait_done(client, client.post("/api/sweeps", json=body()).json()["id"])
    assert status["status"] == "failed"
    assert "想定していないエラー" in status["error"]["detail"]
    assert "boom" not in status["error"]["detail"]  # 中身はログにだけ出す


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_job_without_polling_is_abandoned_and_old_jobs_are_forgotten(tmp_path) -> None:
    release = threading.Event()
    clock = FakeClock()
    jobs = thread_jobs(runner=blocking_runner(release), clock=clock)
    client = make_client(tmp_path, jobs=jobs)
    job_id = client.post("/api/sweeps", json=body()).json()["id"]
    clock.now += 61  # 61秒、問い合わせがない
    job = jobs._jobs[job_id]
    deadline = time.monotonic() + 10
    while job.status == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
    release.set()
    assert job.status == "cancelled"
    clock.now += 30 * 60 + 1  # 終わってから30分たつと消える
    assert client.get(f"/api/sweeps/{job_id}").status_code == 404

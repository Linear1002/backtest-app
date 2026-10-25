"""比較の基準:買い持ち(docs/benchmark.md)の API のテスト。架空データ(DEMO)だけを使う。"""

from __future__ import annotations

import datetime as dt
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.api.convert import to_engine_bars
from backend.main import create_app
from backend.marketdata.models import SymbolId
from backend.marketdata.synthetic import DemoDataSource
from backend.settings import Settings
from backend.sweeps import SweepJobs
from engine.reference import MaCrossParams
from engine.reference.benchmark import run_buy_and_hold


@pytest.fixture(autouse=True)
def cpp_not_built(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "backtest_cpp", None)


@pytest.fixture
def client(tmp_path) -> TestClient:
    jobs = SweepJobs(2, executor_factory=lambda n: ThreadPoolExecutor(max_workers=n))
    return TestClient(create_app(Settings(data_dir=tmp_path), sweeps=jobs))


def demo_bars(code: str):
    return to_engine_bars(DemoDataSource().get_daily_bars(SymbolId("DEMO", code)))


PARAMS = {"fee_rate_pct": 0.1, "slippage_rate_pct": 0.05, "initial_cash": 1_000_000}


def test_backtest_result_has_buy_and_hold_with_the_same_period_and_costs(
    client: TestClient,
) -> None:
    body = client.post(
        "/api/backtests",
        json={
            "symbol_id": "DEMO:1003",
            "start_date": "2024-06-03",
            "end_date": "2025-12-30",
            # 分割前は1株1万円を超えるので、100株を買えるように300万円にする
            "params": {**PARAMS, "initial_cash": 3_000_000, "short_window": 5, "long_window": 25},
        },
    ).json()
    benchmark = body["benchmark"]
    assert benchmark["label"] == "買い持ち" and benchmark["status"] == "bought"

    bars = demo_bars("1003")
    params = MaCrossParams(5, 25, 0.001, 0.0005, 3_000_000.0)
    reference = run_buy_and_hold(bars, dt.date(2024, 6, 3), dt.date(2025, 12, 30), params)
    assert benchmark["signal_date"] == reference.signal_date.isoformat()
    assert benchmark["fill"]["date"] == reference.fill.date.isoformat()
    assert benchmark["fill"]["shares"] == reference.fill.shares
    # 保有中に 1:2 の分割(2025-04-01)があり、持ち株数が2倍になる
    (event,) = benchmark["events"]
    assert event["date"] == "2025-04-01" and event["shares_after"] == 2 * event["shares_before"]
    assert benchmark["metrics"]["total_return"] == reference.metrics.total_return
    assert benchmark["metrics"]["final_equity"] == reference.final_equity
    assert benchmark["open_position_at_end"] is True
    # 日々の買い持ちの資産額は、移動平均クロスの日々の数値と同じ日に並ぶ
    assert [d["date"] for d in body["daily"]] == [d.date.isoformat() for d in reference.daily]
    assert [d["benchmark_equity"] for d in body["daily"]] == [d.equity for d in reference.daily]
    assert "benchmark" in [n["kind"] for n in body["notes"]]


def test_buy_and_hold_that_cannot_buy_is_reported(client: TestClient) -> None:
    """DEMO:1009 は株価が高く、100万円では100株を買えない。"""
    body = client.post(
        "/api/backtests",
        json={"symbol_id": "DEMO:1009", "params": {**PARAMS, "short_window": 5, "long_window": 25}},
    ).json()
    benchmark = body["benchmark"]
    assert benchmark["status"] == "insufficient_cash" and benchmark["fill"] is None
    assert benchmark["skipped"]["cash"] == 1_000_000
    assert benchmark["metrics"]["total_return"] == 0.0
    assert all(d["benchmark_equity"] == 1_000_000 for d in body["daily"])


def wait_done(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status = client.get(f"/api/sweeps/{job_id}").json()
        if status["status"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError("総当たりが時間内に終わりませんでした")


def test_sweep_segments_have_buy_and_hold_and_beat_counts(client: TestClient) -> None:
    request = {
        "symbol_id": "DEMO:1003",
        "holdout_start_date": "2025-08-01",
        "grid": {
            "short_min": 3,
            "short_max": 12,
            "short_step": 3,
            "long_min": 15,
            "long_max": 45,
            "long_step": 10,
        },
        "params": PARAMS,
    }
    status = wait_done(client, client.post("/api/sweeps", json=request).json()["id"])
    result = status["result"]
    bars = demo_bars("1003")
    params = MaCrossParams(3, 15, 0.001, 0.0005, 1_000_000.0)
    values = {}
    for segment in result["segments"]:
        start = dt.date.fromisoformat(segment["start_date"])
        end = dt.date.fromisoformat(segment["end_date"])
        reference = run_buy_and_hold(bars, start, end, params)
        assert segment["benchmark"]["total_return"] == reference.metrics.total_return
        assert segment["benchmark"]["sharpe_ratio"] == reference.metrics.sharpe_ratio
        values[segment["name"]] = segment["benchmark"]
    # 買い持ちより良かった組み合わせの数(シャープレシオは大きいほど、最大ドローダウンは小さいほど良い)
    for ranking in result["rankings"]:
        objective = ranking["objective"]
        larger = objective != "max_drawdown"
        for segment in ("in_sample", "out_of_sample"):
            bench = values[segment][objective]
            expected = sum(
                1
                for combo in result["combos"]
                if combo[segment][objective] is not None
                and (
                    combo[segment][objective] > bench
                    if larger
                    else combo[segment][objective] < bench
                )
            )
            assert ranking[f"{segment}_beats_benchmark"] == expected, (objective, segment)
    assert "benchmark" in [n["kind"] for n in result["notes"]]

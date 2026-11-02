"""ウォークフォワード分析の API(POST/GET/DELETE /api/walkforwards、docs/walkforward.md 10章)のテスト。架空データ(DEMO)だけを使う。"""

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
from engine.reference.sweep import SweepCosts, SweepGrid
from engine.reference.walkforward import WalkForwardSettings, run_walkforward


@pytest.fixture(autouse=True)
def cpp_not_built(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "backtest_cpp", None)


@pytest.fixture
def client(tmp_path) -> TestClient:
    jobs = SweepJobs(2, executor_factory=lambda n: ThreadPoolExecutor(max_workers=n))
    return TestClient(create_app(Settings(data_dir=tmp_path), sweeps=jobs))


GRID = {
    "short_min": 3,
    "short_max": 12,
    "short_step": 3,
    "long_min": 15,
    "long_max": 45,
    "long_step": 10,
}
PARAMS = {"fee_rate_pct": 0.1, "slippage_rate_pct": 0.05, "initial_cash": 1_000_000}


def body(**changes) -> dict:
    request = {
        "symbol_id": "DEMO:1003",
        "grid": GRID,
        "params": PARAMS,
        "objective": "sharpe_ratio",
        "in_sample_months": 12,
        "out_of_sample_months": 6,
    }
    for key, value in changes.items():
        request[key] = {**request[key], **value} if key in ("grid", "params") else value
    return request


def wait_done(client: TestClient, job_id: str, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/api/walkforwards/{job_id}").json()
        if status["status"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError("ウォークフォワード分析が時間内に終わりませんでした")


def errors_of(response) -> dict[str, str]:
    assert response.status_code == 422, response.text
    return {e["field"]: e["message"] for e in response.json()["errors"]}


def test_runs_and_matches_the_reference(client: TestClient) -> None:
    started = client.post("/api/walkforwards", json=body())
    assert started.status_code == 202
    assert started.json()["total"] == 16  # 組み合わせの数(すべての区切りの選ぶ期間を計算して1つ)
    status = wait_done(client, started.json()["id"])
    assert status["status"] == "done" and status["done"] == 16
    result = status["result"]

    bars = to_engine_bars(DemoDataSource().get_daily_bars(SymbolId("DEMO", "1003")))
    reference = run_walkforward(
        bars,
        bars[0].date,
        bars[-1].date,
        SweepGrid(3, 12, 3, 15, 45, 10),
        SweepCosts(fee_rate=0.001, slippage_rate=0.0005, initial_cash=1_000_000.0),
        WalkForwardSettings("sharpe_ratio", 12, 6),
    )
    assert len(result["windows"]) == len(reference.windows)
    assert result["count"] == 16
    assert result["runs"] == 16 * len(reference.windows) + len(reference.windows)
    for out, ref in zip(result["windows"], reference.windows, strict=True):
        chosen = out["chosen"]
        assert (chosen["short_window"], chosen["long_window"]) == ref.choice.pair
        assert out["in_sample_value"] == ref.choice.value
        assert out["out_of_sample"]["start_date"] == ref.window.out_of_sample.start.isoformat()
        assert out["out_of_sample_metrics"]["total_return"] == ref.out_of_sample.total_return
        assert out["liquidated_equity"] == ref.liquidated_equity
    assert [d["equity"] for d in result["daily"]] == [d.equity for d in reference.daily]
    assert result["metrics"]["total_return"] == reference.metrics.total_return
    assert result["metrics"]["sharpe_ratio"] == reference.metrics.sharpe_ratio
    assert result["choice_changes"] == reference.choice_changes
    assert result["beats_benchmark"] == reference.beats_benchmark
    assert result["benchmark"]["status"] == "bought"
    # 区切り1の選ぶ期間だけ、長期45日のウォームアップがそろう日まで遅れる
    first = result["windows"][0]
    assert first["requested_in_sample_start"] == "2022-01-04"
    assert first["in_sample"]["start_date"] > "2022-01-04"
    # 最後の区切りのあとに残った日は使わない
    assert result["unused"] is not None
    kinds = [n["kind"] for n in result["notes"]]
    for kind in ("walkforward_stitching", "walkforward_trials", "walkforward_liquidation"):
        assert kind in kinds
    assert "walkforward_unused" in kinds and "benchmark" in kinds and "demo_data" in kinds


def test_settings_errors_are_reported_with_grid_errors(client: TestClient) -> None:
    response = client.post(
        "/api/walkforwards",
        json=body(
            objective="max_drawdown",
            in_sample_months=0,
            out_of_sample_months=6.5,
            grid={"short_step": 0},
        ),
    )
    errors = errors_of(response)
    assert errors["objective"] == "1位を選ぶ基準は、シャープレシオか総リターンを選んでください"
    assert errors["in_sample_months"] == "選ぶ期間の長さは1〜120か月の整数で入力してください"
    assert errors["out_of_sample_months"] == "使う期間の長さは1〜60か月の整数で入力してください"
    assert errors["short_step"] == "日数と刻みは1以上の整数で入力してください"


def test_no_windows(client: TestClient) -> None:
    response = client.post(
        "/api/walkforwards",
        json=body(start_date="2025-01-06", end_date="2025-12-30", in_sample_months=12),
    )
    assert errors_of(response) == {
        "windows": "期間が短すぎて、選ぶ期間(12か月)と使う期間(6か月)を1回も取れません。"
        "期間を広げるか、選ぶ期間・使う期間を短くしてください"
    }


def test_too_many_runs(client: TestClient) -> None:
    # 1〜20 × 21〜120 = 2,000通り × 区切り5回 = 10,000回 > 4,000回
    grid = {
        "short_min": 1,
        "short_max": 20,
        "short_step": 1,
        "long_min": 21,
        "long_max": 120,
        "long_step": 1,
    }
    response = client.post("/api/walkforwards", json=body(grid=grid, in_sample_months=24))
    message = errors_of(response)["grid"]
    assert message.startswith(
        "計算が多すぎます(2,000通り × 区切り5回 = 10,000回)。このエンジンでは4,000回までです。"
    )


def test_business_day_errors_come_before_too_many_runs(client: TestClient) -> None:
    """7章:区切りの営業日(6)は、計算の量(7)より先に確かめる。"""
    grid = {
        "short_min": 1,
        "short_max": 20,
        "short_step": 1,
        "long_min": 21,
        "long_max": 120,
        "long_step": 1,
    }
    response = client.post(
        "/api/walkforwards", json=body(grid=grid, in_sample_months=1, out_of_sample_months=1)
    )
    errors = errors_of(response)
    assert list(errors) == ["in_sample_months"]
    assert "最長120日" in errors["in_sample_months"]


def test_alignment_error_goes_to_the_in_sample_field(client: TestClient) -> None:
    # データの初日から、選ぶ期間1か月:長期45日のウォームアップを除くと、区切り1の選ぶ期間が残らない
    response = client.post(
        "/api/walkforwards", json=body(in_sample_months=1, out_of_sample_months=1)
    )
    message = errors_of(response)["in_sample_months"]
    assert "最長45日" in message and "区切り1の選ぶ期間の営業日が3日未満" in message


def test_unknown_and_other_kind_of_job_are_404(client: TestClient) -> None:
    assert client.get("/api/walkforwards/nothing").status_code == 404
    sweep = client.post(
        "/api/sweeps", json={"symbol_id": "DEMO:1003", "grid": GRID, "params": PARAMS}
    ).json()
    # 総当たりの id は、ウォークフォワードとしては見つからない(逆も同じ)
    assert client.get(f"/api/walkforwards/{sweep['id']}").status_code == 404
    walk = client.post("/api/walkforwards", json=body()).json()
    assert client.get(f"/api/sweeps/{walk['id']}").status_code == 404
    assert client.delete(f"/api/sweeps/{walk['id']}").status_code == 404
    assert wait_done(client, walk["id"])["status"] == "done"
    detail = client.get("/api/walkforwards/nothing").json()["detail"]
    assert detail.startswith("そのウォークフォワード分析は見つかりません")


def test_cancel(client: TestClient) -> None:
    started = client.post("/api/walkforwards", json=body()).json()
    cancelled = client.delete(f"/api/walkforwards/{started['id']}")
    assert cancelled.status_code == 200
    status = wait_done(client, started["id"])
    assert status["status"] in ("cancelled", "done")  # 先に終わることもある
    assert status["status"] != "failed"


def test_period_in_the_request(client: TestClient) -> None:
    """期間を指定すると、区切りは開始日から月を足して決まる(docs/walkforward.md 3章)。"""
    status = wait_done(
        client,
        client.post(
            "/api/walkforwards",
            json=body(
                start_date="2023-01-04",
                end_date="2025-12-30",
                in_sample_months=12,
                out_of_sample_months=6,
            ),
        ).json()["id"],
    )
    windows = status["result"]["windows"]
    assert [w["out_of_sample"]["start_date"] for w in windows] == [
        "2024-01-04",
        "2024-07-04",
        "2025-01-04",
    ]
    assert (
        windows[-1]["out_of_sample"]["end_date"]
        == (dt.date(2025, 7, 4) - dt.timedelta(days=1)).isoformat()
    )
    # 開始日より前に十分なデータがあるので、区切り1の選ぶ期間も遅れない
    assert windows[0]["in_sample"]["start_date"] == "2023-01-04"

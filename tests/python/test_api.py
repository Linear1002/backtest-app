"""API のテスト。架空データ(DEMO)だけを使うので、APIキーもネットワークもいらない。"""

from __future__ import annotations

import datetime as dt
import sys
import types

import pytest
from fastapi.testclient import TestClient

from backend.api.convert import to_engine_bars
from backend.main import create_app
from backend.marketdata.models import SymbolId
from backend.marketdata.synthetic import DemoDataSource
from backend.settings import Settings
from engine.reference import Bar, MaCrossParams, run_backtest
from engine.reference.contract import to_contract_dict


@pytest.fixture
def client(tmp_path) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path)))


def demo_engine_bars(code: str) -> list[Bar]:
    return to_engine_bars(DemoDataSource().get_daily_bars(SymbolId("DEMO", code)))


# --- 参照系 -------------------------------------------------------------------------


def test_meta_lists_demo_source_and_engines(client: TestClient) -> None:
    body = client.get("/api/meta").json()
    assert [s["id"] for s in body["data_sources"]] == ["demo"]
    engines = {e["id"]: e["available"] for e in body["engines"]}
    assert engines == {"python": True, "cpp": False}
    assert body["trading_days_per_year"] == 245


def test_symbol_search(client: TestClient) -> None:
    def ids(q: str, **params) -> list[str]:
        response = client.get("/api/symbols", params={"q": q, **params})
        return [item["id"] for item in response.json()["items"]]

    assert ids("1003") == ["DEMO:1003"]
    assert ids("ゆうなぎ") == ["DEMO:1003"]
    assert ids("１００８") == ["DEMO:1008"]
    assert len(ids("", limit=3)) == 3
    item = client.get("/api/symbols", params={"q": "1009"}).json()["items"][0]
    assert item["source_id"] == "demo" and "100株" in item["description"]


def test_symbol_detail_shows_range_actions_and_halts(client: TestClient) -> None:
    body = client.get("/api/symbols/DEMO:1008").json()
    assert body["market"] == {
        "code": "DEMO",
        "name": "架空市場(デモ用)",
        "currency": "JPY",
        "lot_size": 100,
    }
    assert (
        body["range"]["first_date"] == "2022-01-04" and body["range"]["last_date"] == "2026-07-31"
    )
    assert body["halted_days"] == 7
    assert body["corporate_actions"] == [
        {"date": "2025-03-12", "ex_rt": 1, "label": "株式分割", "adj_factor": 0.5}
    ]
    assert body["data_info"]["source_id"] == "demo"


def test_strategies_follow_spec_defaults(client: TestClient) -> None:
    items = client.get("/api/strategies").json()["items"]
    ma = next(s for s in items if s["id"] == "ma_cross")
    assert ma["available"]
    defaults = {p["key"]: p["default"] for p in ma["params"]}
    assert defaults == {
        "short_window": 5,
        "long_window": 25,
        "fee_rate_pct": 0.1,
        "slippage_rate_pct": 0.05,
        "initial_cash": 1_000_000,
    }
    assert any(not s["available"] for s in items)


# --- バックテスト -------------------------------------------------------------------


def test_default_backtest_matches_reference_engine(client: TestClient) -> None:
    response = client.post("/api/backtests", json={"symbol_id": "DEMO:1003"})
    assert response.status_code == 200
    body = response.json()

    bars = demo_engine_bars("1003")
    expected = run_backtest(
        bars,
        bars[0].date,
        bars[-1].date,
        MaCrossParams(5, 25, 0.1 / 100, 0.05 / 100, 1_000_000.0, 100),
    )
    assert body["params"]["fee_rate"] == 0.001 and body["params"]["slippage_rate"] == 0.0005
    assert body["metrics"]["total_return"] == expected.metrics.total_return
    assert body["metrics"]["trade_count"] == expected.metrics.trade_count
    assert len(body["daily"]) == len(expected.daily) == body["period"]["business_days"]
    assert [f["shares"] for f in body["fills"]] == [f.shares for f in expected.fills]
    assert body["events"][0]["ratio"] == "2/1"
    assert body["warmup"]["label"] == "ウォームアップ期間:なし"
    kinds = [n["kind"] for n in body["notes"]]
    assert "demo_data" in kinds and "warmup_shortage" in kinds and "survivorship" not in kinds
    assert all(0 <= d["drawdown"] <= 1 for d in body["daily"])


def test_backtest_with_period_and_warmup(client: TestClient) -> None:
    body = client.post(
        "/api/backtests",
        json={
            "symbol_id": "DEMO:1001",
            "start_date": "2025-01-04",  # 土曜日から始めてもよい
            "end_date": "2025-06-30",
            "params": {
                "short_window": 10,
                "long_window": 30,
                "fee_rate_pct": 0.2,
                "slippage_rate_pct": 0.1,
                "initial_cash": 3_000_000,
            },
        },
    ).json()
    assert body["period"]["first_business_day"] == "2025-01-06"
    assert body["warmup"]["valid_days"] == 30 and body["warmup"]["sufficient"]
    assert body["warmup"]["label"].startswith("ウォームアップに使った期間:")
    assert body["params"]["initial_cash"] == 3_000_000
    kinds = [n["kind"] for n in body["notes"]]
    assert "annualized_reference" in kinds and "warmup_shortage" not in kinds


def test_insufficient_cash_is_reported(client: TestClient) -> None:
    body = client.post("/api/backtests", json={"symbol_id": "DEMO:1009"}).json()
    assert body["insufficient_cash_count"] > 0 and body["fills"] == []
    assert any(n["kind"] == "insufficient_cash" for n in body["notes"])


# --- 入力チェック(docs/mvp.md 4.3) --------------------------------------------------


@pytest.mark.parametrize(
    ("params", "field", "message"),
    [
        (
            {"short_window": 25, "long_window": 5},
            "short_window",
            "短期の日数は長期の日数より小さくしてください",
        ),
        ({"short_window": 2.5}, "short_window", "日数は1以上の整数で入力してください"),
        ({"long_window": 0}, "long_window", "日数は1以上の整数で入力してください"),
        (
            {"fee_rate_pct": -0.1},
            "fee_rate_pct",
            "手数料率とスリッページ率は0以上で入力してください",
        ),
        (
            {"slippage_rate_pct": 10},
            "slippage_rate_pct",
            "手数料率とスリッページ率は10%未満で入力してください",
        ),
        ({"initial_cash": 0}, "initial_cash", "初期資金は1円以上で入力してください"),
        ({"initial_cash": 1_000_000_001}, "initial_cash", "初期資金は10億円以下で入力してください"),
        ({"short_window": "abc"}, "short_window", "数値で入力してください"),
    ],
)
def test_parameter_errors_are_japanese(
    client: TestClient, params: dict, field: str, message: str
) -> None:
    response = client.post("/api/backtests", json={"symbol_id": "DEMO:1001", "params": params})
    assert response.status_code == 422
    assert {"field": field, "message": message} in response.json()["errors"]


@pytest.mark.parametrize(
    ("period", "message"),
    [
        (
            {"start_date": "2025-06-30", "end_date": "2025-01-06"},
            "開始日は終了日より前の日付にしてください",
        ),
        (
            {"start_date": "2021-12-01"},
            "指定した期間のデータがありません(取得可能:2022-01-04〜2026-07-31)",
        ),
        (
            {"end_date": "2026-08-31"},
            "指定した期間のデータがありません(取得可能:2022-01-04〜2026-07-31)",
        ),
        (
            {"start_date": "2025-01-06", "end_date": "2025-01-07"},
            "期間が短すぎます。営業日が3日以上になるように指定してください",
        ),
        ({"start_date": "2025/01/06"}, "日付は YYYY-MM-DD の形で入力してください"),
    ],
)
def test_period_errors_are_japanese(client: TestClient, period: dict, message: str) -> None:
    response = client.post("/api/backtests", json={"symbol_id": "DEMO:1001", **period})
    assert response.status_code == 422
    assert message in [e["message"] for e in response.json()["errors"]]


def test_unknown_symbol_and_unconfigured_market(client: TestClient) -> None:
    missing = client.post("/api/backtests", json={"symbol_id": "DEMO:9999"})
    assert missing.status_code == 404
    tse = client.post("/api/backtests", json={"symbol_id": "TSE:7203"})
    assert tse.status_code == 404 and "JQUANTS_API_KEY" in tse.json()["detail"]
    invalid = client.get("/api/symbols/XYZ")
    assert invalid.status_code == 422 and invalid.json()["errors"][0]["field"] == "symbol_id"


def test_unavailable_strategy_and_engine(client: TestClient) -> None:
    strategy = client.post(
        "/api/backtests", json={"symbol_id": "DEMO:1001", "strategy_id": "rsi_reversal"}
    )
    assert strategy.status_code == 422
    engine = client.post("/api/backtests", json={"symbol_id": "DEMO:1001", "engine": "cpp"})
    assert engine.status_code == 422 and engine.json()["errors"][0]["field"] == "engine"


def test_cpp_engine_adapter_with_fake_module(client: TestClient, monkeypatch) -> None:
    """C++ 版の pybind11 モジュールの代わりに、契約どおりの dict を返す偽物を入れて、変換を確かめる。"""

    def run_ma_cross(rows, start, end, params):
        bars = [Bar(dt.date.fromisoformat(r[0]), *r[1:]) for r in rows]
        p = MaCrossParams(**params)
        result = run_backtest(bars, dt.date.fromisoformat(start), dt.date.fromisoformat(end), p)
        return to_contract_dict(result)

    fake = types.SimpleNamespace(run_ma_cross=run_ma_cross)
    monkeypatch.setitem(sys.modules, "backtest_cpp", fake)

    meta = client.get("/api/meta").json()
    assert {e["id"]: e["available"] for e in meta["engines"]}["cpp"]
    python = client.post("/api/backtests", json={"symbol_id": "DEMO:1004"}).json()
    cpp = client.post("/api/backtests", json={"symbol_id": "DEMO:1004", "engine": "cpp"}).json()
    assert cpp["engine"]["id"] == "cpp"
    for key in ("metrics", "daily", "signals", "fills", "events", "trades", "warmup"):
        assert cpp[key] == python[key], key

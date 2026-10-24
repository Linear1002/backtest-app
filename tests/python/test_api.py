"""API のテスト。架空データ(DEMO)だけを使うので、APIキーもネットワークもいらない。"""

from __future__ import annotations

import datetime as dt
import math
import sys
import types

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api.convert import to_engine_bars
from backend.main import create_app
from backend.marketdata.jquants import JQuantsClient, JQuantsDataSource
from backend.marketdata.models import SymbolId, SymbolInfo
from backend.marketdata.service import MarketDataService
from backend.marketdata.store import ParquetStore
from backend.marketdata.synthetic import DemoDataSource
from backend.settings import Settings
from engine.reference import Bar, MaCrossParams, run_backtest
from engine.reference.contract import to_contract_dict


@pytest.fixture(autouse=True)
def cpp_not_built(monkeypatch) -> None:
    """C++ 版がビルドされていても、テストの結果が変わらないようにする(使うテストは偽物を入れ直す)。"""
    monkeypatch.setitem(sys.modules, "backtest_cpp", None)


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
        "trading_days_per_year": 245,
    }
    assert (
        body["range"]["first_date"] == "2022-01-04" and body["range"]["last_date"] == "2026-07-31"
    )
    assert body["halted_days"] == 7
    assert body["corporate_actions"] == [
        {
            "date": "2025-03-12",
            "ex_rt": 1,
            "label": "株式分割",
            "adj_factor": 0.5,
            "changes_shares": True,
        }
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
        ({"long_window": 1001}, "long_window", "日数は1000以下で入力してください"),
        ({"short_window": 1e21}, "short_window", "日数は1000以下で入力してください"),
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
        ({"initial_cash": 0.5}, "initial_cash", "初期資金は1円以上で入力してください"),
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


def test_infinite_numbers_are_rejected(client: TestClient) -> None:
    # JSON の規格外だが Python の json は Infinity を読めるので、文字列で直接送る
    response = client.post(
        "/api/backtests",
        content='{"symbol_id": "DEMO:1001", "params": {"fee_rate_pct": Infinity}}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert {"field": "fee_rate_pct", "message": "数値で入力してください"} in response.json()[
        "errors"
    ]


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


# --- 監査の指摘を受けて足したテスト ----------------------------------------------------


def test_result_has_corporate_actions_and_market_settings(client: TestClient) -> None:
    split = client.post("/api/backtests", json={"symbol_id": "DEMO:1003"}).json()
    assert split["params"]["trading_days_per_year"] == 245
    assert [(a["date"], a["changes_shares"]) for a in split["corporate_actions"]] == [
        ("2025-04-01", True)
    ]
    rights = client.post("/api/backtests", json={"symbol_id": "DEMO:1007"}).json()
    assert [(a["date"], a["ex_rt"], a["changes_shares"]) for a in rights["corporate_actions"]] == [
        ("2025-06-02", 3, False)  # 株主割当増資は持ち株数を変えない
    ]
    later = client.post(
        "/api/backtests", json={"symbol_id": "DEMO:1003", "end_date": "2025-03-31"}
    ).json()
    assert later["corporate_actions"] == []  # 期間の外の権利落ちは入れない


def test_insufficient_cash_note_uses_lot_size(client: TestClient) -> None:
    body = client.post("/api/backtests", json={"symbol_id": "DEMO:1009"}).json()
    note = next(n for n in body["notes"] if n["kind"] == "insufficient_cash")
    assert "売買単位の100株を買えなかった" in note["message"]


def test_unknown_paths_and_methods_are_japanese(client: TestClient) -> None:
    missing = client.get("/api/does-not-exist")
    assert (
        missing.status_code == 404 and missing.json()["detail"] == "そのアドレスの API はありません"
    )
    method = client.delete("/api/backtests")
    assert method.status_code == 405 and "メソッド" in method.json()["detail"]


def test_too_long_inputs_are_rejected_without_echoing(client: TestClient) -> None:
    response = client.post("/api/backtests", json={"symbol_id": "DEMO:" + "1" * 5000})
    assert response.status_code == 422
    assert {"field": "symbol_id", "message": "文字数が多すぎます"} in response.json()["errors"]
    detail = client.get("/api/symbols/" + "X" * 500)
    assert detail.status_code == 422 and len(detail.json()["detail"]) < 100


@pytest.mark.parametrize("limit", [0, 101])
def test_search_limit_is_checked(client: TestClient, limit: int) -> None:
    response = client.get("/api/symbols", params={"q": "", "limit": limit})
    assert response.status_code == 422
    assert response.json()["errors"][0] == {
        "field": "limit",
        "message": "値の範囲が正しくありません",
    }


class ExplodingService(MarketDataService):
    def load(self, symbol_id):  # type: ignore[override]
        raise RuntimeError("内部の情報 /secret/path")


def test_unexpected_errors_are_japanese_json(tmp_path) -> None:
    app = create_app(Settings(data_dir=tmp_path), service=ExplodingService([DemoDataSource()]))
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/api/backtests", json={"symbol_id": "DEMO:1001"})
    assert response.status_code == 500
    body = response.json()  # JSON で返す(画面が「接続できない」と区別できるように)
    assert "想定していないエラー" in body["detail"] and body["errors"] == []
    assert "secret" not in response.text  # 中身はログにだけ出す


@pytest.mark.parametrize(
    "error",
    [
        ImportError("undefined symbol: _ZN8backtest"),  # ビルドはしたが読み込めない
        ModuleNotFoundError("No module named 'libfoo'", name="libfoo"),  # 依存するものがない
    ],
)
def test_cpp_module_that_fails_to_load_is_explained(
    client: TestClient, monkeypatch, error: ImportError
) -> None:
    class BrokenFinder:
        def find_spec(self, name, path=None, target=None):
            if name == "backtest_cpp":
                raise error
            return None

    monkeypatch.delitem(sys.modules, "backtest_cpp")
    monkeypatch.setattr(sys, "meta_path", [BrokenFinder(), *sys.meta_path])
    engines = {e["id"]: e for e in client.get("/api/meta").json()["engines"]}
    assert engines["cpp"]["available"] is False
    assert "読み込めませんでした" in engines["cpp"]["note"]


# --- J-Quants(東証)の道筋。本物の API には接続せず、httpx.MockTransport で応答を作る ---


def jquants_items(days: int = 60) -> list[dict]:
    items, day, k = [], dt.date(2024, 1, 4), 0
    while len(items) < days:
        if day.weekday() < 5:
            price = 1000.0 + 50 * math.sin(k / 6)
            items.append(
                {
                    "Date": day.isoformat(),
                    "Code": "72030",
                    "O": price,
                    "H": price,
                    "L": price,
                    "C": price,
                    "Vo": 1000.0,
                    "Va": 1.0e6,
                    "AdjFactor": 1.0,
                    "ExRT": None,
                    "UL": "0",
                    "LL": "0",
                }
            )
            k += 1
        day += dt.timedelta(days=1)
    return items


def jquants_client_app(tmp_path, handler, *, symbols: list[str] | None = None) -> TestClient:
    store = ParquetStore(tmp_path / "jquants")
    if symbols is not None:
        store.write_symbols(
            [SymbolInfo(SymbolId.parse(s), f"銘柄{s}") for s in symbols],
            dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        )
    client = JQuantsClient("key", transport=httpx.MockTransport(handler), max_wait=15)
    service = MarketDataService([DemoDataSource(), JQuantsDataSource(client, store)])
    return TestClient(create_app(Settings(data_dir=tmp_path), service=service))


def test_tse_symbol_runs_through_jquants(tmp_path) -> None:
    client = jquants_client_app(
        tmp_path, lambda request: httpx.Response(200, json={"data": jquants_items()})
    )
    meta = client.get("/api/meta").json()
    jq = next(s for s in meta["data_sources"] if s["id"] == "jquants")
    assert jq["can_fetch"] and "私的使用" in jq["license_note"]
    detail = client.get("/api/symbols/TSE:7203").json()
    assert detail["market"]["code"] == "TSE" and detail["range"]["business_days"] == 60
    body = client.post(
        "/api/backtests", json={"symbol_id": "TSE:7203", "params": {"long_window": 10}}
    ).json()
    kinds = [n["kind"] for n in body["notes"]]
    assert "survivorship" in kinds and "data_license" in kinds and "demo_data" not in kinds
    assert body["data_info"]["source_id"] == "jquants" and body["data_info"]["fetched_at"]


def test_rate_limit_from_jquants_is_503_in_japanese(tmp_path) -> None:
    client = jquants_client_app(tmp_path, lambda request: httpx.Response(429))
    response = client.post("/api/backtests", json={"symbol_id": "TSE:7203"})
    assert response.status_code == 503
    assert "リクエスト数の上限" in response.json()["detail"]


def test_delisted_symbol_is_refused_when_listing_is_known(tmp_path) -> None:
    client = jquants_client_app(
        tmp_path,
        lambda request: httpx.Response(200, json={"data": jquants_items()}),
        symbols=["TSE:6758"],
    )
    response = client.post("/api/backtests", json={"symbol_id": "TSE:7203"})
    assert response.status_code == 404 and "上場廃止" in response.json()["detail"]

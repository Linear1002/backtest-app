"""J-Quants クライアントとデータソースのテスト。本物の API には接続せず、httpx.MockTransport で応答を作る。"""

import datetime as dt
import json

import httpx
import pytest

from backend.marketdata.jquants import (
    JQuantsClient,
    JQuantsDataSource,
    RateLimiter,
    from_jquants_code,
    parse_daily_bar,
    parse_symbol,
    to_jquants_code,
)
from backend.marketdata.models import SymbolId
from backend.marketdata.source import (
    DataSourceNotConfiguredError,
    DataSourceRequestError,
    RateLimitExceededError,
)
from backend.marketdata.store import ParquetStore

SECRET = "test-secret-key-123"


class FakeClock:
    """time.monotonic と time.sleep の代わり。sleep すると時計が進む。"""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def bar_item(date: str, close: float | None = 100.0, **extra) -> dict:
    item = {
        "Date": date,
        "Code": "72030",
        "O": close,
        "H": close,
        "L": close,
        "C": close,
        "UL": "0",
        "LL": "0",
        "Vo": None if close is None else 1000.0,
        "Va": None if close is None else 100000.0,
        "AdjFactor": 1.0,
        "AdjO": close,
        "AdjH": close,
        "AdjL": close,
        "AdjC": close,
        "AdjVo": None if close is None else 1000.0,
        "MktCap": None,
        "ExRT": None,
    }
    item.update(extra)
    return item


def make_client(handler, clock: FakeClock | None = None, **kwargs) -> JQuantsClient:
    clock = clock or FakeClock()
    return JQuantsClient(
        SECRET,
        transport=httpx.MockTransport(handler),
        clock=clock,
        sleep=clock.sleep,
        **kwargs,
    )


# --- コード変換と変換関数 ---


def test_code_conversion() -> None:
    assert to_jquants_code(SymbolId.parse("TSE:7203")) == "72030"
    assert to_jquants_code(SymbolId.parse("TSE:186A")) == "186A0"
    assert from_jquants_code("72030") == SymbolId.parse("TSE:7203")
    assert from_jquants_code("186A0") == SymbolId.parse("TSE:186A")
    assert from_jquants_code("25935") is None  # 普通株以外(5文字目が0でない)は対象外
    with pytest.raises(ValueError):
        to_jquants_code(SymbolId.parse("DEMO:1001"))


def test_parse_daily_bar_handles_halted_day_and_flags() -> None:
    halted = parse_daily_bar(bar_item("2024-01-04", close=None, AdjFactor=0.5, ExRT="1"))
    assert halted.close is None and halted.open is None and halted.volume is None
    assert halted.adj_factor == 0.5 and halted.ex_rt == 1
    limit = parse_daily_bar(bar_item("2024-01-05", UL="1"))
    assert limit.upper_limit is True and limit.lower_limit is False


def test_parse_symbol_keeps_only_common_stock() -> None:
    info = parse_symbol(
        {"Code": "72030", "CoName": "テスト自動車", "MktNm": "プライム", "S33Nm": "輸送用機器"}
    )
    assert info is not None and info.name == "テスト自動車" and info.segment == "プライム"
    assert parse_symbol({"Code": "25935", "CoName": "優先株"}) is None


# --- レート制限 ---


def test_rate_limiter_waits_when_window_is_full() -> None:
    clock = FakeClock()
    limiter = RateLimiter(5, clock=clock, sleep=clock.sleep)
    for _ in range(5):
        limiter.acquire()
    assert clock.sleeps == []
    limiter.acquire()  # 6回目は、最初のリクエストから60秒たつまで待つ
    assert len(clock.sleeps) == 1 and 60.0 <= clock.sleeps[0] <= 61.0


# --- クライアント ---


def test_client_sends_api_key_header_and_follows_pagination() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        assert request.headers["x-api-key"] == SECRET
        if "pagination_key" not in request.url.params:
            return httpx.Response(
                200, json={"data": [bar_item("2024-01-04")], "pagination_key": "k1"}
            )
        return httpx.Response(200, json={"data": [bar_item("2024-01-05")]})

    client = make_client(handler)
    items = client.daily_bars(code="72030")
    assert [item["Date"] for item in items] == ["2024-01-04", "2024-01-05"]
    assert seen == [{"code": "72030"}, {"code": "72030", "pagination_key": "k1"}]


def test_client_waits_after_429_and_retries() -> None:
    clock = FakeClock()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"message": "Too Many Requests"})
        return httpx.Response(200, json={"data": []})

    make_client(handler, clock).daily_bars(code="72030")
    assert calls["n"] == 2
    assert any(s >= 60 for s in clock.sleeps)  # 1分以上待ってから再送している


def test_client_gives_up_after_repeated_429() -> None:
    client = make_client(lambda request: httpx.Response(429), max_attempts=2)
    with pytest.raises(RateLimitExceededError):
        client.daily_bars(code="72030")


def test_client_reports_400_message_without_leaking_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": f"out of range (key={SECRET})"})

    with pytest.raises(DataSourceRequestError) as error:
        make_client(handler).daily_bars(code="72030", start=dt.date(2000, 1, 1))
    assert "out of range" in str(error.value)
    assert SECRET not in str(error.value)


def test_client_maps_auth_errors() -> None:
    with pytest.raises(DataSourceNotConfiguredError):
        make_client(lambda request: httpx.Response(401)).master()


def test_client_never_shows_key_in_repr() -> None:
    client = make_client(lambda request: httpx.Response(200, json={"data": []}))
    assert SECRET not in repr(client)
    with pytest.raises(DataSourceNotConfiguredError):
        JQuantsClient("")


def test_parse_float_str_keeps_original_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = '{"data": [{"Date": "2024-01-04", "AdjFactor": 0.333333}]}'
        return httpx.Response(200, text=body)

    items = make_client(handler).daily_bars(date=dt.date(2024, 1, 4), parse_float=str)
    assert items[0]["AdjFactor"] == "0.333333"


# --- 保存とデータソース ---


def test_store_roundtrip_keeps_nulls_and_fetched_at(tmp_path) -> None:
    store = ParquetStore(tmp_path)
    symbol_id = SymbolId.parse("TSE:7203")
    bars = [
        parse_daily_bar(bar_item("2024-01-05")),
        parse_daily_bar(bar_item("2024-01-04", close=None, AdjFactor=0.5, ExRT="1")),
    ]
    fetched_at = dt.datetime(2026, 10, 23, 9, 0, tzinfo=dt.UTC)
    store.write_bars(symbol_id, bars, fetched_at)
    loaded = store.read_bars(symbol_id)
    assert loaded == sorted(bars, key=lambda b: b.date)
    assert store.bars_fetched_at(symbol_id) == fetched_at
    assert store.cached_symbol_ids() == [symbol_id]


class CountingHandler:
    def __init__(self, items: list[dict]) -> None:
        self.items = items
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(200, json={"data": self.items})


def test_source_caches_and_refreshes_when_stale(tmp_path) -> None:
    handler = CountingHandler([bar_item("2024-01-04"), bar_item("2024-01-05")])
    now = {"value": dt.datetime(2026, 10, 23, tzinfo=dt.UTC)}
    source = JQuantsDataSource(
        make_client(handler),
        ParquetStore(tmp_path),
        max_age=dt.timedelta(days=7),
        now=lambda: now["value"],
    )
    symbol_id = SymbolId.parse("TSE:7203")

    assert len(source.get_daily_bars(symbol_id)) == 2
    assert source.get_available_range(symbol_id).last == dt.date(2024, 1, 5)
    assert handler.calls == 1  # 2回目は保存済みのデータを使う

    now["value"] += dt.timedelta(days=8)  # 保存から8日たつと取り直す
    source.get_daily_bars(symbol_id)
    assert handler.calls == 2
    assert source.get_data_info(symbol_id).fetched_at == now["value"]


def test_source_reads_cache_without_api_key(tmp_path) -> None:
    store = ParquetStore(tmp_path)
    symbol_id = SymbolId.parse("TSE:7203")
    store.write_bars(
        symbol_id,
        [parse_daily_bar(bar_item("2024-01-04"))],
        dt.datetime(2020, 1, 1, tzinfo=dt.UTC),
    )
    offline = JQuantsDataSource(None, store)
    assert len(offline.get_daily_bars(symbol_id)) == 1  # 古くても、キーがなければ保存済みを使う
    with pytest.raises(DataSourceNotConfiguredError):
        offline.get_daily_bars(SymbolId.parse("TSE:6758"))


def test_refresh_symbols_saves_common_stock_only(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps(
                {
                    "data": [
                        {"Code": "72030", "CoName": "テスト自動車"},
                        {"Code": "25935", "CoName": "優先株"},
                    ]
                }
            ),
        )

    source = JQuantsDataSource(make_client(handler), ParquetStore(tmp_path))
    assert [str(s.symbol_id) for s in source.refresh_symbols()] == ["TSE:7203"]
    assert [s.name for s in source.list_symbols()] == ["テスト自動車"]

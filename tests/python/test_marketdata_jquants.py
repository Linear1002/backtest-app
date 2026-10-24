"""J-Quants クライアントとデータソースのテスト。本物の API には接続せず、httpx.MockTransport で応答を作る。"""

import datetime as dt
import json

import httpx
import pytest

from backend.marketdata.jquants import (
    WAIT_AFTER_429_SECONDS,
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
    SymbolNotFoundError,
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
    # 公式の推奨(1分以上、確実を期すなら2分程度)どおり、2分待ってから再送している
    assert WAIT_AFTER_429_SECONDS >= 120
    assert any(s >= WAIT_AFTER_429_SECONDS for s in clock.sleeps)


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


# --- 監査の指摘を受けて足したテスト:レート制限をスレッドの間で共有する ---


def test_rate_limiter_is_safe_across_threads() -> None:
    """10本のスレッドが同時に送っても、1秒の窓に5回を超えない。"""
    import threading
    import time

    limiter = RateLimiter(5, period=1.0)
    sent: list[float] = []
    guard = threading.Lock()
    barrier = threading.Barrier(10)

    def worker() -> None:
        barrier.wait()
        limiter.acquire()
        with guard:
            sent.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert len(sent) == 10
    sent.sort()
    for i in range(len(sent) - 5):
        assert sent[i + 5] - sent[i] >= 0.95  # 6回目は、1回目から窓の長さ以上あとになる


def test_rate_limiter_block_for_makes_everyone_wait() -> None:
    clock = FakeClock()
    limiter = RateLimiter(5, clock=clock, sleep=clock.sleep)
    limiter.block_for(WAIT_AFTER_429_SECONDS)
    limiter.acquire()
    assert clock.sleeps and clock.sleeps[0] >= WAIT_AFTER_429_SECONDS


def test_rate_limiter_refuses_to_wait_longer_than_max_wait() -> None:
    clock = FakeClock()
    limiter = RateLimiter(2, clock=clock, sleep=clock.sleep)
    limiter.acquire(max_wait=15)
    limiter.acquire(max_wait=15)
    with pytest.raises(RateLimitExceededError) as error:
        limiter.acquire(max_wait=15)  # 3回目は約60秒待つ必要があるので、待たずに目安を伝える
    assert "約61秒後" in str(error.value)
    assert clock.sleeps == []


def test_interactive_client_does_not_sleep_after_429() -> None:
    clock = FakeClock()
    client = make_client(lambda request: httpx.Response(429), clock, max_wait=15)
    with pytest.raises(RateLimitExceededError) as error:
        client.daily_bars(code="72030")
    assert "約2分待ってから" in str(error.value)
    assert clock.sleeps == []  # 画面からのリクエストでは2分も待たない


def test_client_retries_server_errors_then_succeeds() -> None:
    clock = FakeClock()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": [bar_item("2024-01-04")]})

    items = make_client(handler, clock).daily_bars(code="72030")
    assert len(items) == 1 and calls["n"] == 3
    assert clock.sleeps == [2.0, 4.0]


def test_client_reports_repeated_server_errors() -> None:
    with pytest.raises(DataSourceRequestError) as error:
        make_client(lambda request: httpx.Response(503)).daily_bars(code="72030")
    assert "HTTP 503" in str(error.value)


def test_client_retries_connection_errors_then_explains() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(DataSourceRequestError) as error:
        make_client(handler).daily_bars(code="72030")
    assert "接続できませんでした" in str(error.value)


def test_client_maps_forbidden_to_key_problem() -> None:
    with pytest.raises(DataSourceNotConfiguredError):
        make_client(lambda request: httpx.Response(403)).daily_bars(code="72030")


@pytest.mark.parametrize(
    "body",
    ["<html>maintenance</html>", "[1, 2, 3]", '{"data": "not a list"}'],
)
def test_client_explains_unexpected_bodies(body: str) -> None:
    with pytest.raises(DataSourceRequestError):
        make_client(lambda request: httpx.Response(200, text=body)).daily_bars(code="72030")


def test_client_stops_when_pagination_key_repeats() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [], "pagination_key": "same"})

    with pytest.raises(DataSourceRequestError) as error:
        make_client(handler).daily_bars(code="72030")
    assert "ページング" in str(error.value)


def test_daily_bars_needs_code_or_date() -> None:
    client = make_client(lambda request: httpx.Response(200, json={"data": []}))
    with pytest.raises(ValueError):
        client.daily_bars(start=dt.date(2024, 1, 1))


def test_parse_daily_bar_reads_ex_rt_forms() -> None:
    assert parse_daily_bar(bar_item("2024-01-04", ExRT="1")).ex_rt == 1
    assert parse_daily_bar(bar_item("2024-01-04", ExRT=2)).ex_rt == 2
    assert parse_daily_bar(bar_item("2024-01-04", ExRT="3.0")).ex_rt == 3
    with pytest.raises(DataSourceRequestError):
        parse_daily_bar(bar_item("2024-01-04", ExRT="abc"))
    with pytest.raises(DataSourceRequestError):
        parse_daily_bar(bar_item("2024-01-04", C="not-a-number"))
    with pytest.raises(DataSourceRequestError):
        parse_daily_bar(bar_item("2024/01/04"))


# --- 取り直しの合わせ方・失敗したとき・同時に来たとき ---


def make_source(tmp_path, handler, now, **kwargs) -> JQuantsDataSource:
    return JQuantsDataSource(
        make_client(handler),
        ParquetStore(tmp_path),
        max_age=dt.timedelta(days=7),
        now=lambda: now["value"],
        **kwargs,
    )


def test_refresh_keeps_old_dates_and_takes_corrections(tmp_path) -> None:
    """Free プランは取れる期間が後ろへずれる。取り直しても古い日付は消さず、重なる日付は新しい値にする。"""
    responses = [
        [bar_item("2024-01-04", 100.0), bar_item("2024-01-05", 101.0)],
        [
            bar_item("2024-01-05", 111.0),
            bar_item("2024-01-08", 102.0),
        ],  # 01-04 は窓の外、01-05 は訂正
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": responses.pop(0)})

    now = {"value": dt.datetime(2026, 10, 23, tzinfo=dt.UTC)}
    source = make_source(tmp_path, handler, now)
    symbol_id = SymbolId.parse("TSE:7203")
    source.get_daily_bars(symbol_id)
    now["value"] += dt.timedelta(days=8)
    bars = source.get_daily_bars(symbol_id)
    assert [(b.date.isoformat(), b.close) for b in bars] == [
        ("2024-01-04", 100.0),
        ("2024-01-05", 111.0),
        ("2024-01-08", 102.0),
    ]


def test_stale_cache_is_used_when_refresh_fails(tmp_path) -> None:
    state = {"fail": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["fail"]:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": [bar_item("2024-01-04")]})

    now = {"value": dt.datetime(2026, 10, 23, 15, 30, tzinfo=dt.UTC)}
    source = make_source(tmp_path, handler, now)
    symbol_id = SymbolId.parse("TSE:7203")
    source.get_daily_bars(symbol_id)
    assert source.get_data_info(symbol_id).warning is None

    state["fail"] = True
    now["value"] += dt.timedelta(days=8)
    assert len(source.get_daily_bars(symbol_id)) == 1  # 取り直せなくても、保存済みのデータで続ける
    warning = source.get_data_info(symbol_id).warning
    assert warning is not None and "2026-10-24 00:30 に取得したデータ" in warning  # 日本時間で表示

    state["fail"] = False
    source.get_daily_bars(symbol_id)
    assert source.get_data_info(symbol_id).warning is None  # 取り直せたら注意は消える


def test_refresh_failure_without_cache_is_an_error(tmp_path) -> None:
    now = {"value": dt.datetime(2026, 10, 23, tzinfo=dt.UTC)}
    source = make_source(tmp_path, lambda request: httpx.Response(503), now)
    with pytest.raises(DataSourceRequestError):
        source.get_daily_bars(SymbolId.parse("TSE:7203"))


def test_same_symbol_is_fetched_once_when_requests_arrive_together(tmp_path) -> None:
    import threading
    import time

    calls = {"n": 0}
    guard = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        with guard:
            calls["n"] += 1
        time.sleep(0.2)  # 取得に時間がかかっているあいだに、ほかのスレッドが来る
        return httpx.Response(200, json={"data": [bar_item("2024-01-04")]})

    source = JQuantsDataSource(
        JQuantsClient(SECRET, transport=httpx.MockTransport(handler)), ParquetStore(tmp_path)
    )
    symbol_id = SymbolId.parse("TSE:7203")
    barrier = threading.Barrier(4)
    results: list[int] = []

    def worker() -> None:
        barrier.wait()
        results.append(len(source.get_daily_bars(symbol_id)))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert results == [1, 1, 1, 1]
    assert calls["n"] == 1


def test_check_listed_uses_the_symbol_list(tmp_path) -> None:
    store = ParquetStore(tmp_path)
    source = JQuantsDataSource(None, store)
    source.check_listed(
        SymbolId.parse("TSE:9999")
    )  # 一覧を取っていないときは確かめようがないので通す
    store.write_symbols(
        [parse_symbol({"Code": "72030", "CoName": "テスト自動車"})],  # type: ignore[list-item]
        dt.datetime(2026, 10, 23, tzinfo=dt.UTC),
    )
    source.check_listed(SymbolId.parse("TSE:7203"))
    with pytest.raises(SymbolNotFoundError) as error:
        source.check_listed(SymbolId.parse("TSE:9999"))
    assert "上場廃止" in str(error.value)


def test_read_cached_bars_never_fetches(tmp_path) -> None:
    handler = CountingHandler([bar_item("2024-01-04")])
    now = {"value": dt.datetime(2026, 10, 23, tzinfo=dt.UTC)}
    source = make_source(tmp_path, handler, now)
    symbol_id = SymbolId.parse("TSE:7203")
    assert source.read_cached_bars(symbol_id) is None
    source.get_daily_bars(symbol_id)
    now["value"] += dt.timedelta(days=30)
    assert source.read_cached_bars(symbol_id) is not None
    assert handler.calls == 1


def test_store_ignores_files_written_in_another_format(tmp_path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    store = ParquetStore(tmp_path)
    symbol_id = SymbolId.parse("TSE:7203")
    store.write_bars(
        symbol_id, [parse_daily_bar(bar_item("2024-01-04"))], dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    )
    assert store.read_bars(symbol_id) is not None
    old = pa.table({"date": [dt.date(2024, 1, 4)], "close": [1.0]}).replace_schema_metadata(
        {b"schema_version": b"0"}
    )
    pq.write_table(old, store.bars_path(symbol_id))
    assert store.read_bars(symbol_id) is None  # 古い形式は「保存されていない」として取り直す

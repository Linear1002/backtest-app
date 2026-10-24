import datetime as dt

import pytest

from backend.marketdata.models import SymbolId
from backend.marketdata.source import SymbolNotFoundError
from backend.marketdata.synthetic import (
    DEMO_SYMBOLS,
    DemoDataSource,
    business_days,
    generate_bars,
)

source = DemoDataSource()


def test_business_days_skip_weekends_and_new_year() -> None:
    days = business_days()
    assert all(day.weekday() < 5 for day in days)
    assert all(not (day.month == 1 and day.day <= 3) for day in days)
    assert all(not (day.month == 12 and day.day == 31) for day in days)
    assert list(days) == sorted(set(days))


def test_generation_is_deterministic() -> None:
    generate_bars.cache_clear()
    first = generate_bars("1001")
    generate_bars.cache_clear()
    assert generate_bars("1001") == first


@pytest.mark.parametrize("symbol", DEMO_SYMBOLS, ids=lambda s: s.code)
def test_bars_are_consistent(symbol) -> None:
    bars = generate_bars(symbol.code)
    assert bars[0].date >= symbol.listed_from
    for bar in bars:
        if bar.close is None:
            # 売買不成立の日は、四本値と出来高がすべて None(J-Quants と同じ)
            assert (bar.open, bar.high, bar.low, bar.volume, bar.turnover) == (None,) * 5
        else:
            assert bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
            assert bar.volume and bar.volume > 0
        assert bar.adj_factor is not None and bar.adj_factor > 0
        if bar.adj_factor != 1.0:
            assert bar.ex_rt in (1, 2, 3)
    assert "(架空)" in symbol.name


def test_corporate_actions_are_present() -> None:
    def actions(code: str) -> list[tuple[str, int | None, float | None]]:
        return [
            (bar.date.isoformat(), bar.ex_rt, bar.adj_factor)
            for bar in generate_bars(code)
            if bar.ex_rt is not None
        ]

    assert actions("1003") == [("2025-04-01", 1, 0.5)]
    assert actions("1006") == [("2025-01-06", 2, 10.0)]
    assert actions("1007") == [("2025-06-02", 3, 0.97)]
    # 売買停止の日に重なった権利落ちも、レコードには調整係数が入る
    halted_split = [b for b in generate_bars("1008") if b.date == dt.date(2025, 3, 12)][0]
    assert halted_split.close is None and halted_split.adj_factor == 0.5


def test_split_halves_unadjusted_price() -> None:
    bars = {bar.date: bar for bar in generate_bars("1003")}
    before = bars[dt.date(2025, 3, 31)].close
    after = bars[dt.date(2025, 4, 1)].close
    assert 0.35 < after / before < 0.65


def test_expensive_symbol_cannot_be_bought_with_default_cash() -> None:
    closes = [bar.close for bar in generate_bars("1009") if bar.close is not None]
    assert min(closes) * 100 > 1_000_000


def test_late_listing_symbol_starts_later() -> None:
    symbol_id = SymbolId.parse("DEMO:1012")
    assert source.get_available_range(symbol_id).first == dt.date(2025, 4, 1)


def test_source_filters_by_date_and_rejects_unknown_symbols() -> None:
    symbol_id = SymbolId.parse("DEMO:1001")
    bars = source.get_daily_bars(symbol_id, dt.date(2025, 1, 6), dt.date(2025, 1, 10))
    assert [bar.date.isoformat() for bar in bars] == [
        "2025-01-06",
        "2025-01-07",
        "2025-01-08",
        "2025-01-09",
        "2025-01-10",
    ]
    with pytest.raises(SymbolNotFoundError):
        source.get_daily_bars(SymbolId.parse("DEMO:9999"))
    info = source.get_data_info(symbol_id)
    assert info.source_id == "demo" and info.fetched_at is None

import datetime as dt

import pytest

from backend.marketdata.models import DateRange, InvalidSymbolIdError, SymbolId


@pytest.mark.parametrize(
    ("text", "market", "code"),
    [
        ("TSE:7203", "TSE", "7203"),
        ("tse:7203", "TSE", "7203"),
        ("  TSE:186A ", "TSE", "186A"),
        ("DEMO:1003", "DEMO", "1003"),
    ],
)
def test_parse_valid_symbol_id(text: str, market: str, code: str) -> None:
    symbol_id = SymbolId.parse(text)
    assert (symbol_id.market, symbol_id.code) == (market, code)
    assert str(symbol_id) == f"{market}:{code}"


@pytest.mark.parametrize(
    "text",
    ["7203", "TSE7203", "TSE:72", "TSE:72030", "NYSE:IBM", "DEMO:10A3", ""],
)
def test_parse_invalid_symbol_id_raises_japanese_message(text: str) -> None:
    with pytest.raises(InvalidSymbolIdError) as error:
        SymbolId.parse(text)
    assert any("぀" <= ch <= "ヿ" or "一" <= ch <= "鿿" for ch in str(error.value))


def test_filename_stem_has_no_colon() -> None:
    assert SymbolId.parse("TSE:7203").filename_stem() == "TSE_7203"


def test_market_config_lot_size() -> None:
    assert SymbolId.parse("TSE:7203").market_config.lot_size == 100
    assert SymbolId.parse("DEMO:1001").market_config.currency == "JPY"


def test_date_range_rejects_reversed_dates() -> None:
    with pytest.raises(ValueError):
        DateRange(dt.date(2025, 1, 2), dt.date(2025, 1, 1))
    assert DateRange(dt.date(2025, 1, 1), dt.date(2025, 1, 1)).contains(dt.date(2025, 1, 1))

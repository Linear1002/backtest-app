import datetime as dt

import pytest

from backend.marketdata.models import SymbolId
from backend.marketdata.service import (
    MarketDataService,
    build_service,
    normalize_for_search,
)
from backend.marketdata.source import SymbolNotFoundError
from backend.marketdata.synthetic import DemoDataSource
from backend.settings import Settings


@pytest.fixture
def service() -> MarketDataService:
    return MarketDataService([DemoDataSource()])


def test_normalize_for_search() -> None:
    assert normalize_for_search("１００３") == "1003"  # 全角数字
    assert normalize_for_search("ほしぞら") == normalize_for_search("ホシゾラ")  # ひらがな=カタカナ
    assert normalize_for_search(" DEMO:1001 ") == "demo:1001"


def test_search_by_code_name_and_kana(service: MarketDataService) -> None:
    assert [str(s.symbol_id) for s in service.search("1003")] == ["DEMO:1003"]
    assert [str(s.symbol_id) for s in service.search("１００３")] == ["DEMO:1003"]
    assert [str(s.symbol_id) for s in service.search("ホシゾラ")] == ["DEMO:1001"]
    assert [str(s.symbol_id) for s in service.search("demo:1012")] == ["DEMO:1012"]
    assert len(service.search("架空", limit=5)) == 5
    assert service.search("存在しない銘柄") == []


def test_exact_code_match_comes_first(service: MarketDataService) -> None:
    results = service.search("100")
    assert [str(s.symbol_id) for s in results][:3] == ["DEMO:1001", "DEMO:1002", "DEMO:1003"]


def test_routing_by_market(service: MarketDataService) -> None:
    symbol_id = SymbolId.parse("DEMO:1001")
    assert service.get_available_range(symbol_id).first == dt.date(2022, 1, 4)
    with pytest.raises(SymbolNotFoundError) as error:
        service.get_daily_bars(SymbolId.parse("TSE:7203"))
    assert "JQUANTS_API_KEY" in str(error.value)


def test_build_service_without_key_has_demo_only(tmp_path) -> None:
    service = build_service(Settings(data_dir=tmp_path))
    assert [source.source_id for source in service.sources] == ["demo"]


def test_load_reads_bars_once_and_matches_range(service: MarketDataService) -> None:
    data = service.load(SymbolId.parse("DEMO:1012"))
    assert data.available.first == data.bars[0].date == dt.date(2025, 4, 1)
    assert data.available.last == data.bars[-1].date
    assert data.info.source_id == "demo" and data.info.warning is None


def test_describe_and_listing_for_demo(service: MarketDataService) -> None:
    symbol_id = SymbolId.parse("DEMO:1003")
    assert "分割" in (service.describe(symbol_id) or "")
    service.require_listed(symbol_id)  # 架空銘柄はすべて上場中として扱う
    with pytest.raises(SymbolNotFoundError):
        service.require_listed(SymbolId.parse("DEMO:9999"))


def test_sources_describe_themselves(service: MarketDataService) -> None:
    (demo,) = service.sources
    assert demo.source_label == "架空データ(デモ用)"
    assert "架空" in demo.license_note and demo.can_fetch

"""複数のデータソースをまとめて扱う窓口。

銘柄IDの市場(DEMO / TSE など)を見て、担当のデータソースに振り分ける。
API 層はこのクラスだけを使い、J-Quants や架空データを直接は知らない。
"""

from __future__ import annotations

import datetime as dt
import unicodedata
from collections.abc import Sequence

from backend.marketdata.jquants import JQuantsClient, JQuantsDataSource
from backend.marketdata.models import DailyBar, DataInfo, DateRange, SymbolId, SymbolInfo
from backend.marketdata.source import DataSource, SymbolNotFoundError
from backend.marketdata.store import ParquetStore
from backend.marketdata.synthetic import DemoDataSource
from backend.settings import Settings


def normalize_for_search(text: str) -> str:
    """検索用に文字をそろえる:全角英数→半角、大文字小文字の区別なし、ひらがな→カタカナ。"""
    normalized = unicodedata.normalize("NFKC", text).casefold().strip()
    return "".join(chr(ord(ch) + 0x60) if "ぁ" <= ch <= "ゖ" else ch for ch in normalized)


class MarketDataService:
    def __init__(self, sources: Sequence[DataSource]) -> None:
        self._sources = list(sources)
        self._by_market: dict[str, DataSource] = {}
        for source in self._sources:
            for market in source.markets:
                self._by_market[market] = source

    @property
    def sources(self) -> list[DataSource]:
        return list(self._sources)

    def source_for(self, symbol_id: SymbolId) -> DataSource:
        source = self._by_market.get(symbol_id.market)
        if source is None:
            if symbol_id.market == "TSE":
                raise SymbolNotFoundError(
                    "東証の銘柄を使うには J-Quants の設定が必要です。.env に JQUANTS_API_KEY を書いてください"
                )
            raise SymbolNotFoundError(f"この市場のデータソースがありません: {symbol_id.market}")
        return source

    def list_symbols(self) -> list[SymbolInfo]:
        symbols: list[SymbolInfo] = []
        for source in self._sources:
            symbols.extend(source.list_symbols())
        return symbols

    def search(self, query: str, *, limit: int = 20) -> list[SymbolInfo]:
        """コードまたは銘柄名で検索する。完全一致 → 前方一致 → 部分一致の順に並べる。"""
        q = normalize_for_search(query)
        symbols = self.list_symbols()
        if not q:
            return symbols[:limit]
        ranked: list[tuple[int, SymbolInfo]] = []
        for info in symbols:
            sid = normalize_for_search(str(info.symbol_id))
            code = normalize_for_search(info.symbol_id.code)
            name = normalize_for_search(info.name)
            name_en = normalize_for_search(info.name_en or "")
            if q in (code, sid):
                rank = 0
            elif code.startswith(q) or sid.startswith(q) or name.startswith(q):
                rank = 1
            elif q in name or (name_en and q in name_en):
                rank = 2
            else:
                continue
            ranked.append((rank, info))
        ranked.sort(key=lambda item: (item[0], item[1].symbol_id))
        return [info for _, info in ranked[:limit]]

    def find_symbol(self, symbol_id: SymbolId) -> SymbolInfo:
        source = self.source_for(symbol_id)
        for info in source.list_symbols():
            if info.symbol_id == symbol_id:
                return info
        # 銘柄一覧に無くても、日足が取れれば使えるようにする(J-Quants で一覧を未取得のとき)
        return SymbolInfo(symbol_id=symbol_id, name=symbol_id.code)

    def get_daily_bars(
        self, symbol_id: SymbolId, start: dt.date | None = None, end: dt.date | None = None
    ) -> list[DailyBar]:
        return self.source_for(symbol_id).get_daily_bars(symbol_id, start, end)

    def get_available_range(self, symbol_id: SymbolId) -> DateRange:
        return self.source_for(symbol_id).get_available_range(symbol_id)

    def get_data_info(self, symbol_id: SymbolId) -> DataInfo:
        return self.source_for(symbol_id).get_data_info(symbol_id)


def build_jquants_source(settings: Settings) -> JQuantsDataSource | None:
    """APIキーがあれば取得もできる J-Quants データソースを、なくても保存済みデータがあれば読み取り専用で作る。"""
    store = ParquetStore(settings.data_dir / "jquants")
    client = (
        JQuantsClient(
            settings.jquants_api_key,
            requests_per_minute=settings.jquants_requests_per_minute,
        )
        if settings.jquants_api_key
        else None
    )
    if client is None and not store.cached_symbol_ids() and store.read_symbols() is None:
        return None
    return JQuantsDataSource(
        client, store, max_age=dt.timedelta(days=settings.jquants_max_age_days)
    )


def build_service(settings: Settings) -> MarketDataService:
    sources: list[DataSource] = [DemoDataSource()]
    jquants = build_jquants_source(settings)
    if jquants is not None:
        sources.append(jquants)
    return MarketDataService(sources)

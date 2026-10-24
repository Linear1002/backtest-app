"""データソースのインターフェース(docs/mvp.md 3.3)。

バックテストの計算部分は J-Quants を直接知らない。データの取得はすべてこのインターフェースの裏に隠し、
将来、商用データソースに切り替えるときは、このインターフェースを満たすクラスを1つ追加するだけで済むようにする。
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol, runtime_checkable

from backend.marketdata.models import DailyBar, DataInfo, DateRange, SymbolId, SymbolInfo


class MarketDataError(Exception):
    """データ層のエラーの親クラス。メッセージは画面にそのまま出せる日本語にする。

    APIキーなどの秘密情報は、メッセージに絶対に含めない。
    """


class SymbolNotFoundError(MarketDataError):
    """指定された銘柄が見つからない。"""


class DataSourceNotConfiguredError(MarketDataError):
    """データソースの設定(APIキーなど)が足りない。"""


class DataSourceRequestError(MarketDataError):
    """外部APIへの問い合わせに失敗した。"""


class RateLimitExceededError(DataSourceRequestError):
    """リクエスト数の上限を超え、待っても回復しなかった。"""


@runtime_checkable
class DataSource(Protocol):
    """データソースが持つべき機能。責務は3つ:銘柄一覧・日足・データの範囲。"""

    @property
    def source_id(self) -> str:
        """データソースを表す短い名前(例: "jquants")。"""
        ...

    @property
    def markets(self) -> tuple[str, ...]:
        """このデータソースが扱う市場(銘柄IDの前半。例: ("TSE",))。"""
        ...

    @property
    def source_label(self) -> str:
        """画面に出す名前(例: "J-Quants API(東証)")。"""
        ...

    @property
    def license_note(self) -> str:
        """データの利用条件の注意書き(結果画面に出す)。"""
        ...

    @property
    def can_fetch(self) -> bool:
        """新しいデータを取得できるか(J-Quants は APIキーが必要)。"""
        ...

    def describe(self, symbol_id: SymbolId) -> str | None:
        """銘柄の補足説明(架空銘柄で確かめられる境界ケースなど)。なければ None。"""
        ...

    def check_listed(self, symbol_id: SymbolId) -> None:
        """MVP の対象(現在上場している銘柄)か確かめる。対象外なら SymbolNotFoundError(docs/mvp.md 3.6)。"""
        ...

    def list_symbols(self) -> list[SymbolInfo]:
        """銘柄一覧を返す。"""
        ...

    def get_daily_bars(
        self,
        symbol_id: SymbolId,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> list[DailyBar]:
        """日足を日付の古い順に返す。売買不成立の日もレコードを返し、価格は None にする。

        start / end を省略したときは、取得できる範囲の端までを返す。
        """
        ...

    def get_available_range(self, symbol_id: SymbolId) -> DateRange:
        """その銘柄で取得できるデータの範囲(最初の日と最後の日)。"""
        ...

    def get_data_info(self, symbol_id: SymbolId) -> DataInfo:
        """データの出どころと取得日時。"""
        ...


def filter_bars(bars: list[DailyBar], start: dt.date | None, end: dt.date | None) -> list[DailyBar]:
    """日付で絞り込む(両端を含む)。"""
    return [
        bar
        for bar in bars
        if (start is None or bar.date >= start) and (end is None or bar.date <= end)
    ]

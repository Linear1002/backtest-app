"""株価データ層で使う型と、市場ごとの設定。

ここにある型は「データの共通形式」(docs/mvp.md 3.3)。データソース(J-Quants・架空データ)は
自分の形式からこの共通形式に変換して返し、API 層がさらに計算エンジンの入力形式に変換する。
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

# --- 市場ごとの設定(docs/mvp.md 3.4) ------------------------------------------------


@dataclass(frozen=True)
class MarketConfig:
    """市場ごとに違う値をまとめたもの。新しい市場を足すときはここに1件追加する。"""

    code: str  # 銘柄IDの前半(例: "TSE")
    name: str  # 表示名
    currency: str  # 通貨コード(ISO 4217)
    lot_size: int  # 売買単位(株)
    code_pattern: str  # 銘柄コード部分の正規表現
    has_price_limits: bool  # 値幅制限がある市場か(MVPの計算では扱わない。7章)


MARKETS: dict[str, MarketConfig] = {
    "TSE": MarketConfig(
        code="TSE",
        name="東京証券取引所",
        currency="JPY",
        lot_size=100,
        # 4文字。数字だけのコード(7203)と、英字を含むコード(186A)がある
        code_pattern=r"[0-9][0-9A-Z]{3}",
        has_price_limits=True,
    ),
    "DEMO": MarketConfig(
        code="DEMO",
        name="架空市場(デモ用)",
        currency="JPY",
        lot_size=100,
        code_pattern=r"[0-9]{4}",
        has_price_limits=False,
    ),
}


# --- 銘柄ID ----------------------------------------------------------------------

_SYMBOL_ID_RE = re.compile(r"^(?P<market>[A-Z]+):(?P<code>[0-9A-Z]+)$")


class InvalidSymbolIdError(ValueError):
    """銘柄IDの形式が正しくないときのエラー。メッセージは画面にそのまま出せる日本語。"""


@dataclass(frozen=True, order=True)
class SymbolId:
    """「市場+コード」で銘柄を一意に表す(例: TSE:7203)。"""

    market: str
    code: str

    @classmethod
    def parse(cls, text: str) -> SymbolId:
        """'TSE:7203' のような文字列を SymbolId にする。小文字・前後の空白は受け付ける。"""
        normalized = text.strip().upper()
        match = _SYMBOL_ID_RE.match(normalized)
        if match is None:
            raise InvalidSymbolIdError(f"銘柄IDの形式が正しくありません: {text!r}(例: TSE:7203)")
        market, code = match.group("market"), match.group("code")
        config = MARKETS.get(market)
        if config is None:
            raise InvalidSymbolIdError(f"対応していない市場です: {market}")
        if re.fullmatch(config.code_pattern, code) is None:
            raise InvalidSymbolIdError(f"{config.name}の銘柄コードとして正しくありません: {code}")
        return cls(market=market, code=code)

    @property
    def market_config(self) -> MarketConfig:
        return MARKETS[self.market]

    def __str__(self) -> str:
        return f"{self.market}:{self.code}"

    def filename_stem(self) -> str:
        """ファイル名に使える形(Windows でも使えるように ':' を '_' にする)。"""
        return f"{self.market}_{self.code}"


# --- 銘柄情報と日足 ------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolInfo:
    """銘柄一覧の1行。"""

    symbol_id: SymbolId
    name: str
    name_en: str | None = None
    segment: str | None = None  # 市場区分(プライムなど)
    sector: str | None = None  # 業種


@dataclass(frozen=True)
class DailyBar:
    """日足1本(1営業日分)。価格はすべて未調整(その日に実際に付いた値)。

    売買不成立の日もレコードはあり、そのときは四本値・出来高・売買代金がすべて None になる。
    """

    date: dt.date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    turnover: float | None  # 売買代金(円)
    adj_factor: float | None  # 調整係数。権利落ち日以外は 1.0
    ex_rt: int | None  # 権利落ちの種類(1:分割 2:併合 3:株主割当増資)。該当なしは None
    upper_limit: bool | None = None  # 高値がストップ高に達したか(参考情報。計算では使わない)
    lower_limit: bool | None = None  # 安値がストップ安に達したか(参考情報。計算では使わない)

    @property
    def is_trading_day(self) -> bool:
        """売買が成立した日か(docs/mvp.md の「有効日」)。"""
        return self.close is not None


@dataclass(frozen=True)
class DateRange:
    """データの範囲(両端を含む)。"""

    first: dt.date
    last: dt.date

    def __post_init__(self) -> None:
        if self.first > self.last:
            raise ValueError("DateRange の first は last 以前である必要があります")

    def contains(self, day: dt.date) -> bool:
        return self.first <= day <= self.last


@dataclass(frozen=True)
class DataInfo:
    """結果画面に出す「どこから・いつ取ったデータか」。"""

    source_id: str  # "demo" / "jquants"
    source_label: str  # 画面に出す名前
    license_note: str  # 利用条件の注意書き
    fetched_at: dt.datetime | None  # データを取得した日時(UTC。架空データは None)
    warning: str | None = (
        None  # 最新のデータを取得できず、保存済みの古いデータを使っているときの説明
    )

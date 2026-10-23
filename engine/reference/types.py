"""リファレンス実装の入力と出力の型。

入力(Bar・MaCrossParams)は、C++ 版の入力ファイルと同じ項目にしてある(docs/cpp/contract.md)。
金額・価格は float(float64)、株数は int(C++ では int64_t)。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

Side = Literal["buy", "sell"]

# 年間の営業日数(東証。docs/mvp.md 5章)
TRADING_DAYS_PER_YEAR = 245


class EngineInputError(ValueError):
    """パラメータや期間の指定が正しくない。メッセージは画面に出せる日本語。"""


class EngineDataError(ValueError):
    """データに異常がある(調整係数が Null、想定外の権利落ちの種類、日付の順番が崩れている など)。"""


# --- 入力 ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Bar:
    """日足1本。価格は未調整。売買不成立の日は四本値が None。"""

    date: dt.date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    adj_factor: float | None
    ex_rt: int | None  # 1:分割 2:併合 3:株主割当増資 None:該当なし

    @property
    def is_valid(self) -> bool:
        """有効日(終値がある日)か。docs/mvp.md 2.1"""
        return self.close is not None


@dataclass(frozen=True)
class MaCrossParams:
    """移動平均クロス戦略のパラメータ。率はすべて割合(0.1% → 0.001)。"""

    short_window: int
    long_window: int
    fee_rate: float
    slippage_rate: float
    initial_cash: float
    lot_size: int = 100


# --- 出力 ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DailyRecord:
    """期間内の営業日1日分の状態(その日の手順1〜4が終わった後)。"""

    date: dt.date
    close: float | None  # 未調整の終値(グラフ用)
    short_ma: float | None  # 時点 t 基準の短期移動平均(表示用。判定には使わない)
    long_ma: float | None  # 時点 t 基準の長期移動平均(表示用)
    cash: float
    shares: int
    valuation_price: float | None  # 株を持っていない日は None(5章)
    equity: float


@dataclass(frozen=True)
class Signal:
    """クロスを検出した日。action は、売買ルール(2.4)で注文にしたか無視したか。"""

    date: dt.date
    side: Side
    action: Literal["order", "ignored"]


@dataclass(frozen=True)
class Fill:
    """約定。"""

    date: dt.date
    signal_date: dt.date
    side: Side
    open_price: float  # 未調整の始値
    fill_price: float  # スリッページ込みの約定価格
    shares: int
    notional: float  # 約定代金
    fee: float
    cash_after: float


@dataclass(frozen=True)
class SkippedOrder:
    """資金不足で約定しなかった買い注文(2.7)。"""

    date: dt.date
    signal_date: dt.date
    open_price: float
    fill_price: float
    cash: float


@dataclass(frozen=True)
class CorporateActionEvent:
    """株を持っている日の分割・併合の処理(2.8)。"""

    date: dt.date
    ex_rt: int
    adj_factor: float
    ratio_numerator: int  # p
    ratio_denominator: int  # q(持ち株数は p/q 倍になる)
    shares_before: int
    shares_after: int
    fraction_shares: float  # 1株未満の端数(株数)
    fraction_cash: float  # 端数を現金に換えた額
    closed_position: bool  # 併合で0株になって決済したか


@dataclass(frozen=True)
class Trade:
    """買い→売りの1往復。exit_date が None なら期間の最後まで持ち続けた(未決済)。"""

    entry_date: dt.date
    entry_price: float
    entry_shares: int
    buy_cost: float
    exit_date: dt.date | None
    exit_price: float | None
    exit_shares: int | None
    sell_proceeds: float | None  # 売りの notional − fee
    fraction_cash: float  # 併合などの端数を現金に換えた額の合計
    pnl: float | None  # 決済した取引だけ(5章)
    closed_by: Literal["sell", "merger"] | None


@dataclass(frozen=True)
class Metrics:
    """成績表(5章)。None は「算出不可」または「−」。"""

    total_return: float
    annualized_return: float | None
    max_drawdown: float
    sharpe_ratio: float | None
    win_rate: float | None
    trade_count: int
    winning_trades: int
    return_count: int  # N(日次リターンの数)


@dataclass(frozen=True)
class WarmupInfo:
    """ウォームアップ期間(2.2、4.1)。"""

    first_date: dt.date | None
    last_date: dt.date | None
    valid_days: int
    sufficient: bool  # 開始日より前の有効日が long_window 個そろっていたか
    signals_unavailable_until: dt.date | None  # 不足して判定できなかった最後の日(不足時のみ)


@dataclass(frozen=True)
class Notes:
    """結果画面の注記を出すかどうか(4章)。生存者バイアスの注記は常に出すのでここには無い。"""

    open_position_at_end: bool  # 清算コスト控除前
    annualized_is_reference: bool  # N < 245 で年率は参考値


@dataclass(frozen=True)
class BacktestResult:
    params: MaCrossParams
    start: dt.date
    end: dt.date
    daily: tuple[DailyRecord, ...]
    signals: tuple[Signal, ...]
    fills: tuple[Fill, ...]
    skipped_orders: tuple[SkippedOrder, ...]
    events: tuple[CorporateActionEvent, ...]
    trades: tuple[Trade, ...]
    metrics: Metrics
    warmup: WarmupInfo
    notes: Notes

    @property
    def insufficient_cash_count(self) -> int:
        """資金不足で約定しなかった回数(4章の結果画面)。"""
        return len(self.skipped_orders)

    @property
    def final_equity(self) -> float:
        return self.daily[-1].equity

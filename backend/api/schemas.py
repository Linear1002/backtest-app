"""API の入力と出力の形(画面とのやり取りの契約)。http://localhost:8000/docs にそのまま表示される。

率は画面とのやり取りでは %(0.1 = 0.1%)。計算エンジンに渡す前に割合(0.001)に変換する(docs/mvp.md 4.2)。
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- 共通 ---------------------------------------------------------------------------


class ErrorItem(_Model):
    field: str | None = Field(None, description="エラーのある入力項目(全体のエラーは null)")
    message: str


class ErrorResponse(_Model):
    detail: str
    errors: list[ErrorItem] = []


class DataInfoOut(_Model):
    source_id: str
    source_label: str
    license_note: str
    fetched_at: dt.datetime | None = Field(
        description="データを取得した日時(UTC。架空データは null)"
    )
    warning: str | None = Field(
        None, description="最新のデータを取得できず、保存済みの古いデータを使ったときの説明"
    )


# --- メタ情報 ------------------------------------------------------------------------


class DataSourceOut(_Model):
    id: str
    label: str
    markets: list[str]
    license_note: str
    can_fetch: bool = Field(description="新しいデータを取得できるか(J-Quants は APIキーが必要)")


class EngineOut(_Model):
    id: str
    label: str
    available: bool
    note: str


class MetaOut(_Model):
    data_sources: list[DataSourceOut]
    engines: list[EngineOut]
    trading_days_per_year: int


# --- 銘柄 ---------------------------------------------------------------------------


class SymbolOut(_Model):
    id: str = Field(examples=["DEMO:1003"])
    market: str
    code: str
    name: str
    name_en: str | None = None
    segment: str | None = None
    sector: str | None = None
    source_id: str
    description: str | None = Field(None, description="架空銘柄で確かめられる境界ケースの説明")


class SymbolListOut(_Model):
    items: list[SymbolOut]


class MarketOut(_Model):
    code: str
    name: str
    currency: str
    lot_size: int
    trading_days_per_year: int = Field(description="年率換算に使う年間の営業日数")


class DateRangeOut(_Model):
    first_date: dt.date
    last_date: dt.date
    business_days: int = Field(description="営業日の数(売買不成立の日も含む)")
    trading_days: int = Field(description="有効日(終値がある日)の数")


class CorporateActionOut(_Model):
    date: dt.date
    ex_rt: int | None
    label: str
    adj_factor: float
    changes_shares: bool = Field(
        description="持ち株数が変わる日か(分割・併合で、調整係数が1でない日。docs/mvp.md 2.8)"
    )


class SymbolDetailOut(_Model):
    symbol: SymbolOut
    market: MarketOut
    range: DateRangeOut
    corporate_actions: list[CorporateActionOut]
    halted_days: int
    data_info: DataInfoOut


# --- 戦略 ---------------------------------------------------------------------------


class ParamOut(_Model):
    key: str
    label: str
    kind: Literal["integer", "percent", "yen"]
    default: float
    minimum: float
    maximum: float | None
    exclusive_maximum: bool
    step: float
    help: str


class StrategyOut(_Model):
    id: str
    name: str
    summary: str
    description: str
    available: bool
    params: list[ParamOut]


class StrategyListOut(_Model):
    items: list[StrategyOut]


# --- バックテスト:入力 --------------------------------------------------------------


class MaCrossParamsIn(_Model):
    """数値の型だけ確かめ、範囲のチェックは日本語メッセージを出すために API 側で行う。"""

    # Infinity・NaN は「数値で入力してください」にする
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    short_window: float = Field(5, description="短期移動平均の日数(1以上1000以下の整数)")
    long_window: float = Field(25, description="長期移動平均の日数(短期より大きく、1000以下の整数)")
    fee_rate_pct: float = Field(0.1, description="手数料率(%)。0以上10未満")
    slippage_rate_pct: float = Field(0.05, description="スリッページ率(%)。0以上10未満")
    initial_cash: float = Field(1_000_000, description="初期資金(円)。1円以上10億円以下")


class BacktestRequest(_Model):
    symbol_id: str = Field(examples=["DEMO:1003"], max_length=32)
    strategy_id: str = Field("ma_cross", max_length=64)
    engine: str = Field(
        "python", description="python(リファレンス)または cpp(ビルド後)", max_length=32
    )
    start_date: dt.date | None = Field(None, description="省略するとデータの最初の日")
    end_date: dt.date | None = Field(None, description="省略するとデータの最後の日")
    params: MaCrossParamsIn = MaCrossParamsIn()


# --- バックテスト:出力 --------------------------------------------------------------


class PeriodOut(_Model):
    start_date: dt.date
    end_date: dt.date
    first_business_day: dt.date
    last_business_day: dt.date
    business_days: int
    return_count: int = Field(description="N(日次リターンの数)= 営業日数 − 1")


class ParamsOut(_Model):
    short_window: int
    long_window: int
    fee_rate_pct: float
    slippage_rate_pct: float
    fee_rate: float = Field(description="エンジンに渡した割合")
    slippage_rate: float = Field(description="エンジンに渡した割合")
    initial_cash: float
    lot_size: int
    trading_days_per_year: int = Field(description="年率換算に使った年間の営業日数")


class MetricsOut(_Model):
    total_return: float
    annualized_return: float | None = Field(description="null は算出不可")
    max_drawdown: float
    sharpe_ratio: float | None = Field(description="null は算出不可")
    win_rate: float | None = Field(description="null は「−」(決済した取引がない)")
    trade_count: int
    winning_trades: int
    final_equity: float
    profit: float


class WarmupOut(_Model):
    first_date: dt.date | None
    last_date: dt.date | None
    valid_days: int
    sufficient: bool
    signals_unavailable_until: dt.date | None
    label: str = Field(description="画面にそのまま出せる説明(docs/mvp.md 4.1)")


class NoteOut(_Model):
    kind: Literal[
        "liquidation",
        "annualized_reference",
        "survivorship",
        "demo_data",
        "warmup_shortage",
        "insufficient_cash",
        "execution_assumption",
        "data_license",
        "stale_data",
    ]
    message: str


class DailyOut(_Model):
    date: dt.date
    close: float | None
    short_ma: float | None
    long_ma: float | None
    cash: float
    shares: int
    valuation_price: float | None
    equity: float
    drawdown: float = Field(description="その日までの最高値からの下落率(表示用)")


class SignalOut(_Model):
    date: dt.date
    side: Literal["buy", "sell"]
    action: Literal["order", "ignored"]


class FillOut(_Model):
    date: dt.date
    signal_date: dt.date
    side: Literal["buy", "sell"]
    open_price: float
    fill_price: float
    shares: int
    notional: float
    fee: float
    cash_after: float


class SkippedOrderOut(_Model):
    date: dt.date
    signal_date: dt.date
    open_price: float
    fill_price: float
    cash: float


class EventOut(_Model):
    date: dt.date
    ex_rt: int
    label: str
    adj_factor: float
    ratio: str = Field(description="持ち株数の倍率 p/q")
    shares_before: int
    shares_after: int
    fraction_shares: float
    fraction_cash: float
    closed_position: bool


class TradeOut(_Model):
    entry_date: dt.date
    entry_price: float
    entry_shares: int
    buy_cost: float
    exit_date: dt.date | None
    exit_price: float | None
    exit_shares: int | None
    sell_proceeds: float | None
    fraction_cash: float
    pnl: float | None
    return_pct: float | None = Field(description="損益 ÷ 買いの費用 × 100")
    closed_by: Literal["sell", "merger"] | None


class BacktestOut(_Model):
    symbol: SymbolOut
    strategy_id: str
    engine: EngineOut
    period: PeriodOut
    params: ParamsOut
    metrics: MetricsOut
    warmup: WarmupOut
    insufficient_cash_count: int
    notes: list[NoteOut]
    daily: list[DailyOut]
    signals: list[SignalOut]
    fills: list[FillOut]
    skipped_orders: list[SkippedOrderOut]
    events: list[EventOut]
    trades: list[TradeOut]
    corporate_actions: list[CorporateActionOut] = Field(
        description="期間内の権利落ち(株を持っていない日も含む)。チャートの線を切る位置などに使う"
    )
    data_info: DataInfoOut
    elapsed_ms: float = Field(description="計算にかかった時間(ミリ秒)")

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


class SweepEngineOut(_Model):
    id: str
    label: str
    available: bool
    note: str
    max_pairs: int = Field(description="このエンジンで計算できる組み合わせの数の上限")


class MetaOut(_Model):
    data_sources: list[DataSourceOut]
    engines: list[EngineOut]
    sweep_engines: list[SweepEngineOut] = Field(
        description="総当たりに使えるエンジン(docs/sweep.md)"
    )
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
        "trials",
        "selection_bias",
        "no_holdout",
        "aligned_start",
        "sampling_error",
        "benchmark",
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
    benchmark_equity: float = Field(description="同じ日の、買い持ち(docs/benchmark.md)の資産額")


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


class BenchmarkMetricsOut(_Model):
    """買い持ちの成績(docs/mvp.md 5章と同じ定義)。勝率・取引回数は出さない(売らないため)。"""

    total_return: float
    annualized_return: float | None = Field(description="null は算出不可")
    max_drawdown: float
    sharpe_ratio: float | None = Field(description="null は算出不可")
    return_count: int
    final_equity: float


BenchmarkStatus = Literal["bought", "insufficient_cash", "not_bought"]
BENCHMARK_STATUS_HELP = (
    "bought:買った / insufficient_cash:資金不足で買えなかった / not_bought:買う日がなかった。"
    "買えなかったときは、比べない(値は初期資金のまま)"
)


class SegmentBenchmarkOut(BenchmarkMetricsOut):
    """総当たりの期間ごとの買い持ち(docs/benchmark.md)。"""

    status: BenchmarkStatus = Field(description=BENCHMARK_STATUS_HELP)


class BenchmarkOut(_Model):
    """比較の基準:買い持ち(docs/benchmark.md)。同じ期間・同じ費用で、最初に買って最後まで持った場合。"""

    label: str
    status: BenchmarkStatus = Field(description=BENCHMARK_STATUS_HELP)
    signal_date: dt.date | None = Field(description="買うと決めた日(期間内の最初の有効日)")
    fill: FillOut | None
    skipped: SkippedOrderOut | None
    events: list[EventOut]
    metrics: BenchmarkMetricsOut
    open_position_at_end: bool


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
    benchmark: BenchmarkOut
    corporate_actions: list[CorporateActionOut] = Field(
        description="期間内の権利落ち(株を持っていない日も含む)。チャートの線を切る位置などに使う"
    )
    data_info: DataInfoOut
    elapsed_ms: float = Field(description="計算にかかった時間(ミリ秒)")


# --- 総当たり(docs/sweep.md):入力 -------------------------------------------------


class SweepGridIn(_Model):
    """短期日数 × 長期日数の格子。整数かどうか・範囲のチェックは、日本語のメッセージを出すために API 側で行う。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    short_min: float = Field(3, description="短期日数の最小(1以上1000以下の整数)")
    short_max: float = Field(30, description="短期日数の最大")
    short_step: float = Field(3, description="短期日数の刻み")
    long_min: float = Field(20, description="長期日数の最小")
    long_max: float = Field(120, description="長期日数の最大")
    long_step: float = Field(10, description="長期日数の刻み")


class SweepCostsIn(_Model):
    """全組み合わせで共通の費用と資金。率は %。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    fee_rate_pct: float = Field(0.1, description="手数料率(%)。0以上10未満")
    slippage_rate_pct: float = Field(0.05, description="スリッページ率(%)。0以上10未満")
    initial_cash: float = Field(1_000_000, description="初期資金(円)。1円以上10億円以下")


class SweepRequest(_Model):
    symbol_id: str = Field(examples=["DEMO:1003"], max_length=32)
    strategy_id: str = Field("ma_cross", max_length=64)
    engine: str = Field(
        "python",
        description="総当たりに使うエンジン(GET /api/meta の sweep_engines)",
        max_length=32,
    )
    start_date: dt.date | None = Field(None, description="省略するとデータの最初の日")
    end_date: dt.date | None = Field(None, description="省略するとデータの最後の日")
    holdout_start_date: dt.date | None = Field(
        None,
        description="検証期間(アウトオブサンプル)の開始日。省略すると検証期間なし(docs/sweep.md 3章)",
    )
    grid: SweepGridIn = SweepGridIn()
    params: SweepCostsIn = SweepCostsIn()


# --- 総当たり:出力 ------------------------------------------------------------------


class SegmentOut(_Model):
    name: Literal["in_sample", "out_of_sample"] = Field(
        description="in_sample は選ぶ期間、out_of_sample は検証期間"
    )
    start_date: dt.date = Field(
        description="計算した期間の開始日(選ぶ期間は、始まりをそろえたあとの日)"
    )
    end_date: dt.date
    requested_start_date: dt.date = Field(
        description="指定された開始日。選ぶ期間の始まりをそろえたとき(docs/sweep.md 3章)だけ start_date と違う"
    )
    skipped_trading_days: int = Field(
        description=(
            "そろえるためにウォームアップにだけ使った有効日(売買が成立した日)の数"
            "(requested_start_date〜start_date の前日)。docs/mvp.md 4.1 のウォームアップの営業日数と同じ数え方"
        )
    )
    first_business_day: dt.date
    last_business_day: dt.date
    business_days: int
    benchmark: SegmentBenchmarkOut = Field(
        description="この期間の買い持ち(docs/benchmark.md)の成績"
    )


class SweepGridOut(_Model):
    short_min: int
    short_max: int
    short_step: int
    long_min: int
    long_max: int
    long_step: int
    short_values: list[int]
    long_values: list[int]


class SweepParamsOut(_Model):
    fee_rate_pct: float
    slippage_rate_pct: float
    fee_rate: float
    slippage_rate: float
    initial_cash: float
    lot_size: int
    trading_days_per_year: int


class SweepMetricsOut(_Model):
    """1つの期間の成績(docs/mvp.md 5章と同じ定義)。null は算出不可・「−」。"""

    total_return: float
    annualized_return: float | None
    max_drawdown: float
    sharpe_ratio: float | None
    win_rate: float | None
    trade_count: int
    winning_trades: int
    return_count: int
    insufficient_cash_count: int
    final_equity: float
    holding_days: int = Field(description="株を持っていた営業日の数")


class ComboOut(_Model):
    short_window: int
    long_window: int
    in_sample: SweepMetricsOut
    out_of_sample: SweepMetricsOut | None


class RankingOut(_Model):
    """1つの基準で並べた結果(docs/sweep.md 7章)。位置は combos の中の位置。"""

    objective: Literal["sharpe_ratio", "total_return", "max_drawdown"]
    order: list[int] = Field(description="選ぶ期間の成績のよい順")
    best_index: int | None
    best_tie_count: int = Field(
        description="選ぶ期間の1位と同じ値の組み合わせの数。2以上なら1位は1つに決まらない(order の先頭からこの数)"
    )
    best_out_of_sample_rank: int | None = Field(
        description="1位の組み合わせの、検証期間での順位(同率1位のときは null)"
    )
    in_sample_ranked: int = Field(description="選ぶ期間の値がある組み合わせの数")
    out_of_sample_ranked: int = Field(description="検証期間の値がある組み合わせの数")
    in_sample_beats_benchmark: int | None = Field(
        description="選ぶ期間で、買い持ちより良かった組み合わせの数(買い持ちの値が算出不可なら null)"
    )
    out_of_sample_beats_benchmark: int | None = Field(
        description="検証期間で、買い持ちより良かった組み合わせの数(検証期間がない・買い持ちの値が算出不可なら null)"
    )
    rank_correlation: float | None = Field(description="選ぶ期間と検証期間の順位相関(スピアマン)")
    correlation_pairs: int
    neighbors_mean: float | None = Field(
        description="1位のとなりの組み合わせの、選ぶ期間の値の平均(同率1位のときは null)"
    )
    neighbors_count: int


class SweepResultOut(_Model):
    symbol: SymbolOut
    strategy_id: str
    engine: SweepEngineOut
    segments: list[SegmentOut]
    grid: SweepGridOut
    params: SweepParamsOut
    count: int = Field(description="試した組み合わせの数")
    combos: list[ComboOut]
    rankings: list[RankingOut]
    notes: list[NoteOut]
    data_info: DataInfoOut


class SweepStatusOut(_Model):
    id: str
    status: Literal["running", "done", "failed", "cancelled"]
    done: int = Field(description="計算が終わった組み合わせの数")
    total: int = Field(description="組み合わせの数")
    elapsed_ms: float | None = Field(description="計算にかかった時間(終わったときだけ)")
    result: SweepResultOut | None = None
    error: ErrorResponse | None = None

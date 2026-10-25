"""比較の基準:買い持ちのリファレンス実装(docs/benchmark.md)。

期間内の最初の有効日の終値で「買う」と決め、次の有効日の始値で買えるだけ買って、期間の最後まで持つ。
約定(fill_buy)・分割・併合(apply_split_or_merger)・評価価格・指標は、移動平均クロス(backtest.py)と同じ関数を使う
(買い持ちのために書き直さない)。
1日の処理の順番も同じ(docs/mvp.md 2.5 の手順1〜3)。シグナルの判定(手順4)の代わりに、最初の有効日に「買う」と決める。

C++ 版・CUDA 版の約束(docs/cpp/contract.md)には入れない。API はいつもこの Python の関数で計算する。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from engine.reference.backtest import (
    MIN_PERIOD_BUSINESS_DAYS,
    apply_split_or_merger,
    fill_buy,
    is_split_or_merger,
    validate_order,
    validate_params,
    validate_records,
    valuation_price,
)
from engine.reference.metrics import compute_metrics
from engine.reference.types import (
    Bar,
    CorporateActionEvent,
    EngineInputError,
    Fill,
    MaCrossParams,
    SkippedOrder,
)


@dataclass(frozen=True)
class HoldingDay:
    """期間内の営業日1日分の状態(その日の手順1〜3が終わった後)。"""

    date: dt.date
    cash: float
    shares: int
    valuation_price: float | None  # 株を持っていない日は None(docs/mvp.md 5章)
    equity: float


@dataclass(frozen=True)
class BenchmarkMetrics:
    """買い持ちの成績(docs/mvp.md 5章と同じ定義・同じ計算の順番)。勝率・取引回数は出さない(売らないため)。"""

    total_return: float
    annualized_return: float | None
    max_drawdown: float
    sharpe_ratio: float | None
    return_count: int


@dataclass(frozen=True)
class BuyAndHoldResult:
    start: dt.date
    end: dt.date
    signal_date: dt.date | None  # 買うと決めた日(期間内の最初の有効日)。有効日がなければ None
    fill: Fill | None  # 買いの約定。資金不足・約定する日がなかったときは None
    skipped: SkippedOrder | None  # 資金不足で買えなかったとき
    events: tuple[CorporateActionEvent, ...]  # 株を持っている日の分割・併合の処理
    daily: tuple[HoldingDay, ...]
    metrics: BenchmarkMetrics

    @property
    def final_equity(self) -> float:
        return self.daily[-1].equity

    @property
    def open_position_at_end(self) -> bool:
        """期間の最後に株を持っているか(清算コスト控除前の注記に使う)。"""
        return self.daily[-1].shares > 0


def run_buy_and_hold(
    bars: Sequence[Bar], start: dt.date, end: dt.date, params: MaCrossParams
) -> BuyAndHoldResult:
    """bars はその銘柄の日足(古い順)。params のうち日数は使わない(費用・資金・売買単位・年間の営業日数だけ)。

    チェックの順番は run_backtest と同じ(パラメータ → 開始日 ≤ 終了日 → 日付の順番 → 営業日の数 → レコード)。
    ウォームアップがないので、レコードを確かめるのは期間内の営業日だけ(docs/benchmark.md 2章の6)。
    """
    validate_params(params)
    if start > end:
        raise EngineInputError("開始日は終了日より前の日付にしてください")
    validate_order(bars)
    period = [bar for bar in bars if start <= bar.date <= end]
    if len(period) < MIN_PERIOD_BUSINESS_DAYS:
        raise EngineInputError("期間が短すぎます。営業日が3日以上になるように指定してください")
    validate_records(period)

    signal_date = next((bar.date for bar in period if bar.is_valid), None)
    cash = float(params.initial_cash)
    shares = 0
    pending = False  # 約定待ちの買い注文(最初の有効日の終値で出す)
    fill: Fill | None = None
    skipped: SkippedOrder | None = None
    events: list[CorporateActionEvent] = []
    daily: list[HoldingDay] = []

    for t, bar in enumerate(period):
        # 手順1:分割・併合の処理(docs/mvp.md 2.8)。移動平均クロスと同じ計算
        if is_split_or_merger(bar) and shares > 0:
            split = apply_split_or_merger(period, t, shares)
            cash = cash + split.fraction_cash
            events.append(split.event)
            shares = split.shares  # 併合で0株になったら、そのあとは現金のまま(買い直さない)

        # 手順2:約定(docs/mvp.md 2.6・2.7)。始値が Null なら次の有効日に繰り越す
        if pending and bar.open is not None:
            assert signal_date is not None
            bought = fill_buy(bar, signal_date, cash, params)
            if bought.fill is None:
                skipped = (
                    bought.skipped
                )  # 資金不足。買い持ちは買い直さない(docs/benchmark.md 2章の2)
            else:
                fill = bought.fill
                cash = bought.fill.cash_after
                shares = bought.shares
            pending = False

        # 手順3:評価(docs/mvp.md 5章)
        price = valuation_price(period, t) if shares > 0 else None
        equity = cash + shares * price if price is not None else cash
        daily.append(
            HoldingDay(
                date=bar.date, cash=cash, shares=shares, valuation_price=price, equity=equity
            )
        )

        # 手順4の代わり:最初の有効日の終値で「買う」と決める(約定は次の有効日の始値。最終日なら約定しない)
        if bar.date == signal_date:
            pending = True

    m = compute_metrics(
        [day.equity for day in daily], params.initial_cash, (), params.trading_days_per_year
    )
    return BuyAndHoldResult(
        start=start,
        end=end,
        signal_date=signal_date,
        fill=fill,
        skipped=skipped,
        events=tuple(events),
        daily=tuple(daily),
        metrics=BenchmarkMetrics(
            total_return=m.total_return,
            annualized_return=m.annualized_return,
            max_drawdown=m.max_drawdown,
            sharpe_ratio=m.sharpe_ratio,
            return_count=m.return_count,
        ),
    )

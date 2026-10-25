"""データ層・エンジンの型と、API の出力の形を変換する。"""

from __future__ import annotations

from collections.abc import Sequence

from backend.api.schemas import (
    BenchmarkMetricsOut,
    BenchmarkOut,
    CorporateActionOut,
    DailyOut,
    DataInfoOut,
    EventOut,
    FillOut,
    MetricsOut,
    NoteOut,
    SignalOut,
    SkippedOrderOut,
    SymbolOut,
    TradeOut,
    WarmupOut,
)
from backend.marketdata.models import DailyBar, DataInfo, SymbolInfo
from engine.reference import BacktestResult, Bar
from engine.reference.benchmark import BuyAndHoldResult
from engine.reference.types import CorporateActionEvent, Fill, SkippedOrder, WarmupInfo

EX_RT_LABELS = {1: "株式分割", 2: "株式併合", 3: "株主割当増資"}

NOTE_MESSAGES = {
    "liquidation": "最終日の資産額は、持っている株を売る手数料・スリッページを引く前の値です(清算コスト控除前)",
    "annualized_reference": "期間が1年未満のため、年率リターンは参考値です",
    "survivorship": "選べる銘柄は現在も上場している銘柄だけのため、結果は実際より良く見えやすくなります",
    "demo_data": "架空データです。実在の銘柄・株価ではありません",
    "execution_assumption": "寄付きの成行注文で、始値で約定できたと仮定しています(ストップ高・ストップ安、配当、税金は考慮していません)",
    "benchmark": (
        "買い持ちは、期間の最初に売買が成立した日の終値で買うと決め、次に売買が成立した日の始値で買えるだけ買って、"
        "最後まで持った場合です(手数料・スリッページ・分割の扱いは同じ)。配当を含めないので、ずっと株を持つ買い持ちのほうが、"
        "実際より不利に出ます。一方、買い持ちの最後の日は売らずに評価する(清算コスト控除前)ので、売買ルールが最後に"
        "売り切っているときは、その売りの費用の分だけ買い持ちが有利です"
    ),
}

BENCHMARK_LABEL = "買い持ち"


def to_engine_bars(bars: Sequence[DailyBar]) -> list[Bar]:
    """データ層の日足 → エンジンの入力。"""
    return [
        Bar(
            date=b.date,
            open=b.open,
            high=b.high,
            low=b.low,
            close=b.close,
            volume=b.volume,
            adj_factor=b.adj_factor,
            ex_rt=b.ex_rt,
        )
        for b in bars
    ]


def symbol_out(info: SymbolInfo, source_id: str, description: str | None = None) -> SymbolOut:
    """銘柄の情報。description は架空銘柄で確かめられる境界ケースの説明(データソースの describe)。"""
    return SymbolOut(
        id=str(info.symbol_id),
        market=info.symbol_id.market,
        code=info.symbol_id.code,
        name=info.name,
        name_en=info.name_en,
        segment=info.segment,
        sector=info.sector,
        source_id=source_id,
        description=description,
    )


def data_info_out(info: DataInfo) -> DataInfoOut:
    return DataInfoOut(
        source_id=info.source_id,
        source_label=info.source_label,
        license_note=info.license_note,
        fetched_at=info.fetched_at,
        warning=info.warning,
    )


def changes_shares(bar: DailyBar) -> bool:
    """持ち株数が変わる日か(分割・併合で、調整係数が1でない日。docs/mvp.md 2.8 と同じ条件)。"""
    return bar.ex_rt in (1, 2) and bar.adj_factor not in (None, 1.0)


def corporate_actions_out(bars: Sequence[DailyBar]) -> list[CorporateActionOut]:
    """権利落ちの日(調整係数が1でない日と、権利落ちの種類が入っている日)。"""
    return [
        CorporateActionOut(
            date=bar.date,
            ex_rt=bar.ex_rt,
            label=EX_RT_LABELS.get(bar.ex_rt or 0, "権利落ち"),
            adj_factor=bar.adj_factor if bar.adj_factor is not None else 1.0,
            changes_shares=changes_shares(bar),
        )
        for bar in bars
        if bar.ex_rt is not None or bar.adj_factor not in (None, 1.0)
    ]


def warmup_out(w: WarmupInfo) -> WarmupOut:
    if w.valid_days == 0:
        label = "ウォームアップ期間:なし"
    else:
        label = (
            f"ウォームアップに使った期間:{w.first_date.isoformat()}〜{w.last_date.isoformat()}"  # type: ignore[union-attr]
            f"({w.valid_days}営業日)"
        )
    return WarmupOut(
        first_date=w.first_date,
        last_date=w.last_date,
        valid_days=w.valid_days,
        sufficient=w.sufficient,
        signals_unavailable_until=w.signals_unavailable_until,
        label=label,
    )


def notes_out(
    result: BacktestResult,
    market: str,
    data_info: DataInfo,
    benchmark: BuyAndHoldResult | None = None,
) -> list[NoteOut]:
    notes: list[NoteOut] = []
    if data_info.warning:
        notes.append(NoteOut(kind="stale_data", message=data_info.warning))
    if result.notes.open_position_at_end:
        notes.append(NoteOut(kind="liquidation", message=NOTE_MESSAGES["liquidation"]))
    if result.notes.annualized_is_reference:
        notes.append(
            NoteOut(kind="annualized_reference", message=NOTE_MESSAGES["annualized_reference"])
        )
    if result.warmup.signals_unavailable_until is not None:
        until = result.warmup.signals_unavailable_until.isoformat()
        notes.append(
            NoteOut(
                kind="warmup_shortage",
                message=f"開始日より前のデータが不足しているため、{until} までシグナルを出していません",
            )
        )
    if result.insufficient_cash_count:
        notes.append(
            NoteOut(
                kind="insufficient_cash",
                message=(
                    f"資金不足で約定しなかった買い注文が {result.insufficient_cash_count} 回ありました"
                    f"(売買単位の{result.params.lot_size}株を買えなかった)"
                ),
            )
        )
    if market == "DEMO":
        notes.append(NoteOut(kind="demo_data", message=NOTE_MESSAGES["demo_data"]))
    else:
        notes.append(NoteOut(kind="survivorship", message=NOTE_MESSAGES["survivorship"]))
        notes.append(NoteOut(kind="data_license", message=data_info.license_note))
    notes.append(
        NoteOut(kind="execution_assumption", message=NOTE_MESSAGES["execution_assumption"])
    )
    if benchmark is not None:
        notes.append(NoteOut(kind="benchmark", message=NOTE_MESSAGES["benchmark"]))
    return notes


def metrics_out(result: BacktestResult) -> MetricsOut:
    m = result.metrics
    return MetricsOut(
        total_return=m.total_return,
        annualized_return=m.annualized_return,
        max_drawdown=m.max_drawdown,
        sharpe_ratio=m.sharpe_ratio,
        win_rate=m.win_rate,
        trade_count=m.trade_count,
        winning_trades=m.winning_trades,
        final_equity=result.final_equity,
        profit=result.final_equity - result.params.initial_cash,
    )


def daily_out(result: BacktestResult, benchmark: BuyAndHoldResult) -> list[DailyOut]:
    """日々の数値。買い持ちの資産額も同じ日に並べる(同じ期間の営業日なので、日付は1対1で対応する)。"""
    assert [d.date for d in benchmark.daily] == [d.date for d in result.daily]
    rows = []
    peak = result.daily[0].equity
    for r, b in zip(result.daily, benchmark.daily, strict=True):
        peak = max(peak, r.equity)
        rows.append(
            DailyOut(
                date=r.date,
                close=r.close,
                short_ma=r.short_ma,
                long_ma=r.long_ma,
                cash=r.cash,
                shares=r.shares,
                valuation_price=r.valuation_price,
                equity=r.equity,
                drawdown=1 - r.equity / peak,
                benchmark_equity=b.equity,
            )
        )
    return rows


def signals_out(result: BacktestResult) -> list[SignalOut]:
    return [SignalOut(date=s.date, side=s.side, action=s.action) for s in result.signals]


def fill_out(f: Fill) -> FillOut:
    return FillOut(
        date=f.date,
        signal_date=f.signal_date,
        side=f.side,
        open_price=f.open_price,
        fill_price=f.fill_price,
        shares=f.shares,
        notional=f.notional,
        fee=f.fee,
        cash_after=f.cash_after,
    )


def fills_out(result: BacktestResult) -> list[FillOut]:
    return [fill_out(f) for f in result.fills]


def skipped_order_out(s: SkippedOrder) -> SkippedOrderOut:
    return SkippedOrderOut(
        date=s.date,
        signal_date=s.signal_date,
        open_price=s.open_price,
        fill_price=s.fill_price,
        cash=s.cash,
    )


def skipped_out(result: BacktestResult) -> list[SkippedOrderOut]:
    return [skipped_order_out(s) for s in result.skipped_orders]


def events_out(result: BacktestResult) -> list[EventOut]:
    return event_rows_out(result.events)


def event_rows_out(events: Sequence[CorporateActionEvent]) -> list[EventOut]:
    return [
        EventOut(
            date=e.date,
            ex_rt=e.ex_rt,
            label=EX_RT_LABELS.get(e.ex_rt, "権利落ち"),
            adj_factor=e.adj_factor,
            ratio=f"{e.ratio_numerator}/{e.ratio_denominator}",
            shares_before=e.shares_before,
            shares_after=e.shares_after,
            fraction_shares=e.fraction_shares,
            fraction_cash=e.fraction_cash,
            closed_position=e.closed_position,
        )
        for e in events
    ]


def benchmark_metrics_out(b: BuyAndHoldResult) -> BenchmarkMetricsOut:
    m = b.metrics
    return BenchmarkMetricsOut(
        total_return=m.total_return,
        annualized_return=m.annualized_return,
        max_drawdown=m.max_drawdown,
        sharpe_ratio=m.sharpe_ratio,
        return_count=m.return_count,
        final_equity=b.final_equity,
    )


def benchmark_status(b: BuyAndHoldResult) -> str:
    """買えたか(bought)、資金不足で買えなかったか(insufficient_cash)、買う日がなかったか(not_bought)。"""
    if b.fill is not None:
        return "bought"
    if b.skipped is not None:
        return "insufficient_cash"
    return "not_bought"


def benchmark_out(b: BuyAndHoldResult) -> BenchmarkOut:
    """買い持ち(docs/benchmark.md)の結果。"""
    return BenchmarkOut(
        label=BENCHMARK_LABEL,
        status=benchmark_status(b),  # type: ignore[arg-type]
        signal_date=b.signal_date,
        fill=fill_out(b.fill) if b.fill is not None else None,
        skipped=skipped_order_out(b.skipped) if b.skipped is not None else None,
        events=event_rows_out(b.events),
        metrics=benchmark_metrics_out(b),
        open_position_at_end=b.open_position_at_end,
    )


def trades_out(result: BacktestResult) -> list[TradeOut]:
    return [
        TradeOut(
            entry_date=t.entry_date,
            entry_price=t.entry_price,
            entry_shares=t.entry_shares,
            buy_cost=t.buy_cost,
            exit_date=t.exit_date,
            exit_price=t.exit_price,
            exit_shares=t.exit_shares,
            sell_proceeds=t.sell_proceeds,
            fraction_cash=t.fraction_cash,
            pnl=t.pnl,
            return_pct=None if t.pnl is None else t.pnl / t.buy_cost * 100,
            closed_by=t.closed_by,
        )
        for t in result.trades
    ]

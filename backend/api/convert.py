"""データ層・エンジンの型と、API の出力の形を変換する。"""

from __future__ import annotations

from collections.abc import Sequence

from backend.api.schemas import (
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
from backend.marketdata.synthetic import DemoDataSource
from engine.reference import BacktestResult, Bar
from engine.reference.types import WarmupInfo

EX_RT_LABELS = {1: "株式分割", 2: "株式併合", 3: "株主割当増資"}

NOTE_MESSAGES = {
    "liquidation": "最終日の資産額は、持っている株を売る手数料・スリッページを引く前の値です(清算コスト控除前)",
    "annualized_reference": "期間が1年未満のため、年率リターンは参考値です",
    "survivorship": "選べる銘柄は現在も上場している銘柄だけのため、結果は実際より良く見えやすくなります",
    "demo_data": "架空データです。実在の銘柄・株価ではありません",
    "execution_assumption": "寄付きの成行注文で、始値で約定できたと仮定しています(ストップ高・ストップ安、配当、税金は考慮していません)",
}

_demo = DemoDataSource()


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


def symbol_out(info: SymbolInfo, source_id: str) -> SymbolOut:
    description = _demo.describe(info.symbol_id) if info.symbol_id.market == "DEMO" else None
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
    )


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


def notes_out(result: BacktestResult, market: str, license_note: str) -> list[NoteOut]:
    notes: list[NoteOut] = []
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
                message=f"資金不足で約定しなかった買い注文が {result.insufficient_cash_count} 回ありました(売買単位の100株を買えなかった)",
            )
        )
    if market == "DEMO":
        notes.append(NoteOut(kind="demo_data", message=NOTE_MESSAGES["demo_data"]))
    else:
        notes.append(NoteOut(kind="survivorship", message=NOTE_MESSAGES["survivorship"]))
        notes.append(NoteOut(kind="data_license", message=license_note))
    notes.append(
        NoteOut(kind="execution_assumption", message=NOTE_MESSAGES["execution_assumption"])
    )
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


def daily_out(result: BacktestResult) -> list[DailyOut]:
    rows = []
    peak = result.daily[0].equity
    for r in result.daily:
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
            )
        )
    return rows


def signals_out(result: BacktestResult) -> list[SignalOut]:
    return [SignalOut(date=s.date, side=s.side, action=s.action) for s in result.signals]


def fills_out(result: BacktestResult) -> list[FillOut]:
    return [
        FillOut(
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
        for f in result.fills
    ]


def skipped_out(result: BacktestResult) -> list[SkippedOrderOut]:
    return [
        SkippedOrderOut(
            date=s.date,
            signal_date=s.signal_date,
            open_price=s.open_price,
            fill_price=s.fill_price,
            cash=s.cash,
        )
        for s in result.skipped_orders
    ]


def events_out(result: BacktestResult) -> list[EventOut]:
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
        for e in result.events
    ]


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

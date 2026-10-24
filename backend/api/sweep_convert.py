"""総当たりの結果を、画面に返す形(SweepResultOut)にする(docs/sweep.md 6〜8章)。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from backend.api.convert import NOTE_MESSAGES, data_info_out
from backend.api.schemas import (
    ComboOut,
    NoteOut,
    RankingOut,
    SegmentOut,
    SweepEngineOut,
    SweepGridOut,
    SweepMetricsOut,
    SweepParamsOut,
    SweepResultOut,
    SymbolOut,
)
from backend.marketdata.models import DailyBar, DataInfo
from backend.sweep_summary import OBJECTIVES, rank
from engine.reference.sweep import (
    IN_SAMPLE,
    OUT_OF_SAMPLE,
    Segment,
    SegmentMetrics,
    SweepCosts,
    SweepGrid,
    SweepRow,
)

SEGMENT_LABELS = {IN_SAMPLE: "選ぶ期間", OUT_OF_SAMPLE: "検証期間"}


@dataclass(frozen=True)
class SweepContext:
    """ジョブを始めるときに決まっている、結果の画面に出す情報。"""

    symbol: SymbolOut
    strategy_id: str
    engine: SweepEngineOut
    market: str
    data_info: DataInfo
    grid: SweepGrid
    costs: SweepCosts
    fee_rate_pct: float
    slippage_rate_pct: float
    segments: tuple[SegmentOut, ...]


def segments_out(segments: Sequence[Segment], bars: Sequence[DailyBar]) -> tuple[SegmentOut, ...]:
    """期間ごとの最初・最後の営業日と営業日の数(入力チェックを通ったあとなので、どの期間も3日以上ある)。"""
    out = []
    for segment in segments:
        days = [bar.date for bar in bars if segment.start <= bar.date <= segment.end]
        out.append(
            SegmentOut(
                name=segment.name,  # type: ignore[arg-type]
                start_date=segment.start,
                end_date=segment.end,
                first_business_day=days[0],
                last_business_day=days[-1],
                business_days=len(days),
            )
        )
    return tuple(out)


def metrics_out(m: SegmentMetrics) -> SweepMetricsOut:
    return SweepMetricsOut(
        total_return=m.total_return,
        annualized_return=m.annualized_return,
        max_drawdown=m.max_drawdown,
        sharpe_ratio=m.sharpe_ratio,
        win_rate=m.win_rate,
        trade_count=m.trade_count,
        winning_trades=m.winning_trades,
        return_count=m.return_count,
        insufficient_cash_count=m.insufficient_cash_count,
        final_equity=m.final_equity,
    )


def notes_out(context: SweepContext, count: int) -> list[NoteOut]:
    """結果を読むときの注意(docs/sweep.md 8章)。総当たりに特有のものを先に出す。"""
    notes: list[NoteOut] = []
    if context.data_info.warning:
        notes.append(NoteOut(kind="stale_data", message=context.data_info.warning))
    notes.append(
        NoteOut(
            kind="trials",
            message=(
                f"{count:,}通りの組み合わせを試した結果です。たくさん試すほど、"
                "たまたま良かっただけの組み合わせが上位に来やすくなります(過剰最適化)"
            ),
        )
    )
    has_holdout = any(s.name == OUT_OF_SAMPLE for s in context.segments)
    if has_holdout:
        notes.append(
            NoteOut(
                kind="selection_bias",
                message=(
                    "順位は選ぶ期間の成績だけで付けています。検証期間の成績を見て選び直すと、"
                    "検証期間も「選ぶ期間」になってしまい、確かめたことになりません"
                ),
            )
        )
    else:
        notes.append(
            NoteOut(
                kind="no_holdout",
                message=(
                    "検証期間(選ぶのに使っていない期間)がないため、上位の組み合わせがほかの期間でも"
                    "通用するかは確かめていません"
                ),
            )
        )
    for segment in context.segments:
        if segment.business_days - 1 < context.costs.trading_days_per_year:
            label = SEGMENT_LABELS[segment.name] if has_holdout else "期間"
            notes.append(
                NoteOut(
                    kind="annualized_reference",
                    message=f"{label}が1年未満のため、その期間の年率リターンは参考値です",
                )
            )
    notes.append(
        NoteOut(
            kind="liquidation",
            message=(
                "最終日の資産額とリターンは、期間の最後に持っている株を売る手数料・スリッページを"
                "引く前の値です(清算コスト控除前)"
            ),
        )
    )
    if context.market == "DEMO":
        notes.append(NoteOut(kind="demo_data", message=NOTE_MESSAGES["demo_data"]))
    else:
        notes.append(NoteOut(kind="survivorship", message=NOTE_MESSAGES["survivorship"]))
        notes.append(NoteOut(kind="data_license", message=context.data_info.license_note))
    notes.append(
        NoteOut(kind="execution_assumption", message=NOTE_MESSAGES["execution_assumption"])
    )
    return notes


def result_out(
    context: SweepContext, pairs: Sequence[tuple[int, int]], rows: Sequence[SweepRow]
) -> SweepResultOut:
    """組み合わせの順番に並んだ行(選ぶ期間 → 検証期間)を、組み合わせごとの成績と並べ方にまとめる。"""
    by_pair: dict[tuple[int, int], dict[str, SegmentMetrics]] = {}
    for row in rows:
        by_pair.setdefault((row.short_window, row.long_window), {})[row.segment] = row.metrics
    in_sample = [by_pair[pair][IN_SAMPLE] for pair in pairs]
    has_holdout = any(s.name == OUT_OF_SAMPLE for s in context.segments)
    out_of_sample = [by_pair[pair][OUT_OF_SAMPLE] for pair in pairs] if has_holdout else None
    grid = context.grid
    short_values, long_values = grid.short_values(), grid.long_values()
    combos = [
        ComboOut(
            short_window=short,
            long_window=long,
            in_sample=metrics_out(in_sample[i]),
            out_of_sample=metrics_out(out_of_sample[i]) if out_of_sample is not None else None,
        )
        for i, (short, long) in enumerate(pairs)
    ]
    rankings = []
    for objective in OBJECTIVES:
        r = rank(pairs, short_values, long_values, in_sample, out_of_sample, objective)
        rankings.append(
            RankingOut(
                objective=r.objective,
                order=list(r.order),
                best_index=r.best_index,
                best_out_of_sample_rank=r.best_out_of_sample_rank,
                out_of_sample_ranked=r.out_of_sample_ranked,
                rank_correlation=r.rank_correlation,
                correlation_pairs=r.correlation_pairs,
                neighbors_mean=r.neighbors_mean,
                neighbors_count=r.neighbors_count,
            )
        )
    costs = context.costs
    return SweepResultOut(
        symbol=context.symbol,
        strategy_id=context.strategy_id,
        engine=context.engine,
        segments=list(context.segments),
        grid=SweepGridOut(
            short_min=grid.short_min,
            short_max=grid.short_max,
            short_step=grid.short_step,
            long_min=grid.long_min,
            long_max=grid.long_max,
            long_step=grid.long_step,
            short_values=short_values,
            long_values=long_values,
        ),
        params=SweepParamsOut(
            fee_rate_pct=context.fee_rate_pct,
            slippage_rate_pct=context.slippage_rate_pct,
            fee_rate=costs.fee_rate,
            slippage_rate=costs.slippage_rate,
            initial_cash=costs.initial_cash,
            lot_size=costs.lot_size,
            trading_days_per_year=costs.trading_days_per_year,
        ),
        count=len(pairs),
        combos=combos,
        rankings=rankings,
        notes=notes_out(context, len(pairs)),
        data_info=data_info_out(context.data_info),
    )

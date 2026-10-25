"""ウォークフォワード分析の結果を、画面に返す JSON の形にする(docs/walkforward.md 6章・8章)。"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from backend.api.convert import NOTE_MESSAGES, benchmark_out, data_info_out
from backend.api.schemas import (
    NoteOut,
    SweepEngineOut,
    SweepGridOut,
    SweepParamsOut,
    SymbolOut,
    UnusedDaysOut,
    WalkForwardDayOut,
    WalkForwardMetricsOut,
    WalkForwardPeriodOut,
    WalkForwardResultOut,
    WalkForwardWindowOut,
    WindowChoiceOut,
)
from backend.api.sweep_convert import metrics_out
from backend.marketdata.models import DailyBar, DataInfo
from engine.reference.sweep import SweepCosts, SweepGrid
from engine.reference.walkforward import WalkForwardResult, WalkForwardSettings, Window

OBJECTIVE_LABELS = {"sharpe_ratio": "シャープレシオ", "total_return": "総リターン"}


@dataclass(frozen=True)
class WalkForwardContext:
    """ジョブを始めるときに決まっている、結果の画面に出す情報。"""

    symbol: SymbolOut
    strategy_id: str
    engine: SweepEngineOut
    market: str
    data_info: DataInfo
    bars: tuple[DailyBar, ...]  # 期間の営業日の数を数えるため(API の日足。売買不成立の日も入る)
    end: dt.date  # 指定された終了日(最後の区切りのあとに残った日を出すため)
    grid: SweepGrid
    costs: SweepCosts
    fee_rate_pct: float
    slippage_rate_pct: float
    settings: WalkForwardSettings


def period_out(bars: Sequence[DailyBar], start: dt.date, end: dt.date) -> WalkForwardPeriodOut:
    """期間と、その中の最初・最後の営業日、営業日の数(入力チェックを通ったあとなので3日以上ある)。"""
    days = [bar.date for bar in bars if start <= bar.date <= end]
    return WalkForwardPeriodOut(
        start_date=start,
        end_date=end,
        first_business_day=days[0],
        last_business_day=days[-1],
        business_days=len(days),
    )


def unused_out(
    bars: Sequence[DailyBar], windows: Sequence[Window], end: dt.date
) -> UnusedDaysOut | None:
    """最後の使う期間のあとに残り、使わなかった日。営業日がなければ None。"""
    after = windows[-1].out_of_sample.end + dt.timedelta(days=1)
    days = [bar.date for bar in bars if after <= bar.date <= end]
    if not days:
        return None
    return UnusedDaysOut(start_date=after, end_date=end, business_days=len(days))


def notes_out(context: WalkForwardContext, result: WalkForwardResult) -> list[NoteOut]:
    """結果を読むときの注意(docs/walkforward.md 8章)。ウォークフォワードに特有のものを先に出す。"""
    s = context.settings
    notes: list[NoteOut] = []
    if context.data_info.warning:
        notes.append(NoteOut(kind="stale_data", message=context.data_info.warning))
    notes.append(
        NoteOut(
            kind="walkforward_stitching",
            message=(
                f"区切りごとに、直前の{s.in_sample_months}か月(選ぶ期間)だけで{OBJECTIVE_LABELS[s.objective]}が1位の日数を選び、"
                f"次の{s.out_of_sample_months}か月(使う期間)だけその日数で売買した結果を、使う期間だけつないだものです。"
                "どの日も、その日より前のデータだけで選んだ日数で売買しています"
            ),
        )
    )
    notes.append(
        NoteOut(
            kind="walkforward_trials",
            message=(
                f"区切りごとに{len(result.pairs):,}通りの組み合わせを試して選んでいます。格子・選ぶ期間の長さ・使う期間の長さ・基準を"
                "変えて何度も試し、良かった設定を選ぶと、その選び方自体が過剰最適化になります"
            ),
        )
    )
    notes.append(
        NoteOut(
            kind="walkforward_liquidation",
            message=(
                "区切りの最後に株を持っていたら、その日の評価価格で売ったものとして(売りの手数料・スリッページを引いて)、"
                "次の区切りに進みます。実際には同じ向きなら持ち続けられるので、費用を少し多めに引いています。"
                f"最後の区切りの最終日の資産額は清算コスト控除前の値です(清算したあとは {result.metrics.liquidated_equity:,.0f}円)"
            ),
        )
    )
    for w in result.windows:
        if w.choice.pair is None:
            notes.append(
                NoteOut(
                    kind="walkforward_no_choice",
                    message=(
                        f"区切り{w.window.index}では、すべての組み合わせの{OBJECTIVE_LABELS[s.objective]}が算出不可"
                        "(一度も売買しなかった など)だったため、選ばずに現金のままにしました"
                    ),
                )
            )
        elif w.choice.tie_count > 1:
            notes.append(
                NoteOut(
                    kind="walkforward_ties",
                    message=(
                        f"区切り{w.window.index}では、{OBJECTIVE_LABELS[s.objective]}が同じ1位の組み合わせが"
                        f"{w.choice.tie_count}通りあり、組み合わせの順番(短期の短い順 → 長期の短い順)で最初のものを選びました"
                    ),
                )
            )
    unused = unused_out(context.bars, [w.window for w in result.windows], context.end)
    if unused is not None:
        notes.append(
            NoteOut(
                kind="walkforward_unused",
                message=(
                    f"{unused.start_date.isoformat()}〜{unused.end_date.isoformat()}({unused.business_days}営業日)は、"
                    f"使う期間({s.out_of_sample_months}か月)が丸ごと入らないため使っていません"
                ),
            )
        )
    if result.metrics.return_count < context.costs.trading_days_per_year:
        notes.append(
            NoteOut(kind="annualized_reference", message=NOTE_MESSAGES["annualized_reference"])
        )
    if context.market == "DEMO":
        notes.append(NoteOut(kind="demo_data", message=NOTE_MESSAGES["demo_data"]))
    else:
        notes.append(NoteOut(kind="survivorship", message=NOTE_MESSAGES["survivorship"]))
        notes.append(NoteOut(kind="data_license", message=context.data_info.license_note))
    notes.append(
        NoteOut(kind="execution_assumption", message=NOTE_MESSAGES["execution_assumption"])
    )
    notes.append(
        NoteOut(
            kind="benchmark",
            message=(
                "買い持ちは、つないだ期間の最初に売買が成立した日の終値で買うと決め、次に売買が成立した日の始値で買えるだけ買って、"
                "最後まで持った場合です(区切りごとの清算はしません)。配当を含めないので、買い持ちは実際より不利に出ます。"
                "区切りごとの比較は、その使う期間だけの買い持ちと比べています"
            ),
        )
    )
    return notes


def result_out(context: WalkForwardContext, result: WalkForwardResult) -> WalkForwardResultOut:
    bars = context.bars
    windows = [
        WalkForwardWindowOut(
            index=w.window.index,
            requested_in_sample_start=w.window.requested_in_sample_start,
            in_sample=period_out(bars, w.window.in_sample.start, w.window.in_sample.end),
            out_of_sample=period_out(
                bars, w.window.out_of_sample.start, w.window.out_of_sample.end
            ),
            chosen=(
                WindowChoiceOut(short_window=w.choice.pair[0], long_window=w.choice.pair[1])
                if w.choice.pair is not None
                else None
            ),
            in_sample_value=w.choice.value,
            tie_count=w.choice.tie_count,
            starting_cash=w.starting_cash,
            out_of_sample_metrics=metrics_out(w.out_of_sample),
            ended_with_shares=w.ended_with_shares,
            final_equity=w.final_equity,
            liquidated_equity=w.liquidated_equity,
            benchmark_total_return=w.benchmark_total_return if w.benchmark_bought else None,
        )
        for w in result.windows
    ]
    grid, costs, m = context.grid, context.costs, result.metrics
    return WalkForwardResultOut(
        symbol=context.symbol,
        strategy_id=context.strategy_id,
        engine=context.engine,
        grid=SweepGridOut(
            short_min=grid.short_min,
            short_max=grid.short_max,
            short_step=grid.short_step,
            long_min=grid.long_min,
            long_max=grid.long_max,
            long_step=grid.long_step,
            short_values=grid.short_values(),
            long_values=grid.long_values(),
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
        objective=context.settings.objective,  # type: ignore[arg-type]
        in_sample_months=context.settings.in_sample_months,
        out_of_sample_months=context.settings.out_of_sample_months,
        count=len(result.pairs),
        runs=len(result.pairs) * len(result.windows) + len(result.windows),
        windows=windows,
        daily=[
            WalkForwardDayOut(date=d.date, equity=d.equity, benchmark_equity=d.benchmark_equity)
            for d in result.daily
        ],
        metrics=WalkForwardMetricsOut(
            total_return=m.total_return,
            annualized_return=m.annualized_return,
            max_drawdown=m.max_drawdown,
            sharpe_ratio=m.sharpe_ratio,
            return_count=m.return_count,
            final_equity=m.final_equity,
            liquidated_equity=m.liquidated_equity,
        ),
        benchmark=benchmark_out(result.benchmark),
        choice_changes=result.choice_changes,
        compared_windows=result.compared_windows,
        beats_benchmark=result.beats_benchmark,
        unused=unused_out(bars, [w.window for w in result.windows], context.end),
        notes=notes_out(context, result),
        data_info=data_info_out(context.data_info),
    )

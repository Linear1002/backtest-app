"""ウォークフォワード分析のリファレンス実装(docs/walkforward.md)。

区切りごとに、直前の「選ぶ期間」だけで総当たりの1位を選び、次の「使う期間」だけその日数で売買する。使う期間をつなげた成績が、
「総当たりで1位を選ぶ」という選び方そのものの成績になる。

読んで正しいと分かることを優先し、区切りごと・組み合わせごとに順番に計算する(速さは API のジョブが受け持つ)。
- 選ぶ期間の1つの組み合わせの計算は、総当たりと同じ run_pair(= 1組のバックテスト)
- 使う期間は run_backtest、比べる相手は run_buy_and_hold(docs/benchmark.md)
- API のジョブは、選ぶ期間の計算(run_pairs)をプロセスで並列にし、そのあとの assemble_walkforward はこのファイルの関数を使う
"""

from __future__ import annotations

import calendar
import dataclasses
import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass

from engine.reference.backtest import (
    MAX_INITIAL_CASH,
    MIN_PERIOD_BUSINESS_DAYS,
    run_backtest,
    select_load_range,
    validate_order,
    validate_params,
    validate_records,
)
from engine.reference.benchmark import BuyAndHoldResult, run_buy_and_hold
from engine.reference.metrics import compute_metrics
from engine.reference.sweep import (
    Segment,
    SegmentMetrics,
    SweepCosts,
    SweepGrid,
    SweepRow,
    in_sample_start,
    run_pairs,
    segment_metrics,
    validate_grid,
)
from engine.reference.types import Bar, EngineDataError, EngineInputError, MaCrossParams

OBJECTIVES = ("sharpe_ratio", "total_return")  # 2章:最大ドローダウンは選べない
MAX_IN_SAMPLE_MONTHS = 120
MAX_OUT_OF_SAMPLE_MONTHS = 60
DAY = dt.timedelta(days=1)


# --- 入力 ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WalkForwardSettings:
    """区切り方と選び方(2章)。"""

    objective: str = "sharpe_ratio"
    in_sample_months: int = 24
    out_of_sample_months: int = 6


@dataclass(frozen=True)
class Window:
    """1つの区切り(3章)。in_sample は始まりをそろえたあとの選ぶ期間。"""

    index: int  # 1から
    requested_in_sample_start: dt.date  # 暦で決めた選ぶ期間の始まり(そろえる前)
    in_sample: Segment
    out_of_sample: Segment


# --- 出力 ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Choice:
    """選ぶ期間で選んだ組み合わせ(4章)。pair が None なら選ばなかった(すべて算出不可)。"""

    pair: tuple[int, int] | None
    value: float | None  # 選んだ組み合わせの、選ぶ期間の基準の値
    tie_count: int  # 1位と同じ値だった組み合わせの数(選ばなかったときは0)


@dataclass(frozen=True)
class StitchedDay:
    date: dt.date
    equity: float  # つないだ資産額(区切りの最終日は清算したあとの額。5章)
    benchmark_equity: float  # 同じ日の買い持ちの資産額


@dataclass(frozen=True)
class WindowResult:
    window: Window
    choice: Choice
    starting_cash: float  # この使う期間の初期資金(前の区切りの清算したあとの額)
    out_of_sample: SegmentMetrics  # 使う期間の成績(初期資金からの総リターンなど)
    ended_with_shares: bool  # 使う期間の最後に株を持っていたか
    final_equity: float  # 使う期間の最後の資産(清算する前)
    liquidated_equity: float  # 清算したあとの額(5章の式)
    benchmark_total_return: float  # この使う期間だけの買い持ちの総リターン(入力の初期資金で計算)
    benchmark_bought: bool  # その買い持ちが買えたか


@dataclass(frozen=True)
class StitchedMetrics:
    """つないだ成績(docs/mvp.md 5章と同じ定義。勝率・取引回数はない)。"""

    total_return: float
    annualized_return: float | None
    max_drawdown: float
    sharpe_ratio: float | None
    return_count: int
    final_equity: float  # 清算する前
    liquidated_equity: float  # 最後の区切りの最終日に清算したあとの額


@dataclass(frozen=True)
class WalkForwardResult:
    settings: WalkForwardSettings
    pairs: tuple[tuple[int, int], ...]
    windows: tuple[WindowResult, ...]
    daily: tuple[StitchedDay, ...]
    metrics: StitchedMetrics
    benchmark: BuyAndHoldResult  # つないだ期間全体の買い持ち
    choice_changes: int  # 選んだ組み合わせが、前の区切りから変わった回数
    compared_windows: int  # 買い持ちと比べた区切りの数(その使う期間で買い持ちを買えた区切り)
    beats_benchmark: int  # そのうち、使う期間の総リターンが買い持ちを上回った区切りの数


# --- 区切り方(3章) ------------------------------------------------------------------


class WindowError(EngineInputError):
    """区切りの誤り(7章の5・8)。field は API が誤りを出す入力欄(windows・in_sample_months・out_of_sample_months)。"""

    def __init__(self, message: str, field: str) -> None:
        super().__init__(message)
        self.field = field


def add_months(day: dt.date, months: int) -> dt.date:
    """day の年月に months か月を足す。日はそのままで、その月にない日なら月末にする(1月31日 + 1か月 = 2月28日)。"""
    total = day.year * 12 + (day.month - 1) + months
    year, month0 = divmod(total, 12)
    last = calendar.monthrange(year, month0 + 1)[1]
    return dt.date(year, month0 + 1, min(day.day, last))


def calendar_windows(
    start: dt.date, end: dt.date, in_sample_months: int, out_of_sample_months: int
) -> list[tuple[dt.date, dt.date, dt.date, dt.date]]:
    """暦だけで決まる区切り:(選ぶ期間の始まり, 終わり, 使う期間の始まり, 終わり) の一覧。

    すべて start から月を足して決める。使う期間が end までに丸ごと入る区切りだけ。画面も同じ計算をする(lib/walkforward.ts)。
    """
    windows = []
    k = 1
    while True:
        in_start = add_months(start, (k - 1) * out_of_sample_months)
        out_start = add_months(start, in_sample_months + (k - 1) * out_of_sample_months)
        out_end = add_months(start, in_sample_months + k * out_of_sample_months) - DAY
        if out_end > end:
            return windows
        windows.append((in_start, out_start - DAY, out_start, out_end))
        k += 1


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_settings(settings: WalkForwardSettings) -> None:
    """7章の3。"""
    if settings.objective not in OBJECTIVES:
        raise EngineInputError("1位を選ぶ基準は、シャープレシオか総リターンを選んでください")
    months = settings.in_sample_months
    if not _is_int(months) or not 1 <= months <= MAX_IN_SAMPLE_MONTHS:
        raise EngineInputError(
            f"選ぶ期間の長さは1〜{MAX_IN_SAMPLE_MONTHS}か月の整数で入力してください"
        )
    months = settings.out_of_sample_months
    if not _is_int(months) or not 1 <= months <= MAX_OUT_OF_SAMPLE_MONTHS:
        raise EngineInputError(
            f"使う期間の長さは1〜{MAX_OUT_OF_SAMPLE_MONTHS}か月の整数で入力してください"
        )


def _business_days(bars: Sequence[Bar], start: dt.date, end: dt.date) -> int:
    return sum(1 for bar in bars if start <= bar.date <= end)


def no_windows_error(settings: WalkForwardSettings) -> WindowError:
    return WindowError(
        f"期間が短すぎて、選ぶ期間({settings.in_sample_months}か月)と使う期間({settings.out_of_sample_months}か月)を"
        "1回も取れません。期間を広げるか、選ぶ期間・使う期間を短くしてください",
        "windows",
    )


def make_windows(
    bars: Sequence[Bar],
    start: dt.date,
    end: dt.date,
    longest: int,
    settings: WalkForwardSettings,
) -> tuple[Window, ...]:
    """7章の5・8。区切りを作り、選ぶ期間の始まりをそろえ、営業日が3日以上あるかを確かめる。"""
    plan = calendar_windows(start, end, settings.in_sample_months, settings.out_of_sample_months)
    if not plan:
        raise no_windows_error(settings)
    windows = []
    for index, (in_start, in_end, out_start, out_end) in enumerate(plan, start=1):
        aligned = in_sample_start(bars, in_start, longest)
        if (
            aligned is None
            or aligned > in_end
            or _business_days(bars, aligned, in_end) < MIN_PERIOD_BUSINESS_DAYS
        ):
            raise WindowError(
                f"長期の日数(最長{longest}日)のウォームアップに使う日を除くと、区切り{index}の選ぶ期間の営業日が"
                "3日未満になります。長期の日数を短くするか、選ぶ期間を長くしてください",
                "in_sample_months",
            )
        if _business_days(bars, out_start, out_end) < MIN_PERIOD_BUSINESS_DAYS:
            raise WindowError(
                f"区切り{index}の使う期間の営業日が3日未満です。使う期間を長くしてください",
                "out_of_sample_months",
            )
        windows.append(
            Window(
                index=index,
                requested_in_sample_start=in_start,
                in_sample=Segment(f"in_sample_{index}", aligned, in_end),
                out_of_sample=Segment(f"out_of_sample_{index}", out_start, out_end),
            )
        )
    return tuple(windows)


def validate_walkforward(
    bars: Sequence[Bar],
    start: dt.date,
    end: dt.date,
    grid: SweepGrid,
    costs: SweepCosts,
    settings: WalkForwardSettings,
) -> tuple[list[tuple[int, int]], tuple[Window, ...]]:
    """7章の1〜5・7〜9(6 の計算の量は API が確かめる)。誤りがなければ (組み合わせ, 区切り) を返す。"""
    pairs = validate_grid(grid)  # 1
    validate_params(costs.params_for(*pairs[0]))  # 2
    validate_settings(settings)  # 3
    if start > end:  # 4
        raise EngineInputError("開始日は終了日より前の日付にしてください")
    if not calendar_windows(start, end, settings.in_sample_months, settings.out_of_sample_months):
        raise no_windows_error(settings)  # 5
    validate_order(bars)  # 7
    longest = max(long for _, long in pairs)
    windows = make_windows(bars, start, end, longest, settings)  # 8
    # 9:すべての区切り・組み合わせ・買い持ちの読み込む範囲を合わせた範囲
    validate_records(
        select_load_range(bars, windows[0].in_sample.start, windows[-1].out_of_sample.end, longest)
    )
    return pairs, windows


# --- 選び方(4章) ------------------------------------------------------------------


def choose(
    pairs: Sequence[tuple[int, int]], metrics: Sequence[SegmentMetrics], objective: str
) -> Choice:
    """組み合わせの順番に並んだ、1つの選ぶ期間の成績から、基準の値が最も大きい組み合わせを選ぶ。

    同率1位なら組み合わせの順番で最初のもの。すべて算出不可なら選ばない。
    """
    best: int | None = None
    best_value: float | None = None
    ties = 0
    for index, m in enumerate(metrics):
        value = getattr(m, objective)
        if value is None or not math.isfinite(value):
            continue
        if best_value is None or value > best_value:
            best, best_value, ties = index, value, 1
        elif value == best_value:
            ties += 1
    if best is None:
        return Choice(None, None, 0)
    return Choice(tuple(pairs[best]), best_value, ties)  # type: ignore[arg-type]


# --- 使う期間とつなぎ方(5章) ------------------------------------------------------


def liquidated(cash: float, shares: int, price: float | None, params: MaCrossParams) -> float:
    """区切りでの清算:現金 + 株数 × 評価価格 × (1 − スリッページ率) × (1 − 手数料率)。"""
    if shares == 0 or price is None:
        return cash
    return cash + shares * price * (1 - params.slippage_rate) * (1 - params.fee_rate)


def _starting_params(costs: SweepCosts, pair: tuple[int, int], cash: float, index: int):
    if not 1 <= cash <= MAX_INITIAL_CASH:
        raise EngineInputError(
            f"区切り{index}の初期資金(前の区切りの最後の資産 {cash:,.0f}円)が、扱える範囲(1円以上・10億円以下)の外になったため、"
            "計算を続けられません。初期資金を変えてください"
        )
    return dataclasses.replace(costs.params_for(*pair), initial_cash=cash)


def run_window(
    bars: Sequence[Bar],
    window: Window,
    choice: Choice,
    costs: SweepCosts,
    cash: float,
) -> tuple[WindowResult, list[tuple[dt.date, float]]]:
    """1つの区切りの使う期間を計算する。(結果, 日ごとの (日付, 資産額)) を返す。資産額は清算する前。"""
    out = window.out_of_sample
    pair = (
        choice.pair if choice.pair is not None else (1, 2)
    )  # 選ばなかったときは費用・資金を確かめるためだけ
    params = _starting_params(costs, pair, cash, window.index)
    if choice.pair is None:
        # 選ばなかった:売買せず、現金のまま(docs/walkforward.md 4章)
        days = [bar.date for bar in bars if out.start <= bar.date <= out.end]
        equities = [cash] * len(days)
        m = compute_metrics(equities, cash, (), params.trading_days_per_year)
        metrics = SegmentMetrics(
            total_return=m.total_return,
            annualized_return=m.annualized_return,
            max_drawdown=m.max_drawdown,
            sharpe_ratio=m.sharpe_ratio,
            win_rate=None,
            trade_count=0,
            winning_trades=0,
            return_count=m.return_count,
            insufficient_cash_count=0,
            final_equity=cash,
            holding_days=0,
        )
        series = list(zip(days, equities, strict=True))
        final, after, holding = cash, cash, False
    else:
        result = run_backtest(bars, out.start, out.end, params)
        metrics = segment_metrics(result)
        series = [(day.date, day.equity) for day in result.daily]
        last = result.daily[-1]
        final = last.equity
        after = liquidated(last.cash, last.shares, last.valuation_price, params)
        holding = last.shares > 0
    benchmark = run_buy_and_hold(bars, out.start, out.end, costs.params_for(*pair))
    return (
        WindowResult(
            window=window,
            choice=choice,
            starting_cash=cash,
            out_of_sample=metrics,
            ended_with_shares=holding,
            final_equity=final,
            liquidated_equity=after,
            benchmark_total_return=benchmark.metrics.total_return,
            benchmark_bought=benchmark.fill is not None,
        ),
        series,
    )


def assemble_walkforward(
    bars: Sequence[Bar],
    pairs: Sequence[tuple[int, int]],
    windows: Sequence[Window],
    rows: Sequence[SweepRow],
    costs: SweepCosts,
    settings: WalkForwardSettings,
) -> WalkForwardResult:
    """選ぶ期間の計算(rows:組み合わせの順番に、区切りの順番の行)から、選んで、使う期間を計算して、つなぐ。"""
    by_segment: dict[str, list[SegmentMetrics]] = {w.in_sample.name: [] for w in windows}
    for row in rows:
        by_segment[row.segment].append(row.metrics)
    results: list[WindowResult] = []
    stitched: list[tuple[dt.date, float]] = []
    cash = costs.initial_cash
    for position, window in enumerate(windows):
        metrics = by_segment[window.in_sample.name]
        if len(metrics) != len(pairs):
            raise AssertionError("選ぶ期間の行の数が、組み合わせの数と合いません(実装のバグ)")
        choice = choose(pairs, metrics, settings.objective)
        result, series = run_window(bars, window, choice, costs, cash)
        if position < len(windows) - 1:
            # 区切りの最終日は、清算したあとの額にする(次の区切りの初日は、この額から始まる)
            series[-1] = (series[-1][0], result.liquidated_equity)
        stitched.extend(series)
        results.append(result)
        cash = result.liquidated_equity

    first, last = windows[0].out_of_sample, windows[-1].out_of_sample
    benchmark = run_buy_and_hold(bars, first.start, last.end, costs.params_for(*pairs[0]))
    if [d.date for d in benchmark.daily] != [day for day, _ in stitched]:
        raise AssertionError("つないだ期間の営業日が、買い持ちと合いません(実装のバグ)")
    equities = [equity for _, equity in stitched]
    m = compute_metrics(equities, costs.initial_cash, (), costs.trading_days_per_year)
    metrics = StitchedMetrics(
        total_return=m.total_return,
        annualized_return=m.annualized_return,
        max_drawdown=m.max_drawdown,
        sharpe_ratio=m.sharpe_ratio,
        return_count=m.return_count,
        final_equity=equities[-1],
        liquidated_equity=results[-1].liquidated_equity,
    )
    choices = [r.choice.pair for r in results]
    return WalkForwardResult(
        settings=settings,
        pairs=tuple(pairs),
        windows=tuple(results),
        daily=tuple(
            StitchedDay(day, equity, b.equity)
            for (day, equity), b in zip(stitched, benchmark.daily, strict=True)
        ),
        metrics=metrics,
        benchmark=benchmark,
        choice_changes=sum(1 for a, b in zip(choices, choices[1:], strict=False) if a != b),
        # 買い持ちを買えなかった区切りとは比べない(docs/benchmark.md 3章)
        compared_windows=sum(1 for r in results if r.benchmark_bought),
        beats_benchmark=sum(
            1
            for r in results
            if r.benchmark_bought and r.out_of_sample.total_return > r.benchmark_total_return
        ),
    )


def in_sample_rows(
    bars: Sequence[Bar],
    pairs: Sequence[tuple[int, int]],
    windows: Sequence[Window],
    costs: SweepCosts,
) -> tuple[SweepRow, ...]:
    """すべての組み合わせを、すべての区切りの選ぶ期間で計算する(総当たりと同じ run_pairs)。"""
    outcome = run_pairs(bars, [w.in_sample for w in windows], costs, pairs)
    if outcome.error_index is not None:
        error = EngineInputError if outcome.error_kind == "input" else EngineDataError
        raise error(outcome.error_message or "")
    return outcome.rows


def run_walkforward(
    bars: Sequence[Bar],
    start: dt.date,
    end: dt.date,
    grid: SweepGrid,
    costs: SweepCosts,
    settings: WalkForwardSettings,
) -> WalkForwardResult:
    """ウォークフォワード分析を順番に計算する(正解)。"""
    pairs, windows = validate_walkforward(bars, start, end, grid, costs, settings)
    rows = in_sample_rows(bars, pairs, windows, costs)
    return assemble_walkforward(bars, pairs, windows, rows, costs, settings)


__all__ = [
    "OBJECTIVES",
    "Choice",
    "StitchedDay",
    "StitchedMetrics",
    "WalkForwardResult",
    "WalkForwardSettings",
    "Window",
    "WindowError",
    "WindowResult",
    "add_months",
    "assemble_walkforward",
    "calendar_windows",
    "choose",
    "in_sample_rows",
    "liquidated",
    "make_windows",
    "run_walkforward",
    "validate_settings",
    "validate_walkforward",
]

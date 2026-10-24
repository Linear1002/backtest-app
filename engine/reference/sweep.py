"""総当たり(パラメータの探索)のリファレンス実装(docs/sweep.md)。

1つの組み合わせの計算は run_backtest(docs/mvp.md)そのもの。ここで決めるのは、
組み合わせの作り方(2章)・期間の分け方(3章)・チェックの順番(5章)・出力の形(6章)だけ。
速さより、仕様と1対1で読めることを優先している(速くするのは C++ 版・CUDA 版の仕事。docs/gpu-plan.md)。

API は組み合わせをいくつかに分け、run_pairs を別々のプロセスで動かして並列に計算する(backend/sweeps.py)。
分けて計算しても、組み合わせの順番に並べ直せば run_sweep と同じ結果になる。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from engine.reference.backtest import (
    MIN_PERIOD_BUSINESS_DAYS,
    run_backtest,
    select_load_range,
    validate_order,
    validate_params,
    validate_records,
)
from engine.reference.types import (
    MAX_WINDOW,
    TRADING_DAYS_PER_YEAR,
    BacktestResult,
    Bar,
    EngineDataError,
    EngineInputError,
    MaCrossParams,
)

IN_SAMPLE = "in_sample"  # 選ぶ期間
OUT_OF_SAMPLE = "out_of_sample"  # 検証期間

GRID_FIELDS = ("short_min", "short_max", "short_step", "long_min", "long_max", "long_step")


# --- 入力 ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SweepGrid:
    """短期日数 × 長期日数の格子(2章)。"""

    short_min: int
    short_max: int
    short_step: int
    long_min: int
    long_max: int
    long_step: int

    def short_values(self) -> list[int]:
        return list(range(self.short_min, self.short_max + 1, self.short_step))

    def long_values(self) -> list[int]:
        return list(range(self.long_min, self.long_max + 1, self.long_step))

    def pairs(self) -> list[tuple[int, int]]:
        """組み合わせの順番(短期の小さい順、短期が同じなら長期の小さい順)。短期 < 長期 の組だけ。"""
        longs = self.long_values()
        return [(short, long) for short in self.short_values() for long in longs if short < long]


@dataclass(frozen=True)
class SweepCosts:
    """全組み合わせで共通のパラメータ。率はすべて割合(0.1% → 0.001)。"""

    fee_rate: float
    slippage_rate: float
    initial_cash: float
    lot_size: int = 100
    trading_days_per_year: int = TRADING_DAYS_PER_YEAR

    def params_for(self, short_window: int, long_window: int) -> MaCrossParams:
        return MaCrossParams(
            short_window=short_window,
            long_window=long_window,
            fee_rate=self.fee_rate,
            slippage_rate=self.slippage_rate,
            initial_cash=self.initial_cash,
            lot_size=self.lot_size,
            trading_days_per_year=self.trading_days_per_year,
        )


@dataclass(frozen=True)
class Segment:
    """選ぶ期間か検証期間(3章)。start・end は両端を含む日付(休場日でもよい)。"""

    name: str  # IN_SAMPLE / OUT_OF_SAMPLE
    start: dt.date
    end: dt.date


# --- 出力 ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SegmentMetrics:
    """1つの期間の成績(6章)。定義は docs/mvp.md 5章と同じ。None は算出不可・「−」。"""

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


@dataclass(frozen=True)
class SweepRow:
    short_window: int
    long_window: int
    segment: str
    metrics: SegmentMetrics


@dataclass(frozen=True)
class SweepResult:
    grid: SweepGrid
    pairs: tuple[tuple[int, int], ...]
    segments: tuple[Segment, ...]
    rows: tuple[SweepRow, ...]  # 組み合わせの順番に、選ぶ期間 → 検証期間


@dataclass(frozen=True)
class PairsOutcome:
    """run_pairs の結果。誤りがあれば、その組み合わせの番号(pairs の中の位置)と誤り。"""

    rows: tuple[SweepRow, ...]
    error_index: int | None = None
    error_kind: str | None = None  # "input" / "data"
    error_message: str | None = None


# --- チェック(5章) ------------------------------------------------------------------


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_grid(grid: SweepGrid) -> list[tuple[int, int]]:
    """5章の1。誤りがなければ、組み合わせの一覧を返す。"""
    for name in GRID_FIELDS:
        value = getattr(grid, name)
        if not _is_int(value) or value < 1:
            raise EngineInputError("日数と刻みは1以上の整数で入力してください")
        if value > MAX_WINDOW:
            raise EngineInputError(f"日数と刻みは{MAX_WINDOW}以下で入力してください")
    if grid.short_min > grid.short_max:
        raise EngineInputError("短期の日数の範囲は、最小を最大以下にしてください")
    if grid.long_min > grid.long_max:
        raise EngineInputError("長期の日数の範囲は、最小を最大以下にしてください")
    pairs = grid.pairs()
    if not pairs:
        raise EngineInputError(
            "短期の日数が長期の日数より小さい組み合わせがありません。範囲を見直してください"
        )
    return pairs


def split_segments(
    start: dt.date, end: dt.date, holdout_start: dt.date | None
) -> tuple[Segment, ...]:
    """5章の3。期間を、選ぶ期間と検証期間に分ける(3章)。"""
    if start > end:
        raise EngineInputError("開始日は終了日より前の日付にしてください")
    if holdout_start is None:
        return (Segment(IN_SAMPLE, start, end),)
    if not start < holdout_start <= end:
        raise EngineInputError(
            "検証期間の開始日は、期間の開始日より後、終了日以前の日付にしてください"
        )
    return (
        Segment(IN_SAMPLE, start, holdout_start - dt.timedelta(days=1)),
        Segment(OUT_OF_SAMPLE, holdout_start, end),
    )


def _business_days(bars: Sequence[Bar], segment: Segment) -> int:
    return sum(1 for bar in bars if segment.start <= bar.date <= segment.end)


def validate_sweep(
    bars: Sequence[Bar],
    start: dt.date,
    end: dt.date,
    grid: SweepGrid,
    costs: SweepCosts,
    holdout_start: dt.date | None = None,
) -> tuple[list[tuple[int, int]], tuple[Segment, ...]]:
    """5章の1〜6。誤りがなければ (組み合わせの一覧, 期間の一覧) を返す。"""
    pairs = validate_grid(grid)  # 1
    validate_params(
        costs.params_for(*pairs[0])
    )  # 2(日数は正しい組なので、費用・資金だけが確かめられる)
    segments = split_segments(start, end, holdout_start)  # 3
    validate_order(bars)  # 4
    for segment in segments:  # 5
        if _business_days(bars, segment) >= MIN_PERIOD_BUSINESS_DAYS:
            continue
        if holdout_start is None:
            raise EngineInputError("期間が短すぎます。営業日が3日以上になるように指定してください")
        if segment.name == IN_SAMPLE:
            raise EngineInputError(
                "選ぶ期間(検証期間より前)の営業日が3日未満です。検証期間の開始日を遅くしてください"
            )
        raise EngineInputError("検証期間の営業日が3日未満です。検証期間の開始日を早くしてください")
    # 6:すべての組み合わせの読み込む範囲を合わせた範囲 = いちばん長い長期日数で start〜end を読む範囲
    longest = max(long for _, long in pairs)
    validate_records(select_load_range(bars, start, end, longest))
    return pairs, segments


# --- 計算 ---------------------------------------------------------------------------


def segment_metrics(result: BacktestResult) -> SegmentMetrics:
    m = result.metrics
    return SegmentMetrics(
        total_return=m.total_return,
        annualized_return=m.annualized_return,
        max_drawdown=m.max_drawdown,
        sharpe_ratio=m.sharpe_ratio,
        win_rate=m.win_rate,
        trade_count=m.trade_count,
        winning_trades=m.winning_trades,
        return_count=m.return_count,
        insufficient_cash_count=result.insufficient_cash_count,
        final_equity=result.final_equity,
    )


def run_pair(
    bars: Sequence[Bar],
    segments: Sequence[Segment],
    costs: SweepCosts,
    short_window: int,
    long_window: int,
) -> list[SweepRow]:
    """1つの組み合わせを、期間ごとに通常のバックテストとして計算する(4章)。"""
    params = costs.params_for(short_window, long_window)
    return [
        SweepRow(
            short_window,
            long_window,
            segment.name,
            segment_metrics(run_backtest(bars, segment.start, segment.end, params)),
        )
        for segment in segments
    ]


def run_pairs(
    bars: Sequence[Bar],
    segments: Sequence[Segment],
    costs: SweepCosts,
    pairs: Sequence[tuple[int, int]],
    first_index: int = 0,
) -> PairsOutcome:
    """組み合わせの一部を順番に計算する(API が別のプロセスで動かす単位)。

    誤り(5章の7)が出たら、そこで止めて、その組み合わせの番号(first_index から数えた位置)を返す。
    validate_sweep を通したあとに呼ぶ前提。
    """
    rows: list[SweepRow] = []
    for offset, (short, long) in enumerate(pairs):
        try:
            rows.extend(run_pair(bars, segments, costs, short, long))
        except EngineInputError as error:
            return PairsOutcome(tuple(rows), first_index + offset, "input", str(error))
        except EngineDataError as error:
            return PairsOutcome(tuple(rows), first_index + offset, "data", str(error))
    return PairsOutcome(tuple(rows))


def run_sweep(
    bars: Sequence[Bar],
    start: dt.date,
    end: dt.date,
    grid: SweepGrid,
    costs: SweepCosts,
    holdout_start: dt.date | None = None,
) -> SweepResult:
    """総当たりの全体(docs/sweep.md)。誤りは EngineInputError / EngineDataError で投げる。"""
    pairs, segments = validate_sweep(bars, start, end, grid, costs, holdout_start)
    rows: list[SweepRow] = []
    for short, long in pairs:  # 7:組み合わせの順番に計算し、誤りが出たらそこで止まる
        rows.extend(run_pair(bars, segments, costs, short, long))
    return SweepResult(grid, tuple(pairs), segments, tuple(rows))

"""総当たりの並べ方とまとめ(docs/sweep.md 7章)。エンジンではなく API が行う。

すべて純粋な関数(入力 → 出力)なので、tests/python/test_sweep_summary.py でそのまま確かめられる。
順位は選ぶ期間(インサンプル)の成績だけで決める。検証期間(アウトオブサンプル)の値は、選んだあとに確かめるためだけに使う。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from engine.reference.sweep import SegmentMetrics

Objective = Literal["sharpe_ratio", "total_return", "max_drawdown"]

# よい順:大きいほどよい(True)か、小さいほどよい(False)か
LARGER_IS_BETTER: dict[str, bool] = {
    "sharpe_ratio": True,
    "total_return": True,
    "max_drawdown": False,
}
OBJECTIVES: tuple[Objective, ...] = ("sharpe_ratio", "total_return", "max_drawdown")


def objective_value(metrics: SegmentMetrics | None, objective: Objective) -> float | None:
    """基準の値。算出不可(シャープレシオの標準偏差0など)や、期間がないときは None。"""
    if metrics is None:
        return None
    value = getattr(metrics, objective)
    return None if value is None or not math.isfinite(value) else float(value)


def _key(value: float, larger_is_better: bool) -> float:
    return -value if larger_is_better else value


def order_best_first(values: Sequence[float | None], objective: Objective) -> list[int]:
    """よい順に並べた位置の一覧。算出不可(None)は最後。値が同じなら組み合わせの順番(位置の小さい順)。"""
    larger = LARGER_IS_BETTER[objective]
    defined = [i for i, v in enumerate(values) if v is not None]
    undefined = [i for i, v in enumerate(values) if v is None]
    defined.sort(key=lambda i: (_key(values[i], larger), i))  # type: ignore[arg-type]
    return defined + undefined


def competition_rank(
    values: Sequence[float | None], index: int, objective: Objective
) -> int | None:
    """index の組み合わせの順位 = 1 + それより良い値の組み合わせの数。値が None なら順位なし。"""
    target = values[index]
    if target is None:
        return None
    larger = LARGER_IS_BETTER[objective]
    better = sum(1 for v in values if v is not None and _key(v, larger) < _key(target, larger))
    return 1 + better


def average_ranks(values: Sequence[float]) -> list[float]:
    """小さい順の順位(1 から)。同じ値には、その値が占める順位の平均を付ける。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        average = (start + end) / 2 + 1  # 位置 start..end(0から)の順位の平均
        for k in range(start, end + 1):
            ranks[order[k]] = average
        start = end + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """スピアマンの順位相関(同じ値は平均の順位)。3組未満か、どちらかの値がすべて同じなら None。"""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = average_ranks(xs), average_ranks(ys)
    n = len(rx)
    mean_x = sum(rx) / n
    mean_y = sum(ry) / n
    sxy = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry, strict=True))
    sxx = sum((a - mean_x) ** 2 for a in rx)
    syy = sum((b - mean_y) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


@dataclass(frozen=True)
class Ranking:
    """1つの基準で並べた結果(docs/sweep.md 7章のまとめ)。位置は combos の中の位置。"""

    objective: Objective
    order: tuple[int, ...]  # よい順(選ぶ期間)
    best_index: int | None  # 選ぶ期間の1位(値がある組み合わせがなければ None)
    best_tie_count: int  # 1位と同じ値の組み合わせの数(2以上なら1位は決まらない)
    best_out_of_sample_rank: int | None  # 1位の、検証期間での順位(同率1位なら None)
    in_sample_ranked: int  # 選ぶ期間の値がある組み合わせの数
    out_of_sample_ranked: int  # 検証期間の値がある組み合わせの数
    rank_correlation: float | None  # 選ぶ期間と検証期間の順位相関
    correlation_pairs: int  # 相関に使った組み合わせの数
    neighbors_mean: float | None  # 1位のとなりの、選ぶ期間の値の平均
    neighbors_count: int


def neighbors(
    pairs: Sequence[tuple[int, int]],
    short_values: Sequence[int],
    long_values: Sequence[int],
    index: int,
) -> list[int]:
    """格子で index の組み合わせのとなり(短期・長期それぞれ1刻み前後。最大8つ)にある組み合わせの位置。"""
    position = {pair: i for i, pair in enumerate(pairs)}
    short, long = pairs[index]
    si, li = short_values.index(short), long_values.index(long)
    found = []
    for ds in (-1, 0, 1):
        for dl in (-1, 0, 1):
            if ds == 0 and dl == 0:
                continue
            s, l_ = si + ds, li + dl
            if 0 <= s < len(short_values) and 0 <= l_ < len(long_values):
                neighbor = position.get((short_values[s], long_values[l_]))
                if neighbor is not None:
                    found.append(neighbor)
    return sorted(found)


def rank(
    pairs: Sequence[tuple[int, int]],
    short_values: Sequence[int],
    long_values: Sequence[int],
    in_sample: Sequence[SegmentMetrics],
    out_of_sample: Sequence[SegmentMetrics] | None,
    objective: Objective,
) -> Ranking:
    """1つの基準で、並べ方とまとめを作る。in_sample・out_of_sample は pairs と同じ順番。"""
    is_values = [objective_value(m, objective) for m in in_sample]
    oos_values = (
        [objective_value(m, objective) for m in out_of_sample]
        if out_of_sample is not None
        else [None] * len(pairs)
    )
    order = order_best_first(is_values, objective)
    best = order[0] if order and is_values[order[0]] is not None else None
    # 1位と同じ値の組み合わせ(同率1位)。全部が一度も株を持たなかったときなど、1位は1つに決まらない
    tie_count = (
        sum(1 for v in is_values if v is not None and v == is_values[best])
        if best is not None
        else 0
    )
    unique_best = best if tie_count == 1 else None

    both = [i for i in range(len(pairs)) if is_values[i] is not None and oos_values[i] is not None]
    correlation = spearman(
        [is_values[i] for i in both],  # type: ignore[misc]
        [oos_values[i] for i in both],  # type: ignore[misc]
    )

    neighbors_mean: float | None = None
    neighbors_count = 0
    if unique_best is not None:
        around = [
            is_values[i]
            for i in neighbors(pairs, short_values, long_values, unique_best)
            if is_values[i] is not None
        ]
        neighbors_count = len(around)
        if around:
            neighbors_mean = sum(around) / len(around)  # type: ignore[arg-type]

    return Ranking(
        objective=objective,
        order=tuple(order),
        best_index=best,
        best_tie_count=tie_count,
        best_out_of_sample_rank=(
            competition_rank(oos_values, unique_best, objective)
            if unique_best is not None
            else None
        ),
        in_sample_ranked=sum(1 for v in is_values if v is not None),
        out_of_sample_ranked=sum(1 for v in oos_values if v is not None),
        rank_correlation=correlation,
        correlation_pairs=len(both),
        neighbors_mean=neighbors_mean,
        neighbors_count=neighbors_count,
    )

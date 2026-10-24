"""総当たりの並べ方とまとめ(backend/sweep_summary.py、docs/sweep.md 7章)のテスト。"""

from __future__ import annotations

import math

import pytest

from backend.sweep_summary import (
    average_ranks,
    competition_rank,
    neighbors,
    order_best_first,
    rank,
    spearman,
)
from engine.reference.sweep import SegmentMetrics, SweepGrid


def metrics(sharpe: float | None, total: float = 0.0, drawdown: float = 0.1) -> SegmentMetrics:
    return SegmentMetrics(
        total_return=total,
        annualized_return=None,
        max_drawdown=drawdown,
        sharpe_ratio=sharpe,
        win_rate=None,
        trade_count=0,
        winning_trades=0,
        return_count=10,
        insufficient_cash_count=0,
        final_equity=1.0,
    )


def test_order_best_first_puts_undefined_last_and_keeps_combo_order_on_ties() -> None:
    values = [0.5, None, 1.0, 0.5, -0.2]
    assert order_best_first(values, "sharpe_ratio") == [2, 0, 3, 4, 1]
    # 最大ドローダウンは小さいほどよい
    assert order_best_first([0.3, 0.1, None, 0.1], "max_drawdown") == [1, 3, 0, 2]


def test_competition_rank() -> None:
    values = [0.5, 1.0, 0.5, None, 2.0]
    assert competition_rank(values, 4, "sharpe_ratio") == 1
    assert competition_rank(values, 1, "sharpe_ratio") == 2
    assert competition_rank(values, 0, "sharpe_ratio") == 3  # 同じ値どうしは同じ順位
    assert competition_rank(values, 2, "sharpe_ratio") == 3
    assert competition_rank(values, 3, "sharpe_ratio") is None


def test_average_ranks_and_spearman() -> None:
    assert average_ranks([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    # 同じ値があるときは平均の順位で、ピアソンの相関を計算する
    expected = 0.9486832980505138  # 順位 [1,2,3,4] と [1,2.5,2.5,4] の相関
    assert spearman([1, 2, 3, 4], [5, 7, 7, 9]) == pytest.approx(expected)
    assert spearman([1, 2], [1, 2]) is None  # 3組未満
    assert spearman([1, 1, 1], [1, 2, 3]) is None  # 片方がすべて同じ


def test_neighbors_on_the_grid() -> None:
    grid = SweepGrid(2, 6, 2, 4, 8, 2)  # 短期 2,4,6 × 長期 4,6,8(短期 < 長期のみ)
    pairs = grid.pairs()
    assert pairs == [(2, 4), (2, 6), (2, 8), (4, 6), (4, 8), (6, 8)]
    sv, lv = grid.short_values(), grid.long_values()
    # (4,6) のとなり:(2,4),(2,6),(2,8),(4,8),(6,8)。(4,4)(6,4)(6,6) は短期 ≥ 長期で組み合わせがない
    assert [pairs[i] for i in neighbors(pairs, sv, lv, pairs.index((4, 6)))] == [
        (2, 4),
        (2, 6),
        (2, 8),
        (4, 8),
        (6, 8),
    ]
    assert [pairs[i] for i in neighbors(pairs, sv, lv, pairs.index((2, 4)))] == [(2, 6), (4, 6)]


def test_rank_summary() -> None:
    grid = SweepGrid(2, 6, 2, 4, 8, 2)
    pairs = grid.pairs()
    is_sharpe = [0.2, 1.5, 0.4, None, 0.9, 0.1]
    oos_sharpe = [0.3, -0.2, 0.5, 0.1, 0.0, None]
    r = rank(
        pairs,
        grid.short_values(),
        grid.long_values(),
        [metrics(v) for v in is_sharpe],
        [metrics(v) for v in oos_sharpe],
        "sharpe_ratio",
    )
    assert r.order == (1, 4, 2, 0, 5, 3)
    assert r.best_index == 1  # (2,6)
    # 検証期間で (2,6) の -0.2 より良いのは 0.3・0.5・0.1・0.0 の4つ → 5位
    assert r.best_out_of_sample_rank == 5
    assert r.out_of_sample_ranked == 5
    # 両方の値がある組み合わせ:位置 0,1,2,4
    assert r.correlation_pairs == 4
    assert r.rank_correlation == pytest.approx(
        spearman([0.2, 1.5, 0.4, 0.9], [0.3, -0.2, 0.5, 0.0])
    )
    # (2,6) のとなり:(2,4)=0.2, (2,8)=0.4, (4,6)=None, (4,8)=0.9 → 値のある3つの平均
    assert r.neighbors_count == 3
    assert r.neighbors_mean == pytest.approx((0.2 + 0.4 + 0.9) / 3)


def test_rank_without_holdout_and_with_no_defined_values() -> None:
    grid = SweepGrid(1, 1, 1, 2, 3, 1)
    pairs = grid.pairs()
    r = rank(
        pairs, grid.short_values(), grid.long_values(), [metrics(None)] * 2, None, "sharpe_ratio"
    )
    assert r.best_index is None and r.best_out_of_sample_rank is None
    assert r.rank_correlation is None and r.neighbors_mean is None
    assert r.out_of_sample_ranked == 0
    # 総リターンはいつも値があるので1位が決まる
    r2 = rank(
        pairs,
        grid.short_values(),
        grid.long_values(),
        [metrics(None, total=0.1), metrics(None, total=0.3)],
        None,
        "total_return",
    )
    assert r2.best_index == 1


def test_nonfinite_values_are_treated_as_undefined() -> None:
    grid = SweepGrid(1, 1, 1, 2, 3, 1)
    r = rank(
        grid.pairs(),
        grid.short_values(),
        grid.long_values(),
        [metrics(math.inf), metrics(0.5)],
        None,
        "sharpe_ratio",
    )
    assert r.order == (1, 0)

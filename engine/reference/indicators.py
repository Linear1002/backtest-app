"""時点 t 基準の調整済み終値・単純移動平均・クロス判定の値 D(t)(docs/mvp.md 2.2、2.3)。

ここは C++ 版と「完全に一致」させる部分(シグナルの日付)に直結するので、計算の順番まで仕様どおりにしている。
- CumAdj は t から過去へ向かって1つずつ掛ける
- P_t(s) は C(s) × CumAdj_t(s) を t ごとに計算し直す(前の日の結果を使い回さない)
- 和は古い日から新しい日の順に1つずつ足す(sum() や numpy は使わない)
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from engine.reference.types import Bar


def cumulative_adjustments(bars: Sequence[Bar], t: int, oldest: int) -> list[float]:
    """CumAdj_t(s) を s = oldest..t について返す(戻り値の添字は s - oldest)。

    CumAdj_t(t) = 1
    CumAdj_t(s) = CumAdj_t(s+1) × AdjFactor(s+1)   (s+1 は s の次の営業日。売買不成立の日も含む)
    """
    cum = [0.0] * (t - oldest + 1)
    cum[t - oldest] = 1.0
    for s in range(t - 1, oldest - 1, -1):
        factor = bars[s + 1].adj_factor
        assert factor is not None  # 事前チェック済み(validate_records)
        cum[s - oldest] = cum[s + 1 - oldest] * factor
    return cum


@dataclass(frozen=True)
class CrossState:
    """有効日 t における移動平均の和と D(t)。未定義の値は None。"""

    index: int  # bars の中での位置
    short_sum: float | None  # S_short(t)
    long_sum: float | None  # S_long(t)
    d: float | None  # D(t) = S_short(t) × long_window − S_long(t) × short_window


def compute_cross_states(
    bars: Sequence[Bar], short_window: int, long_window: int
) -> dict[int, CrossState]:
    """すべての有効日について CrossState を計算する。キーは bars の中での位置。"""
    valid = [i for i, bar in enumerate(bars) if bar.is_valid]
    states: dict[int, CrossState] = {}
    for k, t in enumerate(valid):
        available = k + 1  # t 以前の有効日の数
        if available < short_window:
            states[t] = CrossState(t, None, None, None)
            continue
        longest = long_window if available >= long_window else short_window
        oldest = valid[k - longest + 1]
        cum = cumulative_adjustments(bars, t, oldest)

        def window_sum(window: int, k: int = k, oldest: int = oldest, cum: list[float] = cum):
            total = 0.0
            for s in valid[k - window + 1 : k + 1]:  # 古い日から新しい日の順
                close = bars[s].close
                assert close is not None
                total = total + close * cum[s - oldest]  # P_t(s) = C(s) × CumAdj_t(s)
            return total

        short_sum = window_sum(short_window)
        long_sum = window_sum(long_window) if available >= long_window else None
        d = None if long_sum is None else short_sum * long_window - long_sum * short_window
        states[t] = CrossState(t, short_sum, long_sum, d)
    return states


def detect_cross(d_prev: float, d_now: float) -> str | None:
    """2.3 の表。上抜けなら "buy"、下抜けなら "sell"、どちらでもなければ None。"""
    if d_prev <= 0 and d_now > 0:
        return "buy"
    if d_prev >= 0 and d_now < 0:
        return "sell"
    return None

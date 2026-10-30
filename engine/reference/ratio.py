"""調整係数(小数)から分割・併合の比率を分数 p/q に戻す(docs/mvp.md 2.8)。

AdjFactor は 1:3 の分割で 0.333333 のような近似値になる。そのまま割り算して切り捨てると株数が1株ずれることがあるので、
比率を分数に戻してから、株数は整数だけで計算する。
"""

from __future__ import annotations

import math

from engine.reference.types import EngineDataError

MAX_DENOMINATOR = 1000
MAX_RELATIVE_ERROR = 1e-4


def round_half_up(x: float) -> int:
    """0.5 を切り上げる丸め(floor(x + 0.5))。

    Python の round() は 0.5 を偶数に丸め(2.5 → 2)、C++ の std::round() は 0 から遠い方に丸める(2.5 → 3)。
    言語で結果が変わらないように、仕様では floor(x + 0.5) に決めている。
    """
    return math.floor(x + 0.5)


def recover_split_ratio(adj_factor: float) -> tuple[int, int]:
    """持ち株数の倍率 1 / adj_factor に最も近い分数 p/q(q ≤ 1000)を返す。

    q = 1, 2, …, 1000 のそれぞれについて p = floor(ratio × q + 0.5) とし、|p/q − ratio| が最小のものを選ぶ。
    同じ誤差なら q が小さいほう(先に見つかったほう)を残す。
    """
    if not adj_factor > 0 or not math.isfinite(adj_factor):
        raise EngineDataError(f"調整係数が正しくありません: {adj_factor}")
    ratio = 1.0 / adj_factor
    best_p, best_q, best_error = 0, 1, math.inf
    for q in range(1, MAX_DENOMINATOR + 1):
        p = round_half_up(ratio * q)
        error = abs(p / q - ratio)
        if error < best_error:
            best_p, best_q, best_error = p, q, error
    if best_p <= 0 or best_error / ratio > MAX_RELATIVE_ERROR:
        raise EngineDataError(f"調整係数 {adj_factor} を分数に戻せませんでした(想定外の係数です)")
    return best_p, best_q

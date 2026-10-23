"""成績表の指標(docs/mvp.md 5章)。

和はすべて古い日から順に1つずつ足す(C++ 版と結果をそろえるため)。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from engine.reference.types import TRADING_DAYS_PER_YEAR, EngineDataError, Metrics, Trade


def daily_returns(equities: Sequence[float]) -> list[float]:
    """r(t) = equity(t) / equity(t-1) − 1(t = 1 … N)。"""
    returns = []
    for previous, current in zip(equities, equities[1:], strict=False):
        if previous == 0:
            # 仕様どおりなら起きない(初期資金は1円以上、価格は正、現金は負にならない)。念のための防御
            raise EngineDataError("資産額が0になったため、日次リターンを計算できません")
        returns.append(current / previous - 1)
    return returns


def annualized_return(
    growth: float, n: int, trading_days_per_year: int = TRADING_DAYS_PER_YEAR
) -> float | None:
    """(equity(N) / 初期資金)^(年間営業日数 / N) − 1。有限の値にならないときは None(算出不可)。"""
    try:
        value = growth ** (trading_days_per_year / n) - 1
    except OverflowError:
        return None
    return value if math.isfinite(value) else None


def max_drawdown(equities: Sequence[float]) -> float:
    """max over t of (1 − equity(t) / max_{s≤t} equity(s))。0以上の割合。"""
    peak = equities[0]
    worst = 0.0
    for equity in equities:
        if equity > peak:
            peak = equity
        drawdown = 1 - equity / peak
        if drawdown > worst:
            worst = drawdown
    return worst


def sharpe_ratio(
    returns: Sequence[float], trading_days_per_year: int = TRADING_DAYS_PER_YEAR
) -> float | None:
    """mean(r) / std(r) × √年間営業日数。std は標本標準偏差(ddof=1)、無リスク金利は0。std = 0 なら None。"""
    n = len(returns)
    if n < 2:
        return None
    total = 0.0
    for r in returns:
        total = total + r
    mean = total / n
    squares = 0.0
    for r in returns:
        squares = squares + (r - mean) * (r - mean)
    std = math.sqrt(squares / (n - 1))
    if std == 0:
        return None
    return mean / std * math.sqrt(trading_days_per_year)


def compute_metrics(
    equities: Sequence[float],
    initial_cash: float,
    trades: Sequence[Trade],
    trading_days_per_year: int = TRADING_DAYS_PER_YEAR,
) -> Metrics:
    n = len(equities) - 1
    returns = daily_returns(equities)
    growth = equities[-1] / initial_cash
    closed = [trade for trade in trades if trade.pnl is not None]
    wins = sum(1 for trade in closed if trade.pnl is not None and trade.pnl > 0)
    return Metrics(
        total_return=growth - 1,
        annualized_return=annualized_return(growth, n, trading_days_per_year),
        max_drawdown=max_drawdown(equities),
        sharpe_ratio=sharpe_ratio(returns, trading_days_per_year),
        win_rate=wins / len(closed) if closed else None,
        trade_count=len(closed),
        winning_trades=wins,
        return_count=n,
    )

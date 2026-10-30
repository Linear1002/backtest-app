"""C++ 版とやり取りするときの「結果の形」(docs/cpp/contract.md)。

C++ 版は、pybind11 から呼ばれたときにこの形の dict を返す。CSV で答え合わせするときも、この dict の各リストが
1つの CSV ファイルになる。リファレンス実装の結果もこの形に変換できるので、両者を同じ方法で比べられる。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from engine.reference.types import BacktestResult

# どの項目を「完全に一致」させ、どれを「許容誤差内」で比べるか(docs/mvp.md 6章)
EXACT_FIELDS = {
    "daily": ("date", "shares"),
    "signals": ("date", "side", "action"),
    "fills": ("date", "signal_date", "side", "shares"),
    "skipped_orders": ("date", "signal_date"),
    "events": ("date", "ex_rt", "p", "q", "shares_before", "shares_after", "closed_position"),
    "trades": ("entry_date", "entry_shares", "exit_date", "exit_shares", "closed_by"),
    "warmup": ("first_date", "last_date", "valid_days", "sufficient", "signals_unavailable_until"),
    "metrics": ("trade_count", "winning_trades", "return_count", "win_rate"),
}


def _iso(day: dt.date | None) -> str | None:
    return None if day is None else day.isoformat()


def to_contract_dict(result: BacktestResult) -> dict[str, Any]:
    m = result.metrics
    w = result.warmup
    return {
        "daily": [
            {
                "date": r.date.isoformat(),
                "close": r.close,
                "short_ma": r.short_ma,
                "long_ma": r.long_ma,
                "cash": r.cash,
                "shares": r.shares,
                "valuation_price": r.valuation_price,
                "equity": r.equity,
            }
            for r in result.daily
        ],
        "signals": [
            {"date": s.date.isoformat(), "side": s.side, "action": s.action} for s in result.signals
        ],
        "fills": [
            {
                "date": f.date.isoformat(),
                "signal_date": f.signal_date.isoformat(),
                "side": f.side,
                "open_price": f.open_price,
                "fill_price": f.fill_price,
                "shares": f.shares,
                "notional": f.notional,
                "fee": f.fee,
                "cash_after": f.cash_after,
            }
            for f in result.fills
        ],
        "skipped_orders": [
            {
                "date": s.date.isoformat(),
                "signal_date": s.signal_date.isoformat(),
                "open_price": s.open_price,
                "fill_price": s.fill_price,
                "cash": s.cash,
            }
            for s in result.skipped_orders
        ],
        "events": [
            {
                "date": e.date.isoformat(),
                "ex_rt": e.ex_rt,
                "adj_factor": e.adj_factor,
                "p": e.ratio_numerator,
                "q": e.ratio_denominator,
                "shares_before": e.shares_before,
                "shares_after": e.shares_after,
                "fraction_shares": e.fraction_shares,
                "fraction_cash": e.fraction_cash,
                "closed_position": e.closed_position,
            }
            for e in result.events
        ],
        "trades": [
            {
                "entry_date": t.entry_date.isoformat(),
                "entry_price": t.entry_price,
                "entry_shares": t.entry_shares,
                "buy_cost": t.buy_cost,
                "exit_date": _iso(t.exit_date),
                "exit_price": t.exit_price,
                "exit_shares": t.exit_shares,
                "sell_proceeds": t.sell_proceeds,
                "fraction_cash": t.fraction_cash,
                "pnl": t.pnl,
                "closed_by": t.closed_by,
            }
            for t in result.trades
        ],
        "warmup": {
            "first_date": _iso(w.first_date),
            "last_date": _iso(w.last_date),
            "valid_days": w.valid_days,
            "sufficient": w.sufficient,
            "signals_unavailable_until": _iso(w.signals_unavailable_until),
        },
        "metrics": {
            "total_return": m.total_return,
            "annualized_return": m.annualized_return,
            "max_drawdown": m.max_drawdown,
            "sharpe_ratio": m.sharpe_ratio,
            "win_rate": m.win_rate,
            "trade_count": m.trade_count,
            "winning_trades": m.winning_trades,
            "return_count": m.return_count,
        },
    }

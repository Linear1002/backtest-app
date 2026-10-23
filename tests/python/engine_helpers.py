"""リファレンス実装のテスト用の小さな道具。"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from engine.reference import Bar, MaCrossParams

FIRST_DAY = dt.date(2025, 1, 6)  # 月曜日


def business_dates(count: int, first: dt.date = FIRST_DAY) -> list[dt.date]:
    """first から始まる平日を count 日分。"""
    dates = []
    day = first
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day += dt.timedelta(days=1)
    return dates


def make_bars(
    closes: Sequence[float | None],
    opens: Sequence[float | None] | None = None,
    *,
    adj: dict[int, float] | None = None,
    ex: dict[int, int] | None = None,
    first: dt.date = FIRST_DAY,
) -> list[Bar]:
    """終値の列から日足を作る。None の日は売買不成立(始値も None)。

    adj / ex は {位置: 調整係数} / {位置: 権利落ちの種類}。
    """
    opens = list(opens) if opens is not None else list(closes)
    assert len(opens) == len(closes)
    adj = adj or {}
    ex = ex or {}
    bars = []
    for i, (day, open_, close) in enumerate(
        zip(business_dates(len(closes), first), opens, closes, strict=True)
    ):
        if close is None:
            open_ = None
        high = None if close is None else max(open_, close)
        low = None if close is None else min(open_, close)
        bars.append(
            Bar(
                date=day,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=None if close is None else 1000.0,
                adj_factor=adj.get(i, 1.0),
                ex_rt=ex.get(i),
            )
        )
    return bars


def params(
    short: int = 1,
    long: int = 2,
    *,
    fee: float = 0.0,
    slippage: float = 0.0,
    cash: float = 1_000_000.0,
    lot: int = 100,
) -> MaCrossParams:
    return MaCrossParams(
        short_window=short,
        long_window=long,
        fee_rate=fee,
        slippage_rate=slippage,
        initial_cash=cash,
        lot_size=lot,
    )

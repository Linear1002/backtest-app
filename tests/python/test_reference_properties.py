"""リファレンス実装の性質テスト。乱数で作ったたくさんのケースで、成り立つべき性質を確かめる。

- 先読みしない:t より後のデータを書き換えても、t 以前の判断・約定・資産額は変わらない
- 分割に強い:分割を入れても(係数が2のべき乗なら丸め誤差なしで)シグナルは変わらない
- 単位に依存しない:価格と初期資金を2倍にすると、株数・シグナルは同じで資産額だけ2倍になる
- 別の書き方で計算した移動平均と、クロスの判定が一致する
- 架空データ全銘柄で、お金と株数のつじつまが合う
"""

from __future__ import annotations

import dataclasses
import random

import pytest
from engine_helpers import make_bars, params

from backend.marketdata.synthetic import DEMO_SYMBOLS, generate_bars
from engine.reference import Bar, MaCrossParams, run_backtest

CASES = 150


def random_bars(rng: random.Random, length: int, *, actions: bool = True) -> list[Bar]:
    """整数価格のランダムな日足。売買停止や分割・併合・増資も混ぜる。"""
    closes: list[float | None] = []
    opens: list[float | None] = []
    adj: dict[int, float] = {}
    ex: dict[int, int] = {}
    price = rng.randint(500, 3000)
    for i in range(length):
        if actions and i > 3 and rng.random() < 0.04:
            kind = rng.choice(
                [(1, 0.5), (1, 0.333333), (1, 0.666667), (2, 10.0), (2, 1000.0), (3, 0.97)]
            )
            ex[i], adj[i] = kind
            price = max(1, round(price * kind[1]))
        price = max(1, price + rng.randint(-40, 40))
        if actions and i > 0 and rng.random() < 0.05:
            closes.append(None)
            opens.append(None)
        else:
            closes.append(float(price))
            opens.append(float(max(1, price + rng.randint(-15, 15))))
    if closes[0] is None:
        closes[0], opens[0] = 1000.0, 1000.0
    return make_bars(closes, opens, adj=adj, ex=ex)


def random_params(rng: random.Random) -> MaCrossParams:
    short = rng.randint(1, 4)
    return params(
        short=short,
        long=rng.randint(short + 1, 8),
        fee=rng.choice([0.0, 0.001, 0.003]),
        slippage=rng.choice([0.0, 0.0005, 0.002]),
        cash=rng.choice([5_000.0, 300_000.0, 1_000_000.0]),
        lot=rng.choice([1, 100]),  # 1株単位にすると、併合で端数が出るケースも混ざる
    )


@pytest.mark.parametrize("seed", range(CASES))
def test_future_data_does_not_change_the_past(seed: int) -> None:
    rng = random.Random(seed)
    bars = random_bars(rng, 60)
    p = random_params(rng)
    start = bars[rng.randint(0, 15)].date
    cut = rng.randint(30, 55)
    # cut より後の日足を、まったく別の値に置き換える
    future = random_bars(random.Random(seed + 10_000), 60)
    mutated = bars[: cut + 1] + [
        dataclasses.replace(f, date=b.date)
        for f, b in zip(future[cut + 1 :], bars[cut + 1 :], strict=True)
    ]
    end = bars[-1].date
    a = run_backtest(bars, start, end, p)
    b = run_backtest(mutated, start, end, p)
    cut_date = bars[cut].date

    def upto(items, attr="date"):
        return [x for x in items if getattr(x, attr) <= cut_date]

    assert upto(a.signals) == upto(b.signals)
    assert upto(a.fills) == upto(b.fills)
    assert upto(a.events) == upto(b.events)
    assert upto(a.daily) == upto(b.daily)


@pytest.mark.parametrize("seed", range(CASES))
def test_split_does_not_change_signals(seed: int) -> None:
    rng = random.Random(seed)
    base = random_bars(rng, 50, actions=False)
    j = rng.randint(5, 45)
    factor = rng.choice([0.5, 0.25, 2.0])  # 2のべき乗なら、掛けても丸め誤差が出ない
    ex_rt = 1 if factor < 1 else 2
    split = [
        dataclasses.replace(
            bar,
            open=bar.open * factor if i >= j else bar.open,
            high=bar.high * factor if i >= j else bar.high,
            low=bar.low * factor if i >= j else bar.low,
            close=bar.close * factor if i >= j else bar.close,
            adj_factor=factor if i == j else 1.0,
            ex_rt=ex_rt if i == j else None,
        )
        for i, bar in enumerate(base)
    ]
    p = random_params(rng)
    p = dataclasses.replace(p, initial_cash=1_000_000_000.0)  # どちらも必ず買えるように
    a = run_backtest(base, base[0].date, base[-1].date, p)
    b = run_backtest(split, split[0].date, split[-1].date, p)
    assert [(s.date, s.side) for s in a.signals] == [(s.date, s.side) for s in b.signals]


@pytest.mark.parametrize("seed", range(CASES))
def test_doubling_prices_and_cash_doubles_equity(seed: int) -> None:
    rng = random.Random(seed)
    bars = random_bars(rng, 50)
    p = random_params(rng)

    def double(x: float | None) -> float | None:
        return None if x is None else x * 2

    doubled = [
        dataclasses.replace(
            b, open=double(b.open), high=double(b.high), low=double(b.low), close=double(b.close)
        )
        for b in bars
    ]
    a = run_backtest(bars, bars[0].date, bars[-1].date, p)
    b = run_backtest(
        doubled,
        bars[0].date,
        bars[-1].date,
        dataclasses.replace(p, initial_cash=p.initial_cash * 2),
    )
    assert a.signals == b.signals
    assert [f.shares for f in a.fills] == [f.shares for f in b.fills]
    assert [r.equity * 2 for r in a.daily] == [r.equity for r in b.daily]
    assert a.metrics.trade_count == b.metrics.trade_count


@pytest.mark.parametrize("seed", range(CASES))
def test_signals_match_independent_moving_average(seed: int) -> None:
    """分割なし・整数価格なら、和はすべて正確に計算できる。素朴な書き方の移動平均と比べる。"""
    rng = random.Random(seed)
    bars = random_bars(rng, 70, actions=False)
    p = random_params(rng)
    result = run_backtest(bars, bars[0].date, bars[-1].date, p)

    valid = [b for b in bars if b.close is not None]
    d_values: dict = {}
    for k in range(len(valid)):
        if k + 1 >= p.long_window:
            short_avg = sum(b.close for b in valid[k + 1 - p.short_window : k + 1]) / p.short_window
            long_avg = sum(b.close for b in valid[k + 1 - p.long_window : k + 1]) / p.long_window
            d_values[valid[k].date] = (short_avg > long_avg) - (short_avg < long_avg)
    expected = []
    dates = list(d_values)
    for prev, now in zip(dates, dates[1:], strict=False):
        if d_values[prev] <= 0 < d_values[now]:
            expected.append((now, "buy"))
        elif d_values[prev] >= 0 > d_values[now]:
            expected.append((now, "sell"))
    assert [(s.date, s.side) for s in result.signals] == expected


def demo_bars(code: str) -> list[Bar]:
    return [
        Bar(b.date, b.open, b.high, b.low, b.close, b.volume, b.adj_factor, b.ex_rt)
        for b in generate_bars(code)
    ]


@pytest.mark.parametrize("symbol", DEMO_SYMBOLS, ids=lambda s: s.code)
@pytest.mark.parametrize(("short", "long"), [(5, 25), (13, 26), (25, 75)])
def test_bookkeeping_on_demo_symbols(symbol, short: int, long: int) -> None:
    bars = demo_bars(symbol.code)
    p = params(short=short, long=long, fee=0.001, slippage=0.0005, cash=1_000_000)
    result = run_backtest(bars, bars[0].date, bars[-1].date, p)

    for record in result.daily:
        assert record.cash >= 0
        if record.shares == 0:
            assert record.valuation_price is None and record.equity == record.cash
        else:
            assert record.equity == record.cash + record.shares * record.valuation_price

    sides = [f.side for f in result.fills]
    assert all(a != b for a, b in zip(sides, sides[1:], strict=False))  # 買いと売りが交互
    assert sides[:1] in ([], ["buy"])
    ordered = [s for s in result.signals if s.action == "order"]
    unfilled = len(ordered) - len(result.fills) - result.insufficient_cash_count
    assert unfilled in (0, 1)  # 約定しない注文は最後の1つだけ
    closed = [t for t in result.trades if t.pnl is not None]
    assert result.metrics.trade_count == len(closed)
    assert result.metrics.trade_count == sides.count("sell") + sum(
        e.closed_position for e in result.events
    )
    if symbol.code == "1009":
        assert result.insufficient_cash_count > 0 and result.fills == ()

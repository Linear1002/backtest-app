"""比較の基準:買い持ち(engine/reference/benchmark.py、docs/benchmark.md)のテスト。"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path

import pytest
from engine_helpers import make_bars, params

from backend.api.convert import to_engine_bars
from backend.marketdata.synthetic import generate_bars
from engine.reference import EngineDataError, EngineInputError, MaCrossParams, run_backtest
from engine.reference.benchmark import run_buy_and_hold
from engine.reference.csvio import read_bars_csv, read_params

GOLDEN = Path(__file__).resolve().parent.parent / "golden"


def run(bars, cash: float = 100_000.0, **kwargs):
    return run_buy_and_hold(bars, bars[0].date, bars[-1].date, params(cash=cash, **kwargs))


# --- 手で計算したケース --------------------------------------------------------------


def test_buys_at_the_next_open_after_the_first_close_and_holds() -> None:
    bars = make_bars([100, 101, 102, 103], opens=[100, 101, 102, 103])
    result = run(bars)
    # 1日目の終値で買うと決め、2日目の始値 101 で買う:floor(100000 / 101 / 100) = 9 単元 → 900株
    assert result.signal_date == bars[0].date
    assert result.fill is not None and result.fill.date == bars[1].date
    assert result.fill.shares == 900 and result.fill.fill_price == 101
    assert [d.equity for d in result.daily] == [100_000.0, 100_000.0, 100_900.0, 101_800.0]
    assert [d.shares for d in result.daily] == [0, 900, 900, 900]
    assert result.metrics.total_return == pytest.approx(0.018)
    assert result.open_position_at_end and result.final_equity == 101_800.0


def test_costs_are_the_same_as_the_strategy() -> None:
    bars = make_bars([1000, 1000, 1000], opens=[1000, 1000, 1000])
    result = run(bars, cash=1_000_000.0, fee=0.001, slippage=0.002)
    fill = result.fill
    assert fill is not None
    # 約定価格 1000 × 1.002 = 1002、1株あたり 1002 × 1.001 で、買える株数は 900株(2.7)
    assert fill.fill_price == pytest.approx(1002.0)
    assert fill.shares == 900
    assert fill.cash_after == pytest.approx(1_000_000 - 1002 * 1.001 * 900)
    # 評価は終値(1000)。売らないので、売りの費用は引かない(清算コスト控除前)
    assert result.final_equity == pytest.approx(fill.cash_after + 900 * 1000)


def test_split_and_merger_while_holding() -> None:
    # 2日目に買う(100株)→ 3日目に 3:2 の併合(調整係数 1.5)→ 66株と 2/3株の端数(評価価格で現金に)
    bars = make_bars([100, 100, 150, 151], opens=[100, 100, 150, 151], adj={2: 1.5}, ex={2: 2})
    result = run(bars, cash=10_100.0, lot=100)
    assert result.fill is not None and result.fill.shares == 100
    (event,) = result.events
    assert (event.shares_before, event.shares_after) == (100, 66)
    assert event.fraction_cash == pytest.approx(2 / 3 * 150)
    assert [d.shares for d in result.daily] == [0, 100, 66, 66]


def test_merger_to_zero_keeps_cash_and_does_not_buy_again() -> None:
    # 売買単位1株。5株を持って 10:1 の併合 → 0株と 0.5株の端数。そのあとは現金のまま
    bars = make_bars(
        [10, 10, 100, 101, 102], opens=[10, 10, 100, 101, 102], adj={2: 10.0}, ex={2: 2}
    )
    result = run(bars, cash=50.0, lot=1)
    assert result.fill is not None and result.fill.shares == 5
    (event,) = result.events
    assert event.closed_position and event.shares_after == 0
    assert event.fraction_cash == pytest.approx(0.5 * 100)
    assert [d.shares for d in result.daily] == [0, 5, 0, 0, 0]
    assert result.daily[-1].equity == result.daily[2].equity  # 現金だけ
    assert not result.open_position_at_end


def test_ex_dates_on_the_signal_day_and_the_fill_day_do_not_adjust() -> None:
    """権利落ち日が「買うと決めた日」や「約定日」と重なっても、株数は変えない。

    1日の処理は 分割・併合 → 約定 の順(docs/mvp.md 2.5)。約定日の手順1ではまだ株を持っていないので、
    買った株数は権利落ち後の始値で決まり、その日に調整しない。
    """
    on_fill = make_bars([100, 50, 51, 52], opens=[100, 50, 51, 52], adj={1: 0.5}, ex={1: 1})
    result = run(on_fill)
    assert result.fill is not None and result.fill.date == on_fill[1].date
    assert result.fill.shares == 2000  # 100,000円 ÷ 50円 = 2,000株(調整しない)
    assert result.events == ()
    assert [d.shares for d in result.daily] == [0, 2000, 2000, 2000]
    on_signal = make_bars([100, 101, 102, 103], opens=[100, 101, 102, 103], adj={0: 0.5}, ex={0: 1})
    result = run(on_signal)
    assert result.events == () and result.fill is not None and result.fill.shares == 900


def test_first_days_halted() -> None:
    # 最初の2日は売買不成立:3日目(最初の有効日)の終値で買うと決め、4日目の始値で買う
    bars = make_bars([None, None, 100, 102, 104], opens=[None, None, 100, 102, 104])
    result = run(bars)
    assert result.signal_date == bars[2].date
    assert result.fill is not None and result.fill.date == bars[3].date
    assert [d.equity for d in result.daily][:3] == [100_000.0] * 3


def test_order_carries_over_halted_days() -> None:
    # 買うと決めた次の日が売買不成立なら、その次の有効日の始値で買う(2.5 の手順2)
    bars = make_bars([100, None, 103, 104], opens=[100, None, 103, 104])
    result = run(bars)
    assert result.fill is not None and result.fill.date == bars[2].date


def test_insufficient_cash_skips_and_never_buys() -> None:
    bars = make_bars([1000, 1000, 900, 800], opens=[1000, 1000, 900, 800])
    result = run(bars, cash=50_000.0)  # 100株で10万円かかる
    assert result.fill is None and result.skipped is not None
    assert result.skipped.date == bars[1].date
    assert all(d.equity == 50_000.0 for d in result.daily)  # 安くなっても買い直さない
    assert result.metrics.total_return == 0.0 and result.metrics.sharpe_ratio is None


def test_no_valid_day_after_the_signal_means_no_purchase() -> None:
    bars = make_bars([None, None, 100])
    result = run(bars)
    assert result.signal_date == bars[2].date
    assert result.fill is None and result.skipped is None
    bars = make_bars([None, None, None])
    assert run(bars).signal_date is None


def test_checks_follow_the_same_order_as_the_strategy() -> None:
    bars = make_bars([100, 101])
    with pytest.raises(EngineInputError, match="期間が短すぎます"):
        run(bars)
    with pytest.raises(EngineInputError, match="短期の日数は長期の日数より小さく"):
        run_buy_and_hold(bars, bars[0].date, bars[-1].date, params(short=5, long=5))
    broken = make_bars([100, 101, 102, 103])
    broken[2] = dataclasses.replace(broken[2], adj_factor=None)
    with pytest.raises(EngineDataError, match="調整係数が Null"):
        run(broken)
    # 期間より前の異常は確かめない(ウォームアップがないので、読み込む範囲は期間だけ。docs/benchmark.md 2章の6)
    outside = make_bars([100, 101, 102, 103, 104])
    outside[0] = dataclasses.replace(outside[0], adj_factor=None)
    assert run_buy_and_hold(outside, outside[1].date, outside[-1].date, params()).fill is not None


# --- 移動平均クロスとの一致(docs/benchmark.md 4章) -----------------------------------


def single_buy_runs():
    """移動平均クロスが「1回だけ買って、そのまま期間の最後まで」だった実行。(名前, 日足, 結果, パラメータ)。"""
    runs = []
    manifest = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
    for case in manifest["cases"]:
        if case.get("expected_error"):
            continue
        folder = GOLDEN / "cases" / case["name"] / "input"
        bars = read_bars_csv(folder / "bars.csv")
        start, end, p = read_params(folder / "params.txt")
        runs.append((case["name"], bars, run_backtest(bars, start, end, p), p))
    for code in ("1001", "1003", "1006", "1010", "1012"):
        bars = to_engine_bars(generate_bars(code))
        for short, long in ((40, 250), (30, 200), (60, 300), (100, 400), (5, 200)):
            p = MaCrossParams(short, long, 0.001, 0.0005, 1_000_000.0)
            runs.append(
                (
                    f"DEMO:{code}・{short}/{long}",
                    bars,
                    run_backtest(bars, bars[0].date, bars[-1].date, p),
                    p,
                )
            )
    return [r for r in runs if len(r[2].fills) == 1 and r[2].fills[0].side == "buy"]


MUST_CHECK = {
    "h07_split_while_holding",  # 分割
    "h08_repeated_splits_fraction",  # 端数の出る分割を3回
    "h09_merger_to_zero_cancels_sell",  # 併合で0株
    "h11_halted_ex_date_while_holding",  # 売買不成立の日が権利落ち日
    "h18_zero_pnl_merger_on_halted_day",  # 売買不成立の日の併合で0株
}


def assert_same_from(benchmark, strategy, start, name) -> None:
    """start 以降の日ごとの資産額・株数・現金と、買いの約定が、移動平均クロスとビット単位で同じ。"""
    days = [day for day in strategy.daily if day.date >= start]
    assert [d.date for d in benchmark.daily] == [d.date for d in days], name
    assert [d.equity for d in benchmark.daily] == [d.equity for d in days], name
    assert [d.shares for d in benchmark.daily] == [d.shares for d in days], name
    assert [d.cash for d in benchmark.daily] == [d.cash for d in days], name
    assert benchmark.fill == strategy.fills[0], name
    assert benchmark.events == strategy.events, name


def test_equals_the_strategy_when_it_buys_once_and_holds() -> None:
    """買いのシグナルの日を開始日にした買い持ちは、その日からの資産額が移動平均クロスと完全に同じになる。

    同じ日に、同じ現金で、同じ始値で買い、同じ分割・併合の処理を通るため(同じ関数 fill_buy・apply_split_or_merger)。
    開始日を「シグナルの前の有効日の翌日」(休場日のこともある)にずらしても同じ。その間、移動平均クロスは株も注文も持たないため。
    """
    checked = []
    for name, bars, strategy, p in single_buy_runs():
        signal = strategy.fills[0].signal_date
        if sum(1 for bar in bars if signal <= bar.date <= strategy.end) < 3:
            continue  # 買い持ちの期間が3営業日未満になる(期間の最後のほうで買ったケース)
        assert_same_from(run_buy_and_hold(bars, signal, strategy.end, p), strategy, signal, name)
        before = [bar.date for bar in bars if bar.date < signal and bar.is_valid]
        shifted = before[-1] + dt.timedelta(days=1) if before else signal
        if shifted >= strategy.start:
            assert_same_from(
                run_buy_and_hold(bars, shifted, strategy.end, p), strategy, shifted, name
            )
        checked.append(name)
    assert len(checked) >= 20
    assert MUST_CHECK <= set(
        checked
    )  # 分割・併合・売買不成立の権利落ち日をはさむケースを必ず確かめる

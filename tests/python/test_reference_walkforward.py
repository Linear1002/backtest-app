"""ウォークフォワード分析のリファレンス実装(engine/reference/walkforward.py、docs/walkforward.md)のテスト。"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path

import pytest
from engine_helpers import make_bars

from backend.api.convert import to_engine_bars
from backend.marketdata.synthetic import generate_bars
from engine.reference import EngineDataError, EngineInputError, run_backtest
from engine.reference.backtest import select_load_range
from engine.reference.benchmark import run_buy_and_hold
from engine.reference.sweep import SegmentMetrics, SweepCosts, SweepGrid
from engine.reference.walkforward import (
    Choice,
    WalkForwardSettings,
    add_months,
    calendar_windows,
    choose,
    liquidated,
    make_windows,
    run_walkforward,
    run_window,
    validate_walkforward,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
COSTS = SweepCosts(fee_rate=0.001, slippage_rate=0.0005, initial_cash=1_000_000.0)
GRID = SweepGrid(3, 12, 3, 15, 45, 10)  # 16通り。いちばん長い長期日数は45日
SETTINGS = WalkForwardSettings("sharpe_ratio", 12, 6)


@pytest.fixture(scope="module")
def demo1003():
    from backend.marketdata.models import SymbolId
    from backend.marketdata.synthetic import DemoDataSource

    return to_engine_bars(DemoDataSource().get_daily_bars(SymbolId("DEMO", "1003")))


def day(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


# --- 3章 区切り方 -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        ("2023-01-31", 1, "2023-02-28"),
        ("2024-01-31", 1, "2024-02-29"),  # うるう年
        ("2024-03-31", -1, "2024-02-29"),
        ("2023-12-15", 1, "2024-01-15"),
        ("2023-05-20", 0, "2023-05-20"),
        ("2022-01-04", 24, "2024-01-04"),
    ],
)
def test_add_months(start: str, months: int, expected: str) -> None:
    assert add_months(day(start), months) == day(expected)


CASES = json.loads((FIXTURES / "walkforward_windows.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_calendar_windows_table(case: dict) -> None:
    """画面(lib/walkforward.ts)と同じ表で確かめる。"""
    windows = calendar_windows(
        day(case["start"]), day(case["end"]), case["in_sample_months"], case["out_of_sample_months"]
    )
    assert [[d.isoformat() for d in w] for w in windows] == case["windows"]


def test_windows_are_contiguous_and_in_sample_ends_the_day_before() -> None:
    windows = calendar_windows(day("2020-03-31"), day("2026-12-31"), 18, 3)
    assert len(windows) > 10
    for (in_start, in_end, out_start, out_end), following in zip(
        windows, windows[1:], strict=False
    ):
        assert in_start < in_end < out_start <= out_end
        assert out_start == in_end + dt.timedelta(days=1)
        assert following[2] == out_end + dt.timedelta(days=1)  # 使う期間にすき間も重なりもない


def test_first_in_sample_waits_for_the_longest_warmup(demo1003) -> None:
    """データの初日から始めると、区切り1の選ぶ期間だけ、長期45日のウォームアップがそろう日まで遅れる。"""
    start, end = demo1003[0].date, demo1003[-1].date
    windows = make_windows(demo1003, start, end, 45, SETTINGS)
    first, second = windows[0], windows[1]
    assert first.requested_in_sample_start == start
    valid_before = [b for b in demo1003 if b.date < first.in_sample.start and b.is_valid]
    assert len(valid_before) == 45
    assert (
        second.in_sample.start == second.requested_in_sample_start
    )  # 2つめからは前のデータで足りる
    assert [w.index for w in windows] == list(range(1, len(windows) + 1))


def test_alignment_that_leaves_too_few_days_is_an_input_error() -> None:
    bars = make_bars([100.0 + (i % 5) for i in range(70)])  # 2025-01-06 から70営業日(約3か月)
    settings = WalkForwardSettings("sharpe_ratio", 1, 1)
    with pytest.raises(EngineInputError, match="最長25日.*区切り1の選ぶ期間の営業日が3日未満"):
        make_windows(bars, bars[0].date, bars[-1].date, 25, settings)
    # 長期の日数が短ければ通る
    assert make_windows(bars, bars[0].date, bars[-1].date, 5, settings)


def test_short_out_of_sample_is_an_input_error() -> None:
    bars = make_bars([100.0 + (i % 5) for i in range(70)])  # 2025-01-06〜2025-04-11
    # 2つめの区切りの使う期間(3月6日〜4月5日)のレコードを、4月4日の1日だけにする(データの抜け)
    gap = [b for b in bars if not (day("2025-03-05") <= b.date <= day("2025-04-03"))]
    settings = WalkForwardSettings("sharpe_ratio", 1, 1)
    with pytest.raises(EngineInputError, match="区切り2の使う期間の営業日が3日未満"):
        make_windows(gap, gap[0].date, gap[-1].date, 2, settings)


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (WalkForwardSettings("max_drawdown", 12, 6), "シャープレシオか総リターン"),
        (WalkForwardSettings("sharpe_ratio", 0, 6), "選ぶ期間の長さは1〜120か月"),
        (WalkForwardSettings("sharpe_ratio", 121, 6), "選ぶ期間の長さは1〜120か月"),
        (WalkForwardSettings("sharpe_ratio", True, 6), "選ぶ期間の長さは1〜120か月"),  # type: ignore[arg-type]
        (WalkForwardSettings("sharpe_ratio", 12, 61), "使う期間の長さは1〜60か月"),
    ],
)
def test_settings_errors(demo1003, settings: WalkForwardSettings, message: str) -> None:
    with pytest.raises(EngineInputError, match=message):
        validate_walkforward(demo1003, demo1003[0].date, demo1003[-1].date, GRID, COSTS, settings)


def test_check_order(demo1003) -> None:
    """7章:格子 → 費用 → 設定 → 期間 → 日付の順番 → 区切り(ない・営業日)→ 計算の量 → データの異常。"""
    start, end = demo1003[0].date, demo1003[-1].date
    bad_grid = SweepGrid(10, 5, 1, 20, 30, 10)
    bad_costs = dataclasses.replace(COSTS, fee_rate=0.2)
    bad_settings = WalkForwardSettings("win_rate", 12, 6)
    with pytest.raises(EngineInputError, match="最小を最大以下"):
        validate_walkforward(demo1003, start, end, bad_grid, bad_costs, bad_settings)
    with pytest.raises(EngineInputError, match="10%未満"):
        validate_walkforward(demo1003, start, end, GRID, bad_costs, bad_settings)
    with pytest.raises(EngineInputError, match="シャープレシオか総リターン"):
        validate_walkforward(demo1003, end, start, GRID, COSTS, bad_settings)
    with pytest.raises(EngineInputError, match="開始日は終了日より前"):
        validate_walkforward(demo1003, end, start, GRID, COSTS, SETTINGS)
    swapped = list(demo1003)
    swapped[10], swapped[11] = swapped[11], swapped[10]
    short_end = add_months(start, 17)  # 12か月 + 6か月に1日足りない
    # 日付の順番(5)は、区切りがない(6)より先
    with pytest.raises(EngineDataError, match="古い順に並んでいません"):
        validate_walkforward(swapped, start, short_end, GRID, COSTS, SETTINGS)
    with pytest.raises(EngineInputError, match="1回も取れません"):
        validate_walkforward(demo1003, start, short_end, GRID, COSTS, SETTINGS)

    # 計算の量(7)は、区切りの営業日(6)のあと、データの異常(8)の前。区切りの数が決まってから呼ぶ
    calls: list[tuple[int, int]] = []

    class TooMany(Exception):
        pass

    def too_many(n_pairs: int, n_windows: int) -> None:
        calls.append((n_pairs, n_windows))
        raise TooMany

    with pytest.raises(EngineInputError, match="選ぶ期間の営業日が3日未満"):
        validate_walkforward(
            demo1003,
            start,
            end,
            SweepGrid(3, 12, 3, 15, 400, 10),
            COSTS,
            WalkForwardSettings("sharpe_ratio", 1, 1),
            check_runs=too_many,
        )
    assert calls == []
    windows = validate_walkforward(demo1003, start, end, GRID, COSTS, SETTINGS)[1]
    # 最後の使う期間の中の日に、データの異常を入れる(最後の区切りのあとの使わない日は、確かめる範囲の外)
    last_end = windows[-1].out_of_sample.end
    target = max(i for i, b in enumerate(demo1003) if b.date <= last_end)
    broken = list(demo1003)
    broken[target] = dataclasses.replace(broken[target], adj_factor=None)
    with pytest.raises(TooMany):
        validate_walkforward(broken, start, end, GRID, COSTS, SETTINGS, check_runs=too_many)
    assert calls == [(16, len(windows))]
    with pytest.raises(EngineDataError, match="調整係数が Null"):
        validate_walkforward(broken, start, end, GRID, COSTS, SETTINGS, check_runs=lambda *_: None)


def test_data_anomaly_only_in_the_last_out_of_sample_is_found_before_computing(demo1003) -> None:
    start, end = demo1003[0].date, demo1003[-1].date
    pairs, windows = validate_walkforward(demo1003, start, end, GRID, COSTS, SETTINGS)
    last = windows[-1].out_of_sample
    target = next(i for i, b in enumerate(demo1003) if b.date >= last.end - dt.timedelta(days=3))
    broken = list(demo1003)
    broken[target] = dataclasses.replace(broken[target], adj_factor=None)
    with pytest.raises(EngineDataError, match="調整係数が Null"):
        validate_walkforward(broken, start, end, GRID, COSTS, SETTINGS)
    # その日は、確かめる範囲の中にある(すべての区切り・組み合わせ・買い持ちの範囲を合わせた範囲)
    loaded = select_load_range(demo1003, windows[0].in_sample.start, last.end, 45)
    assert loaded[0].date <= broken[target].date <= loaded[-1].date
    assert len(pairs) == 16


# --- 4章 選び方 ------------------------------------------------------------------------


def metrics(sharpe: float | None, total: float = 0.0) -> SegmentMetrics:
    return SegmentMetrics(
        total_return=total,
        annualized_return=total,
        max_drawdown=0.1,
        sharpe_ratio=sharpe,
        win_rate=None,
        trade_count=1,
        winning_trades=0,
        return_count=10,
        insufficient_cash_count=0,
        final_equity=1.0,
        holding_days=5,
    )


PAIRS = [(3, 15), (3, 25), (6, 15), (6, 25)]


def test_choose_takes_the_largest_value() -> None:
    choice = choose(
        PAIRS, [metrics(0.5), metrics(1.2), metrics(None), metrics(-0.3)], "sharpe_ratio"
    )
    assert choice == Choice((3, 25), 1.2, 1)
    by_return = choose(
        PAIRS,
        [metrics(0.5, 0.3), metrics(1.2, 0.1), metrics(None, 0.4), metrics(0.0, 0.0)],
        "total_return",
    )
    assert by_return == Choice((6, 15), 0.4, 1)


def test_choose_ties_go_to_the_first_pair_in_combo_order() -> None:
    choice = choose(PAIRS, [metrics(0.5), metrics(0.9), metrics(0.9), metrics(0.9)], "sharpe_ratio")
    assert choice == Choice((3, 25), 0.9, 3)


def test_choose_nothing_when_every_value_is_missing() -> None:
    assert choose(PAIRS, [metrics(None)] * 4, "sharpe_ratio") == Choice(None, None, 0)
    assert choose(PAIRS, [metrics(float("nan"))] * 4, "sharpe_ratio") == Choice(None, None, 0)


def test_choices_do_not_depend_on_out_of_sample_prices(demo1003) -> None:
    """使う期間の株価を書き換えても、その区切りで選ぶ組み合わせは変わらない(選ぶのは選ぶ期間の成績だけ)。"""
    start, end = demo1003[0].date, demo1003[-1].date
    original = run_walkforward(demo1003, start, end, GRID, COSTS, SETTINGS)
    last = original.windows[-1].window.out_of_sample
    changed = [
        dataclasses.replace(b, open=b.open * 1.7, close=b.close * 0.6)
        if last.start <= b.date <= last.end and b.close is not None and b.open is not None
        else b
        for b in demo1003
    ]
    again = run_walkforward(changed, start, end, GRID, COSTS, SETTINGS)
    assert [w.choice for w in again.windows] == [w.choice for w in original.windows]
    assert (
        again.windows[-1].out_of_sample != original.windows[-1].out_of_sample
    )  # 使う期間の成績は変わる


# --- 5章 使う期間とつなぎ方 ------------------------------------------------------------


def test_liquidation_formula() -> None:
    params = COSTS.params_for(3, 15)
    assert liquidated(1000.0, 0, None, params) == 1000.0
    expected = 1000.0 + 200 * 50.0 * (1 - 0.0005) * (1 - 0.001)
    assert liquidated(1000.0, 200, 50.0, params) == expected


def test_out_of_sample_equals_a_single_backtest_from_the_carried_cash(demo1003) -> None:
    start, end = demo1003[0].date, demo1003[-1].date
    result = run_walkforward(demo1003, start, end, GRID, COSTS, SETTINGS)
    cash = COSTS.initial_cash
    for w in result.windows:
        assert w.starting_cash == cash
        out = w.window.out_of_sample
        assert w.choice.pair is not None
        params = dataclasses.replace(COSTS.params_for(*w.choice.pair), initial_cash=cash)
        single = run_backtest(demo1003, out.start, out.end, params)
        assert w.out_of_sample.total_return == single.metrics.total_return
        assert w.out_of_sample.sharpe_ratio == single.metrics.sharpe_ratio
        assert w.final_equity == single.final_equity
        last = single.daily[-1]
        assert w.ended_with_shares == (last.shares > 0)
        assert w.liquidated_equity == liquidated(
            last.cash, last.shares, last.valuation_price, params
        )
        cash = w.liquidated_equity  # 次の区切りは、清算したあとの額から


def test_stitched_series(demo1003) -> None:
    start, end = demo1003[0].date, demo1003[-1].date
    result = run_walkforward(demo1003, start, end, GRID, COSTS, SETTINGS)
    first = result.windows[0].window.out_of_sample
    last = result.windows[-1].window.out_of_sample
    days = [b.date for b in demo1003 if first.start <= b.date <= last.end]
    assert [d.date for d in result.daily] == days
    by_day = {d.date: d for d in result.daily}
    for w in result.windows[:-1]:
        # 区切りの最終日は清算したあとの額。次の区切りの初日も同じ額から始まる
        out = w.window.out_of_sample
        last_day = max(d for d in days if d <= out.end)
        assert by_day[last_day].equity == w.liquidated_equity
    assert result.daily[-1].equity == result.windows[-1].final_equity  # 最後は清算する前
    assert result.metrics.final_equity == result.windows[-1].final_equity
    assert result.metrics.liquidated_equity == result.windows[-1].liquidated_equity
    assert result.metrics.total_return == result.daily[-1].equity / COSTS.initial_cash - 1
    assert result.metrics.return_count == len(days) - 1
    # 比べる相手は、つないだ期間全体の買い持ち
    benchmark = run_buy_and_hold(demo1003, first.start, last.end, COSTS.params_for(3, 15))
    assert [d.benchmark_equity for d in result.daily] == [d.equity for d in benchmark.daily]


def test_one_window_equals_the_single_backtest(demo1003) -> None:
    """区切りが1つなら、つないだ系列は、その使う期間の1組のバックテストの資産額そのもの。"""
    start = demo1003[0].date
    end = add_months(start, 18) - dt.timedelta(days=1)
    result = run_walkforward(demo1003, start, end, GRID, COSTS, SETTINGS)
    assert len(result.windows) == 1
    w = result.windows[0]
    out = w.window.out_of_sample
    single = run_backtest(demo1003, out.start, out.end, COSTS.params_for(*w.choice.pair))
    assert [d.equity for d in result.daily] == [d.equity for d in single.daily]
    assert result.metrics.total_return == single.metrics.total_return
    assert result.metrics.max_drawdown == single.metrics.max_drawdown
    assert result.metrics.sharpe_ratio == single.metrics.sharpe_ratio


def test_counts_of_changes_and_beats(demo1003) -> None:
    start, end = demo1003[0].date, demo1003[-1].date
    result = run_walkforward(demo1003, start, end, GRID, COSTS, SETTINGS)
    pairs = [w.choice.pair for w in result.windows]
    assert result.choice_changes == sum(1 for a, b in zip(pairs, pairs[1:], strict=False) if a != b)
    assert result.compared_windows == sum(1 for w in result.windows if w.benchmark_bought)
    assert result.beats_benchmark == sum(
        1
        for w in result.windows
        if w.benchmark_bought and w.out_of_sample.total_return > w.benchmark_total_return
    )
    for w in result.windows:
        out = w.window.out_of_sample
        # 区切りの買い持ちは、戦略と同じ元手(その区切りの初期資金)で買う
        params = dataclasses.replace(COSTS.params_for(3, 15), initial_cash=w.starting_cash)
        alone = run_buy_and_hold(demo1003, out.start, out.end, params)
        assert w.benchmark_total_return == alone.metrics.total_return


def test_window_without_a_choice_stays_in_cash(demo1003) -> None:
    start, end = demo1003[0].date, demo1003[-1].date
    _, windows = validate_walkforward(demo1003, start, end, GRID, COSTS, SETTINGS)
    result, series = run_window(demo1003, windows[0], Choice(None, None, 0), COSTS, 123_456.0)
    assert {equity for _, equity in series} == {123_456.0}
    out = windows[0].out_of_sample
    assert [d for d, _ in series] == [b.date for b in demo1003 if out.start <= b.date <= out.end]
    m = result.out_of_sample
    assert (m.total_return, m.max_drawdown, m.sharpe_ratio, m.trade_count) == (0.0, 0.0, None, 0)
    assert result.liquidated_equity == result.final_equity == 123_456.0
    assert not result.ended_with_shares


def test_carried_cash_out_of_range_is_an_input_error(demo1003) -> None:
    start, end = demo1003[0].date, demo1003[-1].date
    _, windows = validate_walkforward(demo1003, start, end, GRID, COSTS, SETTINGS)
    with pytest.raises(EngineInputError, match="区切り1の初期資金.*10億円以下"):
        run_window(demo1003, windows[0], Choice((3, 15), 1.0, 1), COSTS, 2_000_000_000.0)


def test_late_listing_runs_end_to_end() -> None:
    """途中で上場した架空銘柄(DEMO:1012)でも、最後まで計算できる。"""
    bars = to_engine_bars(generate_bars("1012"))
    result = run_walkforward(
        bars,
        bars[0].date,
        bars[-1].date,
        SweepGrid(5, 10, 5, 20, 40, 20),
        COSTS,
        WalkForwardSettings("total_return", 6, 3),
    )
    assert len(result.windows) >= 2
    assert result.metrics.return_count == len(result.daily) - 1

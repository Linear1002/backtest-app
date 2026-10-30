"""総当たりのリファレンス実装(engine/reference/sweep.py、docs/sweep.md)のテスト。"""

from __future__ import annotations

import dataclasses
import datetime as dt

import pytest
from engine_helpers import make_bars

from backend.api.convert import to_engine_bars
from backend.marketdata.synthetic import generate_bars
from engine.reference import EngineDataError, EngineInputError, run_backtest
from engine.reference.sweep import (
    IN_SAMPLE,
    OUT_OF_SAMPLE,
    SweepCosts,
    SweepGrid,
    in_sample_start,
    run_pairs,
    run_sweep,
    segment_metrics,
    split_segments,
    validate_grid,
    validate_sweep,
)

COSTS = SweepCosts(fee_rate=0.001, slippage_rate=0.0005, initial_cash=1_000_000.0)


@pytest.fixture(scope="module")
def demo1003():
    return to_engine_bars(generate_bars("1003"))


# --- 2章 組み合わせ -----------------------------------------------------------------


def test_pairs_are_in_order_and_only_short_less_than_long() -> None:
    grid = SweepGrid(5, 20, 5, 10, 40, 10)
    assert grid.short_values() == [5, 10, 15, 20]
    assert grid.long_values() == [10, 20, 30, 40]
    assert grid.pairs() == [
        (5, 10), (5, 20), (5, 30), (5, 40),
        (10, 20), (10, 30), (10, 40),
        (15, 20), (15, 30), (15, 40),
        (20, 30), (20, 40),
    ]  # fmt: skip


def test_default_grid_of_the_screen_has_105_pairs() -> None:
    assert len(SweepGrid(3, 30, 3, 20, 120, 10).pairs()) == 105


def test_max_is_included_only_when_on_a_step() -> None:
    assert SweepGrid(2, 7, 2, 10, 10, 1).short_values() == [2, 4, 6]


# --- 5章 チェックの順番 ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("grid", "message"),
    [
        (SweepGrid(0, 5, 1, 10, 20, 1), "日数と刻みは1以上の整数で入力してください"),
        (SweepGrid(1, 5, 0, 10, 20, 1), "日数と刻みは1以上の整数で入力してください"),
        (SweepGrid(1, 1001, 1, 10, 20, 1), "日数と刻みは1000以下で入力してください"),
        (SweepGrid(1, 5, 1, 10, 20, 1001), "日数と刻みは1000以下で入力してください"),
        (SweepGrid(6, 5, 1, 10, 20, 1), "短期の日数の範囲は、最小を最大以下にしてください"),
        (SweepGrid(1, 5, 1, 30, 20, 1), "長期の日数の範囲は、最小を最大以下にしてください"),
        (SweepGrid(10, 20, 1, 5, 10, 1), "組み合わせがありません"),
        (SweepGrid(True, 5, 1, 10, 20, 1), "1以上の整数"),  # bool は整数として扱わない
    ],
)
def test_grid_errors(grid: SweepGrid, message: str) -> None:
    with pytest.raises(EngineInputError, match=message):
        validate_grid(grid)


def test_first_wrong_grid_field_is_reported_first() -> None:
    # short_max が1000超、long_step が0。並びの順(short_max が先)で報告する
    with pytest.raises(EngineInputError, match="1000以下"):
        validate_grid(SweepGrid(1, 1001, 1, 10, 20, 0))


def test_segments() -> None:
    start, end = dt.date(2024, 1, 1), dt.date(2024, 12, 31)
    assert [s.name for s in split_segments(start, end, None)] == [IN_SAMPLE]
    in_s, out_s = split_segments(start, end, dt.date(2024, 7, 1))
    assert (in_s.start, in_s.end) == (start, dt.date(2024, 6, 30))
    assert (out_s.start, out_s.end) == (dt.date(2024, 7, 1), end)
    assert len(split_segments(start, end, end)) == 2  # 終了日そのものは検証期間の開始日にできる
    for bad in (start, dt.date(2023, 12, 31), dt.date(2025, 1, 1)):
        with pytest.raises(EngineInputError, match="検証期間の開始日は"):
            split_segments(start, end, bad)
    with pytest.raises(EngineInputError, match="開始日は終了日より前"):
        split_segments(end, start, None)


def test_costs_are_checked_after_the_grid() -> None:
    bars = make_bars([100.0] * 10)
    expensive = dataclasses.replace(COSTS, fee_rate=0.1)
    with pytest.raises(EngineInputError, match="組み合わせがありません"):
        run_sweep(bars, bars[0].date, bars[-1].date, SweepGrid(5, 5, 1, 2, 3, 1), expensive)
    with pytest.raises(EngineInputError, match="10%未満"):
        run_sweep(bars, bars[0].date, bars[-1].date, SweepGrid(1, 1, 1, 2, 3, 1), expensive)


def test_business_days_of_each_segment() -> None:
    bars = make_bars([100.0] * 10)  # 2025-01-06(月)〜 2025-01-17(金)
    grid = SweepGrid(1, 1, 1, 2, 2, 1)
    first, last = bars[0].date, bars[-1].date
    with pytest.raises(EngineInputError, match="営業日が3日未満です。検証期間の開始日を遅く"):
        run_sweep(bars, first, last, grid, COSTS, bars[2].date)
    with pytest.raises(EngineInputError, match="検証期間の営業日が3日未満"):
        run_sweep(bars, first, last, grid, COSTS, bars[-2].date)
    with pytest.raises(EngineInputError, match="期間が短すぎます"):
        run_sweep(bars, first, bars[1].date, grid, COSTS)
    # 長期2日のウォームアップ(最初の2日)を除いて、選ぶ期間が3営業日残れば計算できる
    assert len(run_sweep(bars, first, last, grid, COSTS, bars[5].date).rows) == 2


# --- 3章 選ぶ期間の始まりをそろえる --------------------------------------------------


def test_in_sample_start_waits_for_the_longest_warmup() -> None:
    bars = make_bars([100.0, 101.0, None, 102.0, 103.0, 104.0, 105.0, 106.0])  # 3日目は売買不成立
    first = bars[0].date
    # 開始日より前のデータがない:有効日が3つそろう次の営業日(売買不成立の日は数えない)
    assert in_sample_start(bars, first, 3) == bars[4].date
    # 開始日より前の有効日が足りていれば、開始日のまま(休場日でもよい)
    saturday = bars[4].date + dt.timedelta(days=1)
    assert saturday.weekday() == 5
    assert in_sample_start(bars, saturday, 3) == saturday
    # 開始日より前に有効日が1つだけ:残りの2つを開始日以降で数える
    assert in_sample_start(bars, bars[1].date, 3) == bars[4].date
    # データの最後までそろわない
    assert in_sample_start(bars, first, 8) is None


def test_all_pairs_are_scored_on_the_same_in_sample_days(demo1003) -> None:
    """データの初日から始めても、どの組み合わせも同じ日から評価する(3章)。"""
    start, end, holdout = demo1003[0].date, demo1003[-1].date, dt.date(2025, 8, 1)
    result = run_sweep(demo1003, start, end, SweepGrid(3, 12, 3, 15, 45, 10), COSTS, holdout)
    in_sample, out_of_sample = result.segments
    valid_before = [bar.date for bar in demo1003 if bar.date < in_sample.start and bar.is_valid]
    assert len(valid_before) == 45  # いちばん長い長期日数のウォームアップがちょうどそろう日
    assert (out_of_sample.start, out_of_sample.end) == (holdout, end)
    # どの組み合わせ・どちらの期間も、ウォームアップが足りていて、期間の初日からシグナルを判定できる
    for short, long in result.pairs:
        for segment in result.segments:
            single = run_backtest(
                demo1003, segment.start, segment.end, COSTS.params_for(short, long)
            )
            assert single.warmup.sufficient, (short, long, segment.name)
            assert single.warmup.signals_unavailable_until is None


@pytest.mark.parametrize(
    ("holdout", "message"),
    [
        (
            True,
            "選ぶ期間の営業日が3日未満になります。長期の日数を短くするか、検証期間の開始日を遅く",
        ),
        (False, "期間の営業日が3日未満になります。長期の日数を短くするか、期間を広げて"),
    ],
)
def test_alignment_that_leaves_too_few_days_is_an_input_error(holdout: bool, message: str) -> None:
    bars = make_bars([100.0 + i for i in range(10)])
    grid = SweepGrid(1, 1, 1, 2, 8, 6)  # いちばん長い長期日数は8日
    end = bars[-1].date if holdout else bars[9].date
    with pytest.raises(EngineInputError, match=f"最長8日.*{message}"):
        validate_sweep(bars, bars[0].date, end, grid, COSTS, bars[7].date if holdout else None)


def test_records_are_checked_over_the_longest_load_range() -> None:
    """長い組み合わせの読み込む範囲にだけある異常でも、全体をデータの異常にする(5章の6)。"""
    bars = make_bars([100.0 + i for i in range(30)])
    bars[2] = dataclasses.replace(bars[2], adj_factor=None)  # 開始日の 8 有効日前
    start, end = bars[10].date, bars[-1].date
    # 長期5日だけなら、読み込む範囲に入らないので計算できる
    run_sweep(bars, start, end, SweepGrid(1, 2, 1, 5, 5, 1), COSTS)
    with pytest.raises(EngineDataError, match="調整係数が Null"):
        run_sweep(bars, start, end, SweepGrid(1, 2, 1, 5, 10, 5), COSTS)


def test_date_order_is_checked_on_the_whole_input() -> None:
    bars = make_bars([100.0] * 10)
    bars[0], bars[1] = bars[1], bars[0]
    with pytest.raises(EngineDataError, match="古い順"):
        run_sweep(bars, bars[5].date, bars[-1].date, SweepGrid(1, 1, 1, 2, 2, 1), COSTS)


# --- 4章 1つの組み合わせの計算 ---------------------------------------------------------


def test_each_row_equals_a_single_backtest(demo1003) -> None:
    start, end, holdout = demo1003[0].date, demo1003[-1].date, dt.date(2025, 8, 1)
    result = run_sweep(demo1003, start, end, SweepGrid(3, 12, 3, 15, 45, 10), COSTS, holdout)
    assert len(result.rows) == 16 * 2
    in_sample = result.segments[0]
    assert in_sample.end == dt.date(2025, 7, 31)
    periods = {IN_SAMPLE: (in_sample.start, in_sample.end), OUT_OF_SAMPLE: (holdout, end)}
    for row in result.rows:
        params = COSTS.params_for(row.short_window, row.long_window)
        single = run_backtest(demo1003, *periods[row.segment], params)
        assert row.metrics == segment_metrics(single)
    # 行の順番:組み合わせの順番に、選ぶ期間 → 検証期間
    assert [(r.short_window, r.long_window, r.segment) for r in result.rows[:4]] == [
        (3, 15, IN_SAMPLE),
        (3, 15, OUT_OF_SAMPLE),
        (3, 25, IN_SAMPLE),
        (3, 25, OUT_OF_SAMPLE),
    ]


def test_out_of_sample_starts_without_position() -> None:
    """検証期間は、選ぶ期間の持ち株を引き継がず、初期資金から始める(3章)。"""
    # 上がり続けるので、短期1・長期2 は最初の上昇で買って、そのまま持ち続ける
    bars = make_bars([100, 99, 100, 101, 102, 103, 104, 105, 106, 107])
    start, end, holdout = bars[0].date, bars[-1].date, bars[5].date
    result = run_sweep(bars, start, end, SweepGrid(1, 1, 1, 2, 2, 1), COSTS, holdout)
    in_sample, out_of_sample = (r.metrics for r in result.rows)
    assert in_sample.final_equity != COSTS.initial_cash  # 株を持ったまま選ぶ期間が終わる
    # 検証期間の最初の日は持ち株なし(資産額 = 初期資金)。上昇が続くのでクロスは出ず、最後まで現金のまま
    assert out_of_sample.final_equity == COSTS.initial_cash
    assert out_of_sample.trade_count == 0


def test_run_pairs_in_chunks_gives_the_same_rows(demo1003) -> None:
    """API のように組み合わせを分けて計算しても、並べ直せば run_sweep と同じ。"""
    start, end, holdout = demo1003[0].date, demo1003[-1].date, dt.date(2025, 8, 1)
    grid = SweepGrid(3, 12, 3, 15, 45, 10)
    whole = run_sweep(demo1003, start, end, grid, COSTS, holdout)
    pairs = list(whole.pairs)
    rows = []
    for first in range(0, len(pairs), 5):
        outcome = run_pairs(demo1003, whole.segments, COSTS, pairs[first : first + 5], first)
        assert outcome.error_index is None
        rows.extend(outcome.rows)
    assert tuple(rows) == whole.rows


def test_run_pairs_reports_the_failing_pair_index() -> None:
    """計算の途中の誤り(株数の桁あふれ)は、その組み合わせの番号と一緒に返す(5章の7)。"""
    tiny = [1e-12] * 7
    bars = make_bars([1e-12, 1e-12, 1e-12, 1e-12, 2e-12, 3e-12, 4e-12], opens=tiny)
    costs = dataclasses.replace(COSTS, fee_rate=0.0, slippage_rate=0.0, initial_cash=1e9)
    result_segments = split_segments(bars[0].date, bars[-1].date, None)
    outcome = run_pairs(bars, result_segments, costs, [(1, 2), (1, 3)], first_index=7)
    assert outcome.error_index == 7 and outcome.error_kind == "data"
    assert "株数" in (outcome.error_message or "")
    # 長期3日のウォームアップのあと(4日目から)の上抜けで買おうとして、株数が int64 に収まらない
    with pytest.raises(EngineDataError, match="株数"):
        run_sweep(bars, bars[0].date, bars[-1].date, SweepGrid(1, 1, 1, 2, 3, 1), costs)


def test_holding_days_counts_days_with_shares() -> None:
    # 短期1・長期2:3日目(100)の終値で上抜け → 4日目の始値で買い、最後まで持つ
    bars = make_bars([100, 99, 100, 101, 102, 103, 104])
    result = run_sweep(bars, bars[0].date, bars[-1].date, SweepGrid(1, 1, 1, 2, 2, 1), COSTS)
    (row,) = result.rows
    assert result.segments[0].start == bars[2].date  # 長期2日のウォームアップ(最初の2日)を除く
    assert row.metrics.holding_days == 4  # 4日目〜7日目


def test_in_sample_rows_do_not_depend_on_out_of_sample_prices(demo1003) -> None:
    """検証期間の株価を変えても、選ぶ期間の行は1つも変わらない(先読みがないことの確かめ)。"""
    start, end, holdout = demo1003[0].date, demo1003[-1].date, dt.date(2025, 8, 1)
    grid = SweepGrid(3, 12, 3, 15, 45, 10)
    changed = [
        dataclasses.replace(
            bar,
            open=bar.open * 1.37 if bar.open is not None else None,
            high=bar.high * 1.37 if bar.high is not None else None,
            low=bar.low * 1.37 if bar.low is not None else None,
            close=bar.close * 0.71 + 5 if bar.close is not None else None,
        )
        if bar.date >= holdout
        else bar
        for bar in demo1003
    ]
    original = run_sweep(demo1003, start, end, grid, COSTS, holdout)
    modified = run_sweep(changed, start, end, grid, COSTS, holdout)
    pick = lambda result: [r for r in result.rows if r.segment == IN_SAMPLE]  # noqa: E731
    assert pick(original) == pick(modified)
    assert [r for r in original.rows if r.segment == OUT_OF_SAMPLE] != [
        r for r in modified.rows if r.segment == OUT_OF_SAMPLE
    ]

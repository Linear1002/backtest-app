"""リファレンス実装の手計算テスト。

期待値は、仕様(docs/mvp.md)の式をテストの中にそのまま書いて計算している。
short=1・long=2 にすると D(t) = C(t) − C(t−1) × CumAdj(前日)(前日からの値動き)になり、手で追いやすい。
"""

import datetime as dt
import math
import statistics

import pytest
from engine_helpers import business_dates, make_bars, params

from engine.reference import EngineDataError, EngineInputError, run_backtest
from engine.reference.backtest import decide_buy_shares, select_load_range, valuation_price
from engine.reference.indicators import compute_cross_states, cumulative_adjustments
from engine.reference.ratio import recover_split_ratio, round_half_up


def run(bars, p, start=None, end=None):
    return run_backtest(bars, start or bars[0].date, end or bars[-1].date, p)


def signal_list(result):
    return [(s.date, s.side, s.action) for s in result.signals]


# --- 2.2 移動平均と調整 --------------------------------------------------------------


def test_moving_average_sums_and_d() -> None:
    bars = make_bars([10, 11, 12, 13, 14])
    states = compute_cross_states(bars, short_window=2, long_window=3)
    assert states[0].d is None and states[1].short_sum == 21 and states[1].d is None
    # t=2: S_short = 11+12、S_long = 10+11+12、D = 23×3 − 33×2
    assert (states[2].short_sum, states[2].long_sum, states[2].d) == (23, 33, 3)
    assert states[4].d == 27 * 3 - 39 * 2


def test_cumulative_adjustment_goes_backward_from_t() -> None:
    bars = make_bars([100, 100, 50, 50], adj={2: 0.5}, ex={2: 1})
    # CumAdj_3(3)=1、CumAdj_3(2)=AF(3)=1、CumAdj_3(1)=1×AF(2)=0.5、CumAdj_3(0)=0.5×AF(1)
    assert cumulative_adjustments(bars, 3, 0) == [0.5, 0.5, 1.0, 1.0]


def test_split_does_not_create_a_false_cross() -> None:
    # 調整しないと「100 → 50」で急落に見えるが、時点 t 基準で調整すれば値動きはない
    bars = make_bars([100, 100, 50, 50, 50], adj={2: 0.5}, ex={2: 1})
    states = compute_cross_states(bars, short_window=1, long_window=2)
    assert [states[i].d for i in range(1, 5)] == [0, 0, 0, 0]
    assert run(bars, params()).signals == ()


# --- 2.3 クロスの判定 ----------------------------------------------------------------


def test_touch_then_cross_is_a_signal_and_zero_is_not() -> None:
    # D: t1=+1, t2=0(同値:クロスではない), t3=+1(D(t')=0 から上へ → 上抜け)
    bars = make_bars([10, 11, 11, 12, 12])
    result = run(bars, params())
    dates = business_dates(5)
    assert signal_list(result) == [(dates[3], "buy", "order")]


def test_signals_are_ignored_by_position_rules() -> None:
    dates = business_dates(6)
    # 持っていないときの下抜けは無視
    flat = run(make_bars([100, 101, 100]), params())
    assert signal_list(flat) == [(dates[2], "sell", "ignored")]
    # 持っているときの上抜け(同値をはさんで再び上へ)は無視
    holding = run(make_bars([100, 99, 100, 100, 101]), params())
    assert signal_list(holding) == [(dates[2], "buy", "order"), (dates[4], "buy", "ignored")]


# --- 2.5〜2.7 約定と株数:1往復をすべて手計算 ---------------------------------------


def test_full_round_trip_by_hand() -> None:
    closes = [100, 99, 101, 103, 102, 98, 97, 99]
    opens = [100, 99, 100, 102, 104, 101, 97, 98]
    fee, slip, cash0 = 0.001, 0.002, 1_000_000.0
    result = run(make_bars(closes, opens), params(fee=fee, slippage=slip, cash=cash0))
    d = business_dates(8)

    # シグナル:t2 上抜け(D: −1 → +2)、t4 下抜け(+2 → −1)、t7 上抜け(最終日なので約定しない)
    assert signal_list(result) == [
        (d[2], "buy", "order"),
        (d[4], "sell", "order"),
        (d[7], "buy", "order"),
    ]

    # 買い:t3 の始値 102 で約定
    buy_price = 102 * (1 + slip)
    unit_cost = buy_price * (1 + fee)
    shares = math.floor(cash0 / unit_cost / 100) * 100
    assert shares == 9700
    buy_cost = unit_cost * shares
    cash_after_buy = cash0 - buy_cost

    # 売り:t4 の下抜け → t5 の始値 101 で約定
    sell_price = 101 * (1 - slip)
    notional = sell_price * shares
    sell_fee = notional * fee
    proceeds = notional - sell_fee
    cash_after_sell = cash_after_buy + proceeds

    buy, sell = result.fills
    assert (buy.date, buy.side, buy.shares, buy.signal_date) == (d[3], "buy", 9700, d[2])
    assert buy.fill_price == buy_price and buy.cash_after == cash_after_buy
    assert buy.fee == buy_price * shares * fee
    assert (sell.date, sell.side, sell.shares) == (d[5], "sell", 9700)
    assert sell.fill_price == sell_price and sell.fee == sell_fee
    assert sell.cash_after == cash_after_sell

    equities = [r.equity for r in result.daily]
    assert equities == [
        cash0,
        cash0,
        cash0,
        cash_after_buy + shares * 103,
        cash_after_buy + shares * 102,
        cash_after_sell,
        cash_after_sell,
        cash_after_sell,
    ]
    assert [r.shares for r in result.daily] == [0, 0, 0, 9700, 9700, 0, 0, 0]
    assert result.daily[3].valuation_price == 103 and result.daily[5].valuation_price is None

    (trade,) = result.trades
    assert trade.pnl == proceeds - buy_cost and trade.closed_by == "sell"
    assert trade.pnl < 0  # 102.204 で買って 100.798 で売ったので負け

    # 5章の指標を、標準ライブラリで別に計算して照らし合わせる
    m = result.metrics
    returns = [equities[i] / equities[i - 1] - 1 for i in range(1, 8)]
    assert m.return_count == 7
    assert m.total_return == equities[-1] / cash0 - 1
    assert m.annualized_return == pytest.approx((equities[-1] / cash0) ** (245 / 7) - 1)
    assert m.max_drawdown == pytest.approx(1 - equities[5] / equities[3])
    assert m.sharpe_ratio == pytest.approx(
        statistics.mean(returns) / statistics.stdev(returns) * math.sqrt(245), rel=1e-12
    )
    assert (m.trade_count, m.winning_trades, m.win_rate) == (1, 0, 0.0)
    assert result.notes.annualized_is_reference and not result.notes.open_position_at_end


def test_lot_size_boundary_and_insufficient_cash() -> None:
    assert decide_buy_shares(10_000.0, 100.0, 0.0, 100) == (100, 100.0)
    assert decide_buy_shares(9_999.99, 100.0, 0.0, 100) == (0, 100.0)
    # 資金不足はスキップして数える。ノーポジションのまま次のシグナルを待つ
    bars = make_bars([100, 99, 100, 101, 100, 99, 100, 100])
    result = run(bars, params(cash=9_000))
    assert result.fills == () and result.insufficient_cash_count == 2
    assert [s.signal_date for s in result.skipped_orders] == [bars[2].date, bars[6].date]


def test_lot_correction_when_division_rounds_up() -> None:
    # cash を「ちょうど k 単位分の費用」より1ulpだけ少なくすると、割り算が k に丸まることがある。
    # そのときは lots を1減らす(2.7 の最後の行)
    fill_price, fee = 123.45, 0.001
    unit_cost = fill_price * (1 + fee)
    for k in range(1, 5000):
        cash = math.nextafter(unit_cost * (k * 100), 0.0)
        if math.floor(cash / unit_cost / 100) == k:
            break
    else:
        pytest.fail("境目のケースが見つからなかった")
    shares, _ = decide_buy_shares(cash, fill_price, fee, 100)
    assert shares == (k - 1) * 100
    assert unit_cost * shares <= cash


def test_pending_order_carries_over_halted_day() -> None:
    # t2 の上抜け → t3 は売買不成立 → t4 の始値で約定
    bars = make_bars([100, 99, 100, None, 102, 103], opens=[100, 99, 100, None, 101, 103])
    result = run(bars, params(cash=20_000))
    (fill,) = result.fills
    assert fill.date == bars[4].date and fill.signal_date == bars[2].date and fill.open_price == 101


# --- 2.8 分割・併合 ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("adj_factor", "expected"),
    [
        (0.5, (2, 1)),  # 1:2 分割
        (0.333333, (3, 1)),  # 1:3 分割(係数は近似値)
        (0.666667, (3, 2)),  # 2:3 分割
        (0.4, (5, 2)),  # 2:5 分割。q=1 では 2.5 の丸めになるが、q=2 でちょうど表せる
        (10.0, (1, 10)),  # 10:1 併合
        (1000.0, (1, 1000)),  # 1000:1 併合
        (0.001, (1000, 1)),  # 1:1000 分割
    ],
)
def test_recover_split_ratio(adj_factor: float, expected: tuple[int, int]) -> None:
    assert recover_split_ratio(adj_factor) == expected


def test_recover_split_ratio_rejects_unrepresentable_factor() -> None:
    with pytest.raises(EngineDataError):
        recover_split_ratio(10_000.0)  # 1/10000 は q ≤ 1000 では表せない


def test_round_half_up_differs_from_python_round() -> None:
    assert round_half_up(2.5) == 3 and round(2.5) == 2
    assert round_half_up(-0.5) == 0


def test_split_while_holding_keeps_equity_continuous() -> None:
    # t2 上抜け → t3 の始値 101 で買い → t4 に 1:2 分割(終値も半分)
    closes = [100, 99, 101, 102, 51, 52]
    bars = make_bars(closes, opens=[100, 99, 101, 101, 51, 52], adj={4: 0.5}, ex={4: 1})
    result = run(bars, params(cash=10_150))
    (event,) = result.events
    assert (event.shares_before, event.shares_after) == (100, 200)
    assert (event.ratio_numerator, event.ratio_denominator) == (2, 1)
    assert result.daily[4].equity == result.daily[3].equity  # 102 × 100株 = 51 × 200株
    # 調整後は値動きがないので、分割で売りシグナルは出ない(t5 の上抜けは保有中なので無視)
    assert [(s.side, s.action) for s in result.signals] == [("buy", "order"), ("buy", "ignored")]


def test_repeated_splits_and_merger_fraction_goes_to_cash() -> None:
    # 100株 → 2:3分割で150株 → もう一度2:3分割で225株 → 10:1併合で22.5株 → 22株 + 端数0.5株を現金に
    closes = [100, 99, 100, 100, 67, 45, 455, 456]
    bars = make_bars(
        closes,
        adj={4: 0.666667, 5: 0.666667, 6: 10.0},
        ex={4: 1, 5: 1, 6: 2},
    )
    result = run(bars, params(cash=10_050))
    assert [(e.shares_before, e.shares_after) for e in result.events] == [
        (100, 150),
        (150, 225),
        (225, 22),
    ]
    last = result.events[-1]
    assert last.fraction_shares == 0.5 and last.fraction_cash == 0.5 * 455
    assert result.daily[6].cash == 50 + 227.5
    assert result.daily[6].equity == 277.5 + 22 * 455


def test_merger_to_zero_closes_trade_and_cancels_sell_order() -> None:
    # t4 の下抜けで売り注文 → t5 が 1000:1 併合の権利落ち日で0株になる → 売り注文は取り消し
    closes = [100, 99, 100, 101, 100, 99_000, 99_500]
    bars = make_bars(
        closes, opens=[100, 99, 100, 100, 100, 99_000, 99_500], adj={5: 1000.0}, ex={5: 2}
    )
    result = run(bars, params(cash=10_050))
    assert [f.side for f in result.fills] == ["buy"]  # 売りは約定していない
    (event,) = result.events
    assert event.closed_position and event.shares_after == 0
    assert event.fraction_cash == pytest.approx(0.1 * 99_000)
    (trade,) = result.trades
    assert trade.closed_by == "merger" and trade.exit_date == bars[5].date
    assert trade.pnl == pytest.approx(9_900 - 10_000)
    assert (result.metrics.trade_count, result.metrics.winning_trades) == (1, 0)
    assert result.daily[5].shares == 0 and result.daily[5].cash == pytest.approx(50 + 9_900)


def test_rights_issue_keeps_shares_and_adjusts_signals() -> None:
    # 株主割当増資(ExRT=3)は持ち株数を変えない。移動平均の調整には係数 0.97 を使う
    bars = make_bars([100, 99, 100, 100, 97, 98], adj={4: 0.97}, ex={4: 3})
    result = run(bars, params(cash=10_050))
    assert result.events == ()
    assert result.daily[4].shares == 100 and result.daily[4].valuation_price == 97
    states = compute_cross_states(bars, 1, 2)
    assert states[4].d == 97 - 100 * 0.97


def test_halted_ex_date_while_holding_uses_adjusted_valuation() -> None:
    # t4 で買い → t5 は売買不成立かつ 1:2 分割の権利落ち日 → 評価価格は C(t4) × 0.5
    closes = [100, 99, 100, None, 102, None, 52]
    bars = make_bars(closes, opens=[100, 99, 100, None, 101, None, 52], adj={5: 0.5}, ex={5: 1})
    result = run(bars, params(cash=10_150))
    assert valuation_price(bars, 5) == 102 * 0.5
    (event,) = result.events
    assert event.date == bars[5].date and event.shares_after == 200
    assert result.daily[5].equity == result.daily[4].equity


# --- ウォームアップ(2.2、4.1) --------------------------------------------------------


def test_warmup_allows_signal_on_start_date() -> None:
    bars = make_bars([100, 101, 100, 102, 103, 104])
    start = bars[3].date
    result = run(bars, params(), start=start)
    assert signal_list(result)[0] == (start, "buy", "order")
    w = result.warmup
    assert (w.first_date, w.last_date, w.valid_days, w.sufficient) == (
        bars[1].date,
        bars[2].date,
        2,
        True,
    )
    assert w.signals_unavailable_until is None
    assert [r.date for r in result.daily] == [b.date for b in bars[3:]]


def test_select_load_range_is_idempotent() -> None:
    bars = make_bars([100 + i for i in range(30)])
    loaded = select_load_range(bars, bars[20].date, bars[25].date, 5)
    assert [b.date for b in loaded] == [b.date for b in bars[15:26]]
    assert select_load_range(loaded, bars[20].date, bars[25].date, 5) == loaded


def test_no_warmup_reports_when_signals_start() -> None:
    bars = make_bars([100, 101, 102, 103, 104, 105])
    result = run(bars, params(short=1, long=3))
    w = result.warmup
    assert (w.first_date, w.valid_days, w.sufficient) == (None, 0, False)
    # D は3番目の有効日から定義され、判定は4番目の有効日から。判定できない最後の日は3番目
    assert w.signals_unavailable_until == bars[2].date


def test_insufficient_warmup_counts_partial_days() -> None:
    bars = make_bars([100, 101, 102, 103, 104, 105, 106])
    result = run(bars, params(short=1, long=4), start=bars[2].date)
    w = result.warmup
    assert (w.valid_days, w.sufficient) == (2, False)
    assert w.signals_unavailable_until == bars[3].date


# --- 5章 指標 ------------------------------------------------------------------------


def test_annualized_return_overflow_is_not_computable() -> None:
    # 3営業日(N=2)で資産が約1万倍 → (成長率)^(245/2) が桁あふれ → 算出不可
    bars = make_bars([100, 99, 100, 100, 1_000_000])
    result = run(bars, params(cash=10_050), start=bars[2].date)
    assert result.metrics.return_count == 2
    assert result.metrics.annualized_return is None
    assert result.notes.open_position_at_end and result.notes.annualized_is_reference


def test_no_trades_gives_undefined_sharpe_and_win_rate() -> None:
    result = run(make_bars([100, 101, 102, 103]), params(cash=5_000))
    m = result.metrics
    assert (m.sharpe_ratio, m.win_rate, m.trade_count, m.total_return, m.max_drawdown) == (
        None,
        None,
        0,
        0.0,
        0.0,
    )


# --- 入力チェック(4.3)とデータの異常 ------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"short": 5, "long": 5}, "短期の日数は長期の日数より小さく"),
        ({"short": 0, "long": 5}, "日数は1以上の整数"),
        ({"fee": -0.001}, "0以上"),
        ({"slippage": 0.1}, "10%未満"),
        ({"cash": 0}, "初期資金は1円以上"),
        ({"cash": 1_000_000_001}, "10億円以下"),
    ],
)
def test_parameter_validation_messages(kwargs: dict, message: str) -> None:
    with pytest.raises(EngineInputError, match=message):
        run(make_bars([100, 101, 102, 103, 104, 105]), params(**kwargs))


def test_period_validation() -> None:
    bars = make_bars([100, 101, 102, 103])
    with pytest.raises(EngineInputError, match="3日以上"):
        run(bars, params(), start=bars[2].date)
    with pytest.raises(EngineInputError, match="開始日は終了日より前"):
        run(bars, params(), start=bars[3].date, end=bars[0].date)


def test_period_may_start_and_end_on_holidays() -> None:
    bars = make_bars([100, 101, 102, 103, 104])  # 2025-01-06(月)〜01-10(金)
    result = run(bars, params(), start=dt.date(2025, 1, 4), end=dt.date(2025, 1, 12))
    assert len(result.daily) == 5


@pytest.mark.parametrize(
    "broken",
    [
        {"adj": {2: None}},
        {"adj": {2: 0.5}},  # 調整係数があるのに権利落ちの種類がない
        {"adj": {2: 0.5}, "ex": {2: 9}},
    ],
)
def test_data_anomalies_are_errors(broken: dict) -> None:
    bars = make_bars([100, 101, 102, 103], **broken)
    with pytest.raises(EngineDataError):
        run(bars, params())


def test_unsorted_dates_are_errors() -> None:
    bars = make_bars([100, 101, 102, 103])
    with pytest.raises(EngineDataError, match="古い順"):
        run([bars[1], bars[0], bars[2], bars[3]], params(), start=bars[0].date, end=bars[3].date)

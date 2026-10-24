"""C++ 版の答え合わせに使う「正解データ」(ゴールデンケース)を作る。

    uv run python scripts/make_golden.py      (make golden でも同じ)

tests/golden/cases/<名前>/input/  … bars.csv と params.txt(C++ 版に渡す入力)
tests/golden/cases/<名前>/expected/ … リファレンス実装の出力(正解)
tests/golden/manifest.json        … ケースの一覧(段階・説明)

段階:
  1 … 読み込む範囲に調整係数が1でない日がない(分割・併合・増資の処理がなくても正解できる)
  2 … 分割・併合・増資を含む(docs/cpp/README.md の段階2で正解する)
マイルストーン(docs/cpp/README.md の M2〜M6):そのケースに合格できるようになる段階。
  M2 … 入力の誤り・データの異常(チェックだけで正解できる)
  M4 … 売買の途中で気づくデータの異常(株数の桁あふれ)
  M5 … 段階1の計算のケース / M6 … 段階2の計算のケース

入力の切り出し:多くのケースは「読み込む範囲」(ウォームアップの最も古い有効日〜終了日)だけを入力にする。
u で始まるケースと h19 は切り出さない(もっと前のデータ・終了日より後のデータ・範囲の外の異常を含む)。
API は銘柄の全期間を渡すので、C++ 版も自分で切り出す必要がある(docs/cpp/contract.md)。

リファレンス実装を直したら、このスクリプトで作り直して、差分を確認してからコミットする。
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import math
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.api.convert import to_engine_bars  # noqa: E402
from backend.marketdata.models import SymbolId  # noqa: E402
from backend.marketdata.synthetic import DemoDataSource  # noqa: E402
from engine.reference import (  # noqa: E402
    Bar,
    EngineDataError,
    EngineInputError,
    MaCrossParams,
    run_backtest,
)
from engine.reference.backtest import decide_buy_shares, select_load_range  # noqa: E402
from engine.reference.cli import run_case  # noqa: E402
from engine.reference.contract import to_contract_dict  # noqa: E402
from engine.reference.csvio import write_bars_csv, write_params  # noqa: E402

GOLDEN = ROOT / "tests" / "golden"
FIRST_DAY = dt.date(2025, 1, 6)


def weekdays(count: int, first: dt.date = FIRST_DAY) -> list[dt.date]:
    days, day = [], first
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += dt.timedelta(days=1)
    return days


def bars_from(
    closes: list[float | None],
    opens: list[float | None] | None = None,
    *,
    adj: dict[int, float] | None = None,
    ex: dict[int, int] | None = None,
) -> list[Bar]:
    opens = opens if opens is not None else list(closes)
    adj, ex = adj or {}, ex or {}
    out = []
    for i, (day, o, c) in enumerate(zip(weekdays(len(closes)), opens, closes, strict=True)):
        if c is None:
            o = None
        out.append(
            Bar(
                date=day,
                open=o,
                high=None if c is None else max(o, c),
                low=None if c is None else min(o, c),
                close=c,
                volume=None if c is None else 1000.0,
                adj_factor=adj.get(i, 1.0),
                ex_rt=ex.get(i),
            )
        )
    return out


def p(short=1, long=2, fee=0.0, slip=0.0, cash=1_000_000.0, lot=100) -> MaCrossParams:
    return MaCrossParams(short, long, fee, slip, float(cash), lot)


def demo(code: str) -> list[Bar]:
    return to_engine_bars(DemoDataSource().get_daily_bars(SymbolId("DEMO", code)))


def lot_correction_cash() -> float:
    """2.7 の最後の行(lots を1減らす補正)が実際に起きる資金を探す。"""
    fill_price, fee = 123.45, 0.001
    unit_cost = fill_price * (1 + fee)
    for k in range(1, 5000):
        cash = math.nextafter(unit_cost * (k * 100), 0.0)
        if math.floor(cash / unit_cost / 100) == k:
            assert decide_buy_shares(cash, fill_price, fee, 100)[0] == (k - 1) * 100
            return cash
    raise RuntimeError("見つからなかった")


def with_bar(bars: list[Bar], index: int, **changes) -> list[Bar]:
    """index 番目の日足だけを書き換えた列(データの異常のケースを作るため)。"""
    out = list(bars)
    out[index] = dataclasses.replace(out[index], **changes)
    return out


def wave(count: int, base: float = 100.0) -> list[float]:
    """上下に揺れる終値(クロスが何度も起きるように)。小数第2位までの決まった値。"""
    return [round(base + 6 * math.sin(i / 2.7) + 2 * math.sin(i / 1.3), 2) for i in range(count)]


def near_zero_sell_open(
    buy_open: float, fee: float, slip: float, shares: int
) -> tuple[float, float, float] | None:
    """仕様の計算順では損益が +ε、buy_cost を notional + fee で計算すると 0 以下になる売りの始値を探す。

    仕様(2.6):buy_cost = unit_cost × shares(unit_cost = fill_price × (1 + fee_rate))。
    数学的には notional + fee と同じだが、浮動小数点では最後の桁が違うことがある。
    勝ち負け(完全一致の項目)が入れ替わるので、計算の順番を変えた C++ を見つけられる。
    戻り値:(売りの始値, 仕様の損益, 順番を変えたときの損益)。見つからなければ None。
    """
    fill_b = buy_open * (1 + slip)
    buy_cost = (fill_b * (1 + fee)) * shares
    notional_b = fill_b * shares
    buy_cost_alt = notional_b + notional_b * fee
    if not buy_cost < buy_cost_alt:
        return None
    x = buy_cost / shares / (1 - slip) / (1 - fee)
    x = math.nextafter(x, 0.0)
    for _ in range(4000):
        fill_s = x * (1 - slip)
        notional_s = fill_s * shares
        proceeds = notional_s - notional_s * fee
        pnl, pnl_alt = proceeds - buy_cost, proceeds - buy_cost_alt
        if pnl > 0 and pnl_alt <= 0:
            return x, pnl, pnl_alt
        if pnl_alt > 0:
            return None
        x = math.nextafter(x, math.inf)
    return None


def near_zero_case_prices() -> tuple[float, float]:
    """near_zero_sell_open が見つかる (買いの始値, 売りの始値) の組。"""
    for cents in range(10_000, 10_400):
        buy_open = cents / 100
        found = near_zero_sell_open(buy_open, 0.001, 0.001, 100)
        if found:
            return buy_open, found[0]
    raise RuntimeError("損益が +ε になる価格が見つからなかった")


@dataclass
class Case:
    name: str
    title: str
    bars: list[Bar]
    start: dt.date
    end: dt.date
    params: MaCrossParams
    slice_input: bool = True  # 読み込む範囲だけを入力にする(エラーのケースは切り出さない)
    milestone: str | None = None  # None なら段階とエラーの種類から決める


def hand_cases() -> list[Case]:
    d = weekdays(12)
    cases = []

    def add(name, title, bars, params, start=None, end=None, slice_input=True):
        cases.append(
            Case(
                name, title, bars, start or bars[0].date, end or bars[-1].date, params, slice_input
            )
        )

    add(
        "h01_round_trip",
        "1往復の売買。手数料・スリッページ・資産額・指標をすべて手計算できる",
        bars_from([100, 99, 101, 103, 102, 98, 97, 99], [100, 99, 100, 102, 104, 101, 97, 98]),
        p(fee=0.001, slip=0.002),
    )
    add(
        "h02_touch_cross",
        "同値をはさんだ上抜け(D=0 はクロスではない)",
        bars_from([10, 11, 11, 12, 12]),
        p(),
    )
    add(
        "h03_ignored_signals",
        "未保有の下抜けと、保有中の上抜けは見送る",
        bars_from([100, 101, 100, 99, 100, 100, 101]),
        p(),
    )
    add(
        "h04_insufficient_cash",
        "100株分の資金がなく、買い注文を2回見送る",
        bars_from([100, 99, 100, 101, 100, 99, 100, 100]),
        p(cash=9_000),
    )
    add(
        "h05_lot_correction",
        "割り算の丸めで lots が1多くなる境目(2.7 の補正)",
        bars_from([100, 99, 100, 120, 121], [100, 99, 100, 123.45, 121]),
        p(fee=0.001, cash=lot_correction_cash()),
    )
    add(
        "h06_halted_carry_over",
        "約定日が売買不成立なので、次の有効日に繰り越す",
        bars_from([100, 99, 100, None, 102, 103], [100, 99, 100, None, 101, 103]),
        p(cash=20_000),
    )
    add(
        "h07_split_while_holding",
        "保有中の1:2分割。持ち株が2倍になり、資産額は変わらない",
        bars_from(
            [100, 99, 101, 102, 51, 52], [100, 99, 101, 101, 51, 52], adj={4: 0.5}, ex={4: 1}
        ),
        p(cash=10_150),
    )
    add(
        "h08_repeated_splits_fraction",
        "2:3分割を2回(150株→225株)、10:1併合で22株と端数0.5株",
        bars_from(
            [100, 99, 100, 100, 67, 45, 455, 456],
            adj={4: 0.666667, 5: 0.666667, 6: 10.0},
            ex={4: 1, 5: 1, 6: 2},
        ),
        p(cash=10_050),
    )
    add(
        "h09_merger_to_zero_cancels_sell",
        "1000:1併合で0株になり決済。待っていた売り注文は取り消す",
        bars_from(
            [100, 99, 100, 101, 100, 99_000, 99_500],
            [100, 99, 100, 100, 100, 99_000, 99_500],
            adj={5: 1000.0},
            ex={5: 2},
        ),
        p(cash=10_050),
    )
    add(
        "h10_rights_issue",
        "株主割当増資(ExRT=3)。持ち株は変えず、移動平均の調整だけに使う",
        bars_from([100, 99, 100, 100, 97, 98], adj={4: 0.97}, ex={4: 3}),
        p(cash=10_050),
    )
    add(
        "h11_halted_ex_date_while_holding",
        "売買不成立の日が分割の権利落ち日。評価価格は前の終値×係数",
        bars_from(
            [100, 99, 100, None, 102, None, 52],
            [100, 99, 100, None, 101, None, 52],
            adj={5: 0.5},
            ex={5: 1},
        ),
        p(cash=10_150),
    )
    b = bars_from([100, 101, 100, 102, 103, 104])
    add(
        "h12_warmup_signal_on_start",
        "ウォームアップを使い、開始日にシグナルが出る",
        b,
        p(),
        start=b[3].date,
    )
    add(
        "h13_no_warmup",
        "開始日より前のデータがない。判定できない最後の日を記録する",
        bars_from([100, 101, 102, 103, 104, 105]),
        p(short=1, long=3),
    )
    b = bars_from([100, 101, 102, 103, 104, 105, 106])
    add(
        "h14_partial_warmup",
        "ウォームアップが long_window 個に足りない",
        b,
        p(short=1, long=4),
        start=b[2].date,
    )
    b = bars_from([100, 99, 100, 100, 1_000_000])
    add(
        "h15_annualized_overflow",
        "N=2 で資産が約1万倍。年率リターンは桁あふれで算出不可",
        b,
        p(cash=10_050),
        start=b[2].date,
    )
    add(
        "h16_no_trades",
        "取引なし。シャープレシオは算出不可、勝率は「−」",
        bars_from([100, 101, 102, 103]),
        p(cash=5_000),
    )
    add(
        "h17_prev_d_zero_on_ex_date",
        "権利落ち日に D(t')=0。D(t') は t' 自身の基準で計算する",
        bars_from([2.6, 1.6, 3.6, 1.215, 1.215], adj={3: 0.333333}, ex={3: 1}),
        p(short=2, long=3, cash=10_000),
    )
    add(
        "h18_zero_pnl_merger_on_halted_day",
        "売買不成立の日に併合で0株。損益ちょうど0は負けに数える",
        bars_from([100, 99, 100, 100, None, 100_000, 100_000], adj={4: 1000.0}, ex={4: 2}),
        p(cash=1_000, lot=1),
    )
    b = bars_from([100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 108, 107, 106, 105, 104])
    add(
        "h19_period_on_weekends",
        "開始日・終了日が土日。入力は切り出さず、終了日の後にもデータがある(期間の外は使わない)",
        b,
        p(),
        start=dt.date(2025, 1, 11),
        end=dt.date(2025, 1, 19),
        slice_input=False,
    )
    add(
        "h20_split_type_with_factor_one",
        "ExRT=1 でも調整係数が1なら、分割として扱わない",
        bars_from([100, 99, 100, 101, 102, 103], ex={4: 1}),
        p(cash=20_000),
    )
    add(
        "h21_touch_down_cross",
        "同値をはさんだ下抜け。保有中の 上→同値→下 で売り、未保有の 下→同値→下 は見送り(0→負もクロス)",
        bars_from([100, 99, 100, 101, 101, 100, 99, 99, 98]),
        p(),
    )
    add(
        "h22_fractions_with_costs_then_sell",
        "1つの取引で端数が2回(3:2併合・10:1併合)。手数料・スリッページあり、最後は売りで決済",
        bars_from(
            [100, 99, 100, 101, 153, 154, 1545, 1550, 1500, 1490],
            [100, 99, 100, 100.5, 152, 153.5, 1540, 1548, 1540, 1495],
            adj={4: 1.5, 6: 10.0},
            ex={4: 2, 6: 2},
        ),
        p(fee=0.001, slip=0.002, cash=10_200),
    )
    buy_open, sell_open = near_zero_case_prices()
    add(
        "h23_near_zero_pnl",
        "損益が +ε の取引(buy_cost を notional + fee で計算すると 0 以下になり、勝ち負けが入れ替わる)",
        bars_from([100, 99, 100, 101, 100, sell_open], [100, 99, 100, buy_open, 100, sell_open]),
        p(fee=0.001, slip=0.001, cash=15_000),
    )
    add(
        "h24_halted_first_day_no_prior",
        "期間の最初の日が売買不成立で、それより前に有効日がない(株がない日は評価価格を計算しない)",
        bars_from([None, 100, 99, 100, 101, 102]),
        p(),
    )
    add(
        "h25_never_judgeable",
        "期間内に一度も判定できない(長期の日数が、有効日の数より多い)",
        bars_from([100, 101, 102, 103, 104]),
        p(short=2, long=10),
    )
    add(
        "h26_first_judgeable_after_halt",
        "判定できる最初の有効日の直前が売買不成立。最終日の買いシグナルは約定しない",
        bars_from([100, 101, None, 102, 101, 103]),
        p(),
    )
    assert d  # 日付の列は bars_from の中で作る
    return cases


def error_cases() -> list[Case]:
    cases = []
    b = bars_from([100, 99, 100, 101, 102, 75_030, 75_100], adj={5: 750.3}, ex={5: 2})
    cases.append(
        Case(
            "e01_unrecoverable_factor",
            "分数に戻せない調整係数(データの異常)",
            b,
            b[0].date,
            b[-1].date,
            p(cash=5_000),
            False,
        )
    )
    b = bars_from([100, 101, 102, 103])
    cases.append(
        Case(
            "e02_short_period",
            "期間内の営業日が3日未満(入力の誤り)",
            b,
            b[2].date,
            b[-1].date,
            p(),
            False,
        )
    )
    cases.append(
        Case(
            "e03_bad_windows",
            "短期の日数 ≥ 長期の日数(入力の誤り)",
            b,
            b[0].date,
            b[-1].date,
            p(short=5, long=5),
            False,
        )
    )
    b = bars_from([100, 99, 100, 101, 102], [100, 99, 100, 0, 102])
    cases.append(
        Case("e04_zero_open", "始値が0(データの異常)", b, b[0].date, b[-1].date, p(), False)
    )
    b = bars_from([100, 99, 100, 101, 102], adj={2: 0.5})
    cases.append(
        Case(
            "e05_factor_without_type",
            "調整係数があるのに権利落ちの種類がない(データの異常)",
            b,
            b[0].date,
            b[-1].date,
            p(),
            False,
        )
    )

    def data_error(
        name: str, title: str, bars: list[Bar], params=None, start=None, end=None, milestone=None
    ):
        cases.append(
            Case(
                name,
                title,
                bars,
                start or bars[0].date,
                end or bars[-1].date,
                params or p(),
                False,
                milestone,
            )
        )

    base = bars_from([100, 99, 100, 101, 102, 103])
    data_error(
        "e06_duplicate_date",
        "同じ日付の日足が2本ある(日付の順番の異常)",
        with_bar(base, 2, date=base[1].date),
    )
    long = bars_from(wave(30))
    swapped = list(long)
    swapped[2], swapped[3] = swapped[3], swapped[2]
    data_error(
        "e07_order_broken_outside_range",
        "読み込む範囲より前で日付の順番が崩れている(日付の順番は入力全体で確かめる)",
        swapped,
        p(short=2, long=3),
        start=long[20].date,
    )
    data_error(
        "e08_open_null_only",
        "始値だけが Null(始値と終値は、そろって Null になるはず)",
        with_bar(base, 2, open=None),
    )
    data_error("e09_adj_factor_null", "調整係数が Null", with_bar(base, 3, adj_factor=None))
    data_error(
        "e10_adj_factor_zero",
        "調整係数が 0(正の数のはず)",
        with_bar(base, 3, adj_factor=0.0, ex_rt=1),
    )
    data_error(
        "e11_adj_factor_inf",
        "調整係数が inf(有限の数のはず)",
        with_bar(base, 3, adj_factor=math.inf, ex_rt=1),
    )
    data_error(
        "e12_unknown_ex_rt",
        "権利落ちの種類が 1〜3 以外(ExRT=4)",
        with_bar(base, 3, adj_factor=0.5, ex_rt=4),
    )
    data_error(
        "e13_factor_out_of_range",
        "分割・併合の調整係数が扱える範囲(0.001〜1000)の外",
        with_bar(base, 3, adj_factor=2000.0, ex_rt=2),
    )
    data_error(
        "e14_shares_overflow",
        "買う株数が int64 に収まらない(売買の途中で気づくデータの異常)",
        bars_from([1e-12, 0.99e-12, 1e-12, 1.01e-12, 1.02e-12]),
        p(cash=1_000_000_000),
        milestone="M4",
    )
    data_error(
        "e15_start_after_end",
        "開始日が終了日より後(入力の誤り)",
        base,
        start=base[4].date,
        end=base[1].date,
    )
    data_error("e16_fee_too_high", "手数料率が10%(入力の誤り)", base, p(fee=0.1))
    data_error("e17_window_too_long", "長期の日数が1000日を超える(入力の誤り)", base, p(long=1001))
    data_error(
        "e18_input_checked_before_data",
        "入力の誤りとデータの異常の両方がある → 入力の誤り(パラメータを先に確かめる)",
        with_bar(base, 3, open=0.0),
        p(short=5, long=5),
    )
    data_error(
        "e19_order_checked_before_period",
        "日付の順番の崩れと、期間が短すぎる誤りの両方 → データの異常(日付の順番を先に確かめる)",
        with_bar(base, 1, date=base[0].date),
        start=base[4].date,
    )
    return cases


def unsliced_cases() -> list[Case]:
    """入力を切り出さないケース。API と同じく、銘柄の全期間を渡す。"""
    cases = []
    bars = bars_from(wave(64))
    # 読み込む範囲の外に、データの異常を置く(範囲の中だけを 3.7 でチェックするので、エラーにならない)
    bars = with_bar(bars, 3, open=0.0)  # ウォームアップより前
    bars = with_bar(bars, 60, adj_factor=750.3, ex_rt=2)  # 終了日より後(分数に戻せない係数)
    cases.append(
        Case(
            "u01_long_history_and_after_end",
            "切り出していない入力:前に長いデータ・終了日の後のデータ・範囲の外の異常がある(使わない)",
            bars,
            bars[40].date,
            bars[52].date,
            p(short=2, long=5, fee=0.001, slip=0.0005, cash=20_000),
            False,
        )
    )
    full = demo("1003")
    cases.append(
        Case(
            "u02_demo_window_inside_history",
            "DEMO:1003 の全期間を渡し、途中の8か月だけを計算する(期間より前の分割は読み込む範囲の外)",
            full,
            dt.date(2025, 8, 1),
            dt.date(2026, 3, 31),
            p(5, 25, 0.001, 0.0005),
            False,
        )
    )
    return cases


def demo_cases() -> list[Case]:
    full = lambda code: (demo(code)[0].date, demo(code)[-1].date)  # noqa: E731
    two_years = (dt.date(2024, 8, 1), dt.date(2026, 7, 31))
    spec = [
        (
            "d1001_full_5_25",
            "1001",
            "上昇トレンド・全期間・既定値",
            full("1001"),
            p(5, 25, 0.001, 0.0005),
        ),
        (
            "d1002_2y_13_26",
            "1002",
            "横ばい・直近2年・13日と26日(ウォームアップあり)",
            two_years,
            p(13, 26, 0.001, 0.0005),
        ),
        ("d1003_full_5_25", "1003", "保有中に1:2分割", full("1003"), p(5, 25, 0.001, 0.0005)),
        (
            "d1004_full_5_25",
            "1004",
            "保有中に1:3分割(係数 0.333333)",
            full("1004"),
            p(5, 25, 0.001, 0.0005),
        ),
        (
            "d1005_2y_8_10",
            "1005",
            "保有中に2:3分割(係数 0.666667)",
            two_years,
            p(8, 10, 0.001, 0.0005),
        ),
        ("d1006_2y_10_50", "1006", "保有中に10:1併合", two_years, p(10, 50, 0.001, 0.0005)),
        (
            "d1006_2y_8_50",
            "1006",
            "10:1併合の権利落ち日に、そのまま売りが約定する",
            two_years,
            p(8, 50, 0.001, 0.0005),
        ),
        ("d1007_2y_3_25", "1007", "保有中に株主割当増資", two_years, p(3, 25, 0.001, 0.0005)),
        (
            "d1008_full_20_22",
            "1008",
            "売買停止中の分割を、持ったまままたぐ",
            full("1008"),
            p(20, 22, 0.001, 0.0005),
        ),
        ("d1009_2y_5_25", "1009", "資金不足で買えない", two_years, p(5, 25, 0.001, 0.0005)),
        (
            "d1010_2y_25_75",
            "1010",
            "下落トレンド・手数料0.3%・スリッページ0.1%",
            two_years,
            p(25, 75, 0.003, 0.001),
        ),
        (
            "d1011_2y_lot1",
            "1011",
            "急落と回復・1株単位",
            two_years,
            p(5, 25, 0.001, 0.0005, 300_000, 1),
        ),
        (
            "d1012_late_listing",
            "1012",
            "途中上場・ウォームアップが足りない",
            (dt.date(2025, 6, 2), dt.date(2026, 7, 31)),
            p(13, 75, 0.001, 0.0005),
        ),
    ]
    return [
        Case(name, f"DEMO:{code} {title}", demo(code), start, end, params)
        for name, code, title, (start, end), params in spec
    ]


def loaded_bars(case: Case) -> list[Bar]:
    """エンジンが実際に使う「読み込む範囲」。切り出せない(エラーになる)ときは入力全体。"""
    try:
        return select_load_range(case.bars, case.start, case.end, case.params.long_window)
    except EngineInputError, EngineDataError:
        return case.bars


def stage_of(case: Case) -> int:
    """読み込む範囲に、調整係数が1でない日があれば段階2。範囲の外の係数は計算に使わない。"""
    bars = loaded_bars(case)
    return 2 if any(bar.adj_factor not in (None, 1.0) for bar in bars) else 1


def milestone_of(case: Case, stage: int, error_kind: str | None) -> str:
    if case.milestone:
        return case.milestone
    if error_kind is not None:
        return "M2"
    return "M5" if stage == 1 else "M6"


def period_business_days(case: Case) -> int:
    return sum(1 for bar in case.bars if case.start <= bar.date <= case.end)


def check_unsliced_matches_sliced(case: Case) -> None:
    """切り出していない入力と、切り出した入力で、結果がまったく同じになることを確かめる(2.2 の約束)。"""
    full = to_contract_dict(run_backtest(case.bars, case.start, case.end, case.params))
    sliced_bars = select_load_range(case.bars, case.start, case.end, case.params.long_window)
    sliced = to_contract_dict(run_backtest(sliced_bars, case.start, case.end, case.params))
    assert full == sliced, f"{case.name}:切り出す前と後で結果が違う"


def main() -> None:
    cases_dir = GOLDEN / "cases"
    if cases_dir.exists():
        shutil.rmtree(cases_dir)
    manifest = []
    groups = (
        ("hand", hand_cases()),
        ("error", error_cases()),
        ("demo", demo_cases()),
        ("unsliced", unsliced_cases()),
    )
    for kind, cases in groups:
        for case in cases:
            bars = loaded_bars(case) if case.slice_input else case.bars
            if kind == "unsliced" or (not case.slice_input and kind == "hand"):
                check_unsliced_matches_sliced(case)
            input_dir = cases_dir / case.name / "input"
            expected_dir = cases_dir / case.name / "expected"
            input_dir.mkdir(parents=True)
            write_bars_csv(input_dir / "bars.csv", bars)
            write_params(input_dir / "params.txt", case.start, case.end, case.params)
            code = run_case(input_dir, expected_dir)
            if kind == "error":
                assert code == 2, f"{case.name} はエラーになるはずだった"
            else:
                assert code == 0, f"{case.name} がエラーになった"
            error_kind = None
            if code == 2:
                error_kind = (
                    (expected_dir / "error.txt")
                    .read_text(encoding="utf-8")
                    .split("\n")[0]
                    .removeprefix("kind=")
                )
            stage = stage_of(case)
            milestone = milestone_of(case, stage, error_kind)
            manifest.append(
                {
                    "name": case.name,
                    "title": case.title,
                    "kind": kind,
                    "stage": stage,
                    "milestone": milestone,
                    "expected_error": error_kind,
                    "business_days": period_business_days(case),
                    "input_rows": len(bars),
                }
            )
            print(f"{case.name:40s} 段階{stage} {milestone} {case.title}")
    (GOLDEN / "manifest.json").write_text(
        json.dumps({"cases": manifest}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n{len(manifest)} ケースを {cases_dir.relative_to(ROOT)} に書きました")


if __name__ == "__main__":
    main()

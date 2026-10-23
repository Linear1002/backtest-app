"""C++ 版の答え合わせに使う「正解データ」(ゴールデンケース)を作る。

    uv run python scripts/make_golden.py      (make golden でも同じ)

tests/golden/cases/<名前>/input/  … bars.csv と params.txt(C++ 版に渡す入力)
tests/golden/cases/<名前>/expected/ … リファレンス実装の出力(正解)
tests/golden/manifest.json        … ケースの一覧(段階・説明)

段階:
  1 … 読み込む範囲に調整係数が1でない日がない(分割・併合・増資の処理がなくても正解できる)
  2 … 分割・併合・増資を含む(docs/cpp/README.md の段階2で正解する)

リファレンス実装を直したら、このスクリプトで作り直して、差分を確認してからコミットする。
"""

from __future__ import annotations

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
from engine.reference import Bar, EngineDataError, EngineInputError, MaCrossParams  # noqa: E402
from engine.reference.backtest import decide_buy_shares, select_load_range  # noqa: E402
from engine.reference.cli import run_case  # noqa: E402
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


@dataclass
class Case:
    name: str
    title: str
    bars: list[Bar]
    start: dt.date
    end: dt.date
    params: MaCrossParams
    slice_input: bool = True  # 読み込む範囲だけを入力にする(エラーのケースは切り出さない)


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
    b = bars_from([100, 101, 102, 103, 104, 105, 106, 107, 108, 109])
    add(
        "h19_period_on_weekends",
        "開始日・終了日が土日",
        b,
        p(),
        start=dt.date(2025, 1, 11),
        end=dt.date(2025, 1, 19),
    )
    add(
        "h20_split_type_with_factor_one",
        "ExRT=1 でも調整係数が1なら、分割として扱わない",
        bars_from([100, 99, 100, 101, 102, 103], ex={4: 1}),
        p(cash=20_000),
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


def stage_of(bars: list[Bar]) -> int:
    return 2 if any(bar.adj_factor not in (None, 1.0) for bar in bars) else 1


def main() -> None:
    cases_dir = GOLDEN / "cases"
    if cases_dir.exists():
        shutil.rmtree(cases_dir)
    manifest = []
    for kind, cases in (("hand", hand_cases()), ("error", error_cases()), ("demo", demo_cases())):
        for case in cases:
            bars = case.bars
            if case.slice_input:
                try:
                    bars = select_load_range(
                        case.bars, case.start, case.end, case.params.long_window
                    )
                except EngineInputError, EngineDataError:
                    bars = case.bars
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
            manifest.append(
                {
                    "name": case.name,
                    "title": case.title,
                    "kind": kind,
                    "stage": stage_of(bars),
                    "expected_error": error_kind,
                    "business_days": len(bars),
                }
            )
            print(f"{case.name:40s} 段階{stage_of(bars)} {case.title}")
    (GOLDEN / "manifest.json").write_text(
        json.dumps({"cases": manifest}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n{len(manifest)} ケースを {cases_dir.relative_to(ROOT)} に書きました")


if __name__ == "__main__":
    main()

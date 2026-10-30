"""総当たり(docs/sweep.md)の正解データを作る。C++ 版・CUDA 版の総当たりの答え合わせに使う。

    uv run python scripts/make_golden_sweeps.py      (make golden でも作り直す)

tests/golden/sweeps/<名前>/input/    … bars.csv と sweep.txt(sweep_cli に渡す入力)
tests/golden/sweeps/<名前>/expected/ … リファレンス実装の出力(combos.csv か error.txt)
tests/golden/sweeps/manifest.json   … ケースの一覧

段階(単体のバックテストの正解データと同じ):
  1 … 読み込む範囲を合わせた範囲に、調整係数が1でない日がない / 2 … 分割・併合を含む

入力の bars.csv は、架空データ(DEMO)の全期間か、単体のバックテストの正解データ(tests/golden/cases)の入力をそのまま使う。
総当たりは API と同じく銘柄の全期間を受け取るので、切り出さない(s09 だけは、途中で上場した銘柄に見立てて前を切る)。
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.api.convert import to_engine_bars  # noqa: E402
from backend.marketdata.models import SymbolId  # noqa: E402
from backend.marketdata.synthetic import DemoDataSource  # noqa: E402
from engine.reference.backtest import select_load_range  # noqa: E402
from engine.reference.csvio import read_bars_csv, write_bars_csv  # noqa: E402
from engine.reference.sweep import (  # noqa: E402
    SweepCosts,
    SweepGrid,
    in_sample_start,
    run_sweep,
    validate_grid,
)
from engine.reference.sweep_cli import run_case  # noqa: E402
from engine.reference.sweep_files import write_sweep_input  # noqa: E402
from engine.reference.types import Bar, EngineDataError, EngineInputError  # noqa: E402

GOLDEN = ROOT / "tests" / "golden"
SWEEPS = GOLDEN / "sweeps"
COSTS = SweepCosts(fee_rate=0.001, slippage_rate=0.0005, initial_cash=1_000_000.0)


@dataclass(frozen=True)
class SweepCase:
    name: str
    title: str
    bars: list[Bar]
    start: dt.date
    end: dt.date
    grid: SweepGrid
    costs: SweepCosts = COSTS
    holdout_start: dt.date | None = None


def demo(code: str) -> list[Bar]:
    return to_engine_bars(DemoDataSource().get_daily_bars(SymbolId("DEMO", code)))


def golden_input(case_name: str) -> list[Bar]:
    """単体のバックテストの正解データの入力(手で作った境界ケース)。"""
    return read_bars_csv(GOLDEN / "cases" / case_name / "input" / "bars.csv")


def full(bars: list[Bar]) -> tuple[dt.date, dt.date]:
    return bars[0].date, bars[-1].date


def nth_business_day(bars: list[Bar], start: dt.date, n: int) -> dt.date:
    """start 以降の営業日を、1から数えて n 番目の日。"""
    return [bar.date for bar in bars if bar.date >= start][n - 1]


def compute_cases() -> list[SweepCase]:
    d1001, d1002, d1003, d1004 = demo("1001"), demo("1002"), demo("1003"), demo("1004")
    d1005, d1008, d1012 = demo("1005"), demo("1008"), demo("1012")
    h22 = golden_input("h22_fractions_with_costs_then_sell")
    h08 = golden_input("h08_repeated_splits_fraction")
    # 2025-02-03 に上場した銘柄に見立てる(売買停止の 2025-03-10〜14 が、ウォームアップの途中に入る)
    d1008_listed = [bar for bar in d1008 if bar.date >= dt.date(2025, 2, 3)]
    boundary_start = dt.date(2023, 3, 1)
    d1001_halt = halted(d1001, d1001[5].date)
    return [
        SweepCase(
            "s01_demo1001_small_grid",
            "DEMO:1001 全期間。短期2〜6 × 長期8〜12(25通り)。検証期間なし",
            d1001,
            *full(d1001),
            SweepGrid(2, 6, 1, 8, 12, 1),
        ),
        SweepCase(
            "s02_demo1003_holdout",
            "DEMO:1003(1:2分割)。短期3〜12(刻み3)× 長期15〜45(刻み10)。2025-08-01 から検証期間",
            d1003,
            *full(d1003),
            SweepGrid(3, 12, 3, 15, 45, 10),
            holdout_start=dt.date(2025, 8, 1),
        ),
        SweepCase(
            "s03_demo1004_skip_invalid_pairs",
            "DEMO:1004(1:3分割)。短期5〜20 × 長期10〜40(刻み5・10)。短期 ≥ 長期の組は作らない(12通り)",
            d1004,
            *full(d1004),
            SweepGrid(5, 20, 5, 10, 40, 10),
            holdout_start=dt.date(2025, 1, 6),
        ),
        SweepCase(
            "s04_demo1012_late_listing",
            "DEMO:1012(途中上場)。開始日より前の有効日が41日しかないので、選ぶ期間の始まりを長期80日のウォームアップがそろう日まで遅らせる",
            d1012,
            dt.date(2025, 6, 2),
            dt.date(2026, 7, 31),
            SweepGrid(5, 15, 5, 20, 80, 30),
            holdout_start=dt.date(2026, 2, 2),
        ),
        SweepCase(
            "s05_hand_fractions_holdout",
            "手作りの10日(3:2併合で端数)。短期1 × 長期2。2025-01-13 から検証期間(選ぶ期間の持ち株を引き継がない)",
            h22,
            *full(h22),
            SweepGrid(1, 1, 1, 2, 2, 1),
            costs=SweepCosts(fee_rate=0.001, slippage_rate=0.002, initial_cash=10_200.0),
            holdout_start=dt.date(2025, 1, 13),
        ),
        SweepCase(
            "s06_hand_repeated_splits",
            "手作りの8日(2:3分割を2回・10:1併合で端数)。短期1 × 長期2",
            h08,
            *full(h08),
            SweepGrid(1, 1, 1, 2, 2, 1),
            costs=SweepCosts(fee_rate=0.0, slippage_rate=0.0, initial_cash=15_000.0),
        ),
        SweepCase(
            "s07_demo1005_holdout_on_holiday",
            "DEMO:1005(2:3分割 2025-07-01)。検証期間の開始日が土曜日(2025-06-28)。分割は検証期間の中",
            d1005,
            *full(d1005),
            SweepGrid(5, 10, 5, 20, 30, 10),
            holdout_start=dt.date(2025, 6, 28),
        ),
        SweepCase(
            "s08_demo1002_grid_max_off_step",
            "DEMO:1002。最大が刻みに乗らない格子(短期3〜10 刻み3 → 3・6・9、長期20〜55 刻み10 → 20〜50)",
            d1002,
            *full(d1002),
            SweepGrid(3, 10, 3, 20, 55, 10),
            holdout_start=dt.date(2025, 10, 1),
        ),
        SweepCase(
            "s09_demo1008_align_across_halt",
            "DEMO:1008 を 2025-02-03 上場に見立てる。選ぶ期間の始まりをそろえるとき、売買停止の日(有効日でない)は数えない",
            d1008_listed,
            dt.date(2025, 2, 3),
            dt.date(2025, 12, 30),
            SweepGrid(5, 15, 5, 20, 40, 10),
            holdout_start=dt.date(2025, 9, 1),
        ),
        SweepCase(
            "s10_in_sample_exactly_three_days",
            "DEMO:1001。選ぶ期間がちょうど3営業日(通る境界)。開始日より前のデータが十分あるので、始まりは動かない",
            d1001,
            boundary_start,
            nth_business_day(d1001, boundary_start, 20),
            SweepGrid(2, 2, 1, 5, 5, 1),
            holdout_start=nth_business_day(d1001, boundary_start, 4),
        ),
        SweepCase(
            "s11_align_onto_halted_day",
            "DEMO:1001 の6日目を売買不成立にする。データの初日から始めると、そろえた選ぶ期間の始まりは"
            "5個目の有効日の次の営業日(売買不成立の日)。選ぶ期間はその日を含めてちょうど3営業日(通る境界)",
            d1001_halt,
            d1001_halt[0].date,
            d1001_halt[40].date,
            SweepGrid(2, 2, 1, 5, 5, 1),
            holdout_start=d1001_halt[8].date,
        ),
    ]


def with_bar(bars: list[Bar], day: dt.date, **changes) -> list[Bar]:
    out = list(bars)
    index = next(i for i, bar in enumerate(out) if bar.date == day)
    out[index] = dataclasses.replace(out[index], **changes)
    return out


def halted(bars: list[Bar], day: dt.date) -> list[Bar]:
    """その日を売買不成立の日(四本値・出来高が Null)にする。"""
    return with_bar(bars, day, open=None, high=None, low=None, close=None, volume=None)


def valid_day_before(bars: list[Bar], start: dt.date, count: int) -> dt.date:
    """start より前の有効日を、新しい方から数えて count 番目の日。"""
    before = [bar.date for bar in bars if bar.date < start and bar.is_valid]
    return before[-count]


def error_cases() -> list[SweepCase]:
    d1001 = demo("1001")
    e14 = golden_input("e14_shares_overflow")
    boundary_start = dt.date(2023, 3, 1)
    start, end = dt.date(2023, 1, 4), dt.date(2024, 12, 30)
    # 長期60日のウォームアップには入るが、長期40日以下のウォームアップには入らない日
    only_longest = valid_day_before(d1001, start, 50)
    d1001_halt = halted(d1001, d1001[5].date)
    swapped = list(d1001)
    swapped[10], swapped[11] = swapped[11], swapped[10]  # 日付の順番が崩れている
    return [
        SweepCase(
            "se01_no_pairs",
            "短期 ≥ 長期 の組しかない(入力の誤り)",
            d1001,
            *full(d1001),
            SweepGrid(10, 20, 5, 5, 10, 5),
        ),
        SweepCase(
            "se02_window_over_1000",
            "短期の最大が1001(入力の誤り)",
            d1001,
            *full(d1001),
            SweepGrid(5, 1001, 1, 1002, 1003, 1),
        ),
        SweepCase(
            "se03_fee_too_high",
            "手数料率が10%(入力の誤り。格子のあとに確かめる)",
            d1001,
            *full(d1001),
            SweepGrid(5, 5, 1, 25, 25, 1),
            costs=dataclasses.replace(COSTS, fee_rate=0.1),
        ),
        SweepCase(
            "se04_holdout_on_start",
            "検証期間の開始日が期間の開始日と同じ(入力の誤り)",
            d1001,
            *full(d1001),
            SweepGrid(5, 5, 1, 25, 25, 1),
            holdout_start=d1001[0].date,
        ),
        SweepCase(
            "se05_holdout_too_short",
            "検証期間の営業日が2日(入力の誤り)",
            d1001,
            *full(d1001),
            SweepGrid(5, 5, 1, 25, 25, 1),
            holdout_start=d1001[-2].date,
        ),
        SweepCase(
            "se06_anomaly_only_for_longest",
            "いちばん長い長期日数(60日)の読み込む範囲にだけ、調整係数が Null の日がある(データの異常)",
            with_bar(d1001, only_longest, adj_factor=None),
            start,
            end,
            SweepGrid(5, 10, 5, 20, 60, 20),
        ),
        SweepCase(
            "se07_grid_checked_before_date_order",
            "組み合わせがなく(入力)、日付の順番も崩れている(データ)。格子を先に確かめる",
            swapped,
            *full(d1001),
            SweepGrid(30, 30, 1, 10, 20, 10),
        ),
        SweepCase(
            "se08_short_holdout_before_anomaly",
            "検証期間が2日(入力)で、読み込む範囲に異常もある(データ)。営業日の数を先に確かめる",
            with_bar(d1001, d1001[-1].date, adj_factor=0.0),
            *full(d1001),
            SweepGrid(5, 5, 1, 25, 25, 1),
            holdout_start=d1001[-2].date,
        ),
        SweepCase(
            "se09_in_sample_two_days",
            "選ぶ期間(検証期間より前)が2営業日(入力の誤り。s10 の1日前)",
            d1001,
            boundary_start,
            nth_business_day(d1001, boundary_start, 20),
            SweepGrid(2, 2, 1, 5, 5, 1),
            holdout_start=nth_business_day(d1001, boundary_start, 3),
        ),
        SweepCase(
            "se10_alignment_leaves_too_few_days",
            "データの初日から始め、長期60日のウォームアップを除くと選ぶ期間が1営業日しか残らない(入力の誤り)",
            d1001,
            *full(d1001),
            SweepGrid(5, 5, 1, 60, 60, 1),
            holdout_start=nth_business_day(d1001, d1001[0].date, 62),
        ),
        SweepCase(
            "se11_anomaly_only_in_holdout",
            "検証期間の中にだけ、調整係数が Null の日がある(データの異常)",
            with_bar(d1001, dt.date(2026, 3, 2), adj_factor=None),
            *full(d1001),
            SweepGrid(5, 5, 1, 25, 25, 1),
            holdout_start=dt.date(2025, 12, 1),
        ),
        SweepCase(
            "se12_shares_overflow",
            "買う株数が int64 に収まらない(5章の7:計算の途中で気づくデータの異常)",
            e14,
            *full(e14),
            SweepGrid(1, 1, 1, 2, 2, 1),
            costs=SweepCosts(fee_rate=0.0, slippage_rate=0.0, initial_cash=1_000_000_000.0),
        ),
        SweepCase(
            "se13_align_onto_halted_day_two_days",
            "s11 の検証期間を1日早める。売買不成立の日を含めて選ぶ期間が2営業日になる(入力の誤り)",
            d1001_halt,
            d1001_halt[0].date,
            d1001_halt[40].date,
            SweepGrid(2, 2, 1, 5, 5, 1),
            holdout_start=d1001_halt[7].date,
        ),
    ]


def union_range(case: SweepCase) -> list[Bar]:
    """すべての組み合わせの読み込む範囲を合わせた範囲(docs/sweep.md 5章の6)。求められなければ入力全体。"""
    try:
        pairs = validate_grid(case.grid)
        longest = max(long for _, long in pairs)
        start = in_sample_start(case.bars, case.start, longest) or case.start
        return select_load_range(case.bars, start, case.end, longest)
    except EngineInputError, EngineDataError:
        return case.bars


def stage_of(case: SweepCase) -> int:
    return 2 if any(bar.adj_factor not in (None, 1.0) for bar in union_range(case)) else 1


def main() -> None:
    if SWEEPS.exists():
        shutil.rmtree(SWEEPS)
    manifest = []
    for kind, cases in (("compute", compute_cases()), ("error", error_cases())):
        for case in cases:
            input_dir = SWEEPS / case.name / "input"
            expected_dir = SWEEPS / case.name / "expected"
            input_dir.mkdir(parents=True)
            write_bars_csv(input_dir / "bars.csv", case.bars)
            write_sweep_input(
                input_dir / "sweep.txt",
                case.start,
                case.end,
                case.holdout_start,
                case.grid,
                case.costs,
            )
            code = run_case(input_dir, expected_dir)
            error_kind = None
            if code == 2:
                first_line = (expected_dir / "error.txt").read_text(encoding="utf-8").split("\n")[0]
                error_kind = first_line.removeprefix("kind=")
            if kind == "error":
                assert code == 2, f"{case.name} はエラーになるはずだった"
            else:
                assert code == 0, f"{case.name} がエラーになった"
            pairs = segments = 0
            if error_kind is None:
                result = run_sweep(
                    case.bars, case.start, case.end, case.grid, case.costs, case.holdout_start
                )
                pairs, segments = len(result.pairs), len(result.segments)
            manifest.append(
                {
                    "name": case.name,
                    "title": case.title,
                    "kind": kind,
                    "stage": stage_of(case),
                    "expected_error": error_kind,
                    "pairs": pairs,
                    "segments": segments,
                    "input_rows": len(case.bars),
                }
            )
            print(f"{case.name:40s} {error_kind or f'{pairs}通り × {segments}期間'}  {case.title}")
    (SWEEPS / "manifest.json").write_text(
        json.dumps({"cases": manifest}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n{len(manifest)} ケースを {SWEEPS.relative_to(ROOT)} に書きました")


if __name__ == "__main__":
    main()

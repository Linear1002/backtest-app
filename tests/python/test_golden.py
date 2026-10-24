"""ゴールデンケース(tests/golden)のテスト。

1. リファレンス実装が、保存してある正解をビット単位で再現すること(うっかり計算を変えていないか)
2. C++ 版の backtest_cli がビルドされていれば、正解と docs/mvp.md 6章の基準で一致すること

C++ 版のテストだけを動かす:make test-cpp(いま取り組んでいるマイルストーンまで:make test-cpp UPTO=M3)
環境変数:
  BACKTEST_CPP_CLI     … C++ 版のコマンドの場所(既定: build/engine/cpp/backtest_cli)
  BACKTEST_CPP_UPTO    … どのマイルストーンまでのケース・項目を比べるか(M2〜M6。既定: M6 = すべて)
                         M3・M4 は、その段階で作る項目だけを比べる(FIELDS_AT)
  BACKTEST_CPP_ONLY    … 比べる項目を自分で絞る(例: "signals.date,signals.side,daily.short_ma")
  BACKTEST_CPP_STRICT  … 1 にすると、小数も許容誤差なしの完全一致で比べる(「ビット単位で一致」を確かめる)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from engine.reference import EngineDataError, EngineInputError, run_backtest
from engine.reference.backtest import select_load_range
from engine.reference.compare import compare_results
from engine.reference.contract import to_contract_dict
from engine.reference.csvio import read_bars_csv, read_outputs, read_params

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "golden"
MANIFEST = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))["cases"]
CASES = {case["name"]: case for case in MANIFEST}

MILESTONES = ("M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8")
# M3・M4 の途中では、その段階で作る項目だけを比べる(docs/cpp/README.md)
FIELDS_AT = {
    "M3": {
        "signals.date",
        "signals.side",
        "daily.date",
        "daily.close",
        "daily.short_ma",
        "daily.long_ma",
    },
    "M4": {"signals", "fills", "skipped_orders", "daily", "trades"},
}


def case_dir(name: str) -> Path:
    return GOLDEN / "cases" / name


def rank(milestone: str) -> int:
    if milestone not in MILESTONES:
        raise ValueError(f"マイルストーンは M0〜M8 で指定してください: {milestone!r}")
    return MILESTONES.index(milestone)


def comparison_plan(case: dict, upto: str) -> tuple[bool, set[str] | None, str]:
    """(比べるか, 比べる項目(None はすべて), 比べない理由) を決める。

    - エラーのケース:そのケースのマイルストーン(M2 か M4)に着いたら比べる
    - 計算のケース:段階1は M3 から一部の項目を、M5 ですべてを比べる。段階2は M6 で比べる
    """
    if case["expected_error"]:
        if rank(case["milestone"]) <= rank(upto):
            return True, None, ""
        return False, None, f"{case['milestone']} で合格するケース(いまは {upto})"
    if rank(upto) < rank(case["milestone"]):
        if case["stage"] == 1 and upto in FIELDS_AT:
            return True, FIELDS_AT[upto], ""
        return False, None, f"{case['milestone']} で合格するケース(いまは {upto})"
    return True, None, ""


@pytest.mark.parametrize("name", list(CASES))
def test_reference_reproduces_golden(name: str) -> None:
    directory = case_dir(name)
    bars = read_bars_csv(directory / "input" / "bars.csv")
    start, end, params = read_params(directory / "input" / "params.txt")
    expected = read_outputs(directory / "expected")
    try:
        actual = to_contract_dict(run_backtest(bars, start, end, params))
    except (EngineInputError, EngineDataError) as error:
        kind = "input" if isinstance(error, EngineInputError) else "data"
        actual = {"error": {"kind": kind}}
    assert compare_results(expected, actual, strict=True) == []


def test_manifest_covers_stages_milestones_and_kinds() -> None:
    assert {case["stage"] for case in MANIFEST} == {1, 2}
    assert {case["kind"] for case in MANIFEST} == {"hand", "error", "demo", "unsliced"}
    assert {case["milestone"] for case in MANIFEST} == {"M2", "M4", "M5", "M6"}
    assert {case["expected_error"] for case in MANIFEST} == {None, "input", "data"}


@pytest.mark.parametrize(
    "name",
    [
        c["name"]
        for c in MANIFEST
        if c["kind"] == "unsliced" or c["name"] == "h19_period_on_weekends"
    ],
)
def test_unsliced_input_gives_the_same_result_as_sliced(name: str) -> None:
    """切り出していない入力(API と同じく全期間)でも、切り出した入力と結果がまったく同じ(docs/mvp.md 2.2)。"""
    directory = case_dir(name)
    bars = read_bars_csv(directory / "input" / "bars.csv")
    start, end, params = read_params(directory / "input" / "params.txt")
    sliced = select_load_range(bars, start, end, params.long_window)
    assert len(sliced) < len(bars), "このケースの入力は、切り出していないはず"
    full = to_contract_dict(run_backtest(bars, start, end, params))
    assert full == to_contract_dict(run_backtest(sliced, start, end, params))


@pytest.mark.parametrize(
    ("upto", "name", "expected"),
    [
        ("M2", "e02_short_period", (True, None)),
        ("M2", "e14_shares_overflow", (False, None)),
        ("M4", "e14_shares_overflow", (True, None)),
        ("M2", "h01_round_trip", (False, None)),
        ("M3", "h01_round_trip", (True, FIELDS_AT["M3"])),
        ("M4", "d1001_full_5_25", (True, FIELDS_AT["M4"])),
        ("M5", "h01_round_trip", (True, None)),
        ("M5", "h07_split_while_holding", (False, None)),
        ("M6", "h07_split_while_holding", (True, None)),
    ],
)
def test_comparison_plan(upto: str, name: str, expected: tuple[bool, set[str] | None]) -> None:
    run, only, _ = comparison_plan(CASES[name], upto)
    assert (run, only) == expected


def cpp_cli() -> Path | None:
    configured = os.environ.get("BACKTEST_CPP_CLI")
    path = Path(configured) if configured else ROOT / "build" / "engine" / "cpp" / "backtest_cli"
    return path if path.exists() else None


def run_and_compare(
    command: list[str], name: str, out: Path, only: set[str] | None, *, strict: bool = False
) -> list[str]:
    """コマンドを入力フォルダ・出力フォルダを引数にして実行し、正解と比べる。違いの一覧を返す。"""
    case = CASES[name]
    completed = subprocess.run(
        [*command, str(case_dir(name) / "input"), str(out)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    expected_code = 2 if case["expected_error"] else 0
    if completed.returncode != expected_code:
        return [
            f"終了コードが {completed.returncode} でした(正しくは {expected_code})\n{completed.stderr}"
        ]
    expected = read_outputs(case_dir(name) / "expected")
    try:
        actual = read_outputs(out)
    except (FileNotFoundError, ValueError, KeyError) as error:
        return [f"出力を読めませんでした:{error}"]
    return compare_results(expected, actual, only=only, strict=strict)


@pytest.mark.parametrize("name", list(CASES))
def test_cpp_matches_golden(name: str, tmp_path: Path) -> None:
    cli = cpp_cli()
    if cli is None:
        pytest.skip("C++ 版の backtest_cli がまだありません(docs/cpp/README.md)")
    case = CASES[name]
    upto = os.environ.get("BACKTEST_CPP_UPTO", "M6").strip() or "M6"
    run, only, reason = comparison_plan(case, upto)
    if not run:
        pytest.skip(reason)
    custom = {s.strip() for s in os.environ.get("BACKTEST_CPP_ONLY", "").split(",") if s.strip()}
    strict = os.environ.get("BACKTEST_CPP_STRICT", "") == "1"
    differences = run_and_compare([str(cli)], name, tmp_path / "out", custom or only, strict=strict)
    assert differences == [], f"{case['title']}\n" + "\n".join(differences)


@pytest.mark.parametrize(
    "name",
    [
        "h01_round_trip",
        "h08_repeated_splits_fraction",
        "h22_fractions_with_costs_then_sell",
        "e01_unrecoverable_factor",
        "e11_adj_factor_inf",
        "e14_shares_overflow",
        "u01_long_history_and_after_end",
    ],
)
def test_harness_works_with_reference_cli(name: str, tmp_path: Path) -> None:
    """C++ 版の代わりにリファレンスのコマンドを入れて、答え合わせの仕組み自体が動くことを確かめる。"""
    command = [sys.executable, "-m", "engine.reference.cli"]
    assert run_and_compare(command, name, tmp_path / "out", None, strict=True) == []


def test_harness_reports_missing_output_files(tmp_path: Path) -> None:
    """出力のファイルが足りないときは、例外ではなく「違い」として分かる文で報告する。"""
    script = tmp_path / "fake_cli.py"
    script.write_text(
        "import sys, pathlib\n"
        "out = pathlib.Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)\n"
        "(out / 'signals.csv').write_text('date,side,action\\n')\n",
        encoding="utf-8",
    )
    differences = run_and_compare(
        [sys.executable, str(script)], "h01_round_trip", tmp_path / "out", None
    )
    assert len(differences) == 1 and "daily.csv がありません" in differences[0]

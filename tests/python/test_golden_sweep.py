"""総当たりの正解データ(tests/golden/sweeps、docs/sweep.md 11章)のテスト。

1. リファレンス実装が、保存してある正解をビット単位で再現すること
2. C++ 版(・CUDA 版)の sweep_cli がビルドされていれば、正解と docs/sweep.md 6章の基準で一致すること

環境変数:
  BACKTEST_CPP_SWEEP_CLI … 総当たりのコマンドの場所(既定: build/engine/cpp/sweep_cli)
  BACKTEST_CPP_STRICT    … 1 にすると、小数も許容誤差なしの完全一致で比べる
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from engine.reference.csvio import read_bars_csv
from engine.reference.sweep import run_sweep
from engine.reference.sweep_files import (
    combo_rows,
    compare_combos,
    read_combos,
    read_sweep_input,
)
from engine.reference.types import EngineDataError, EngineInputError

ROOT = Path(__file__).resolve().parents[2]
SWEEPS = ROOT / "tests" / "golden" / "sweeps"
MANIFEST = json.loads((SWEEPS / "manifest.json").read_text(encoding="utf-8"))["cases"]
CASES = {case["name"]: case for case in MANIFEST}


def case_dir(name: str) -> Path:
    return SWEEPS / name


@pytest.mark.parametrize("name", list(CASES))
def test_reference_reproduces_golden_sweep(name: str) -> None:
    directory = case_dir(name)
    bars = read_bars_csv(directory / "input" / "bars.csv")
    start, end, holdout, grid, costs = read_sweep_input(directory / "input" / "sweep.txt")
    expected = read_combos(directory / "expected")
    try:
        actual = {"combos": combo_rows(run_sweep(bars, start, end, grid, costs, holdout))}
    except (EngineInputError, EngineDataError) as error:
        kind = "input" if isinstance(error, EngineInputError) else "data"
        actual = {"error": {"kind": kind}}
    assert compare_combos(expected, actual, strict=True) == []


def test_manifest_covers_kinds_stages_and_errors() -> None:
    assert {case["kind"] for case in MANIFEST} == {"compute", "error"}
    assert {case["stage"] for case in MANIFEST} == {1, 2}
    assert {case["expected_error"] for case in MANIFEST} == {None, "input", "data"}
    assert {case["segments"] for case in MANIFEST if case["kind"] == "compute"} == {1, 2}


def sweep_cli() -> Path | None:
    configured = os.environ.get("BACKTEST_CPP_SWEEP_CLI")
    path = Path(configured) if configured else ROOT / "build" / "engine" / "cpp" / "sweep_cli"
    return path if path.exists() else None


def run_and_compare(command: list[str], name: str, out: Path, *, strict: bool = False) -> list[str]:
    case = CASES[name]
    completed = subprocess.run(
        [*command, str(case_dir(name) / "input"), str(out)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    expected_code = 2 if case["expected_error"] else 0
    if completed.returncode != expected_code:
        return [
            f"終了コードが {completed.returncode} でした(正しくは {expected_code})\n{completed.stderr}"
        ]
    try:
        actual = read_combos(out)
    except (FileNotFoundError, ValueError, KeyError) as error:
        return [f"出力を読めませんでした:{error}"]
    return compare_combos(read_combos(case_dir(name) / "expected"), actual, strict=strict)


@pytest.mark.parametrize("name", list(CASES))
def test_cpp_sweep_matches_golden(name: str, tmp_path: Path) -> None:
    cli = sweep_cli()
    if cli is None:
        pytest.skip("総当たりの sweep_cli がまだありません(docs/gpu-plan.md の G2)")
    strict = os.environ.get("BACKTEST_CPP_STRICT", "") == "1"
    differences = run_and_compare([str(cli)], name, tmp_path / "out", strict=strict)
    assert differences == [], f"{CASES[name]['title']}\n" + "\n".join(differences)


@pytest.mark.parametrize(
    "name",
    ["s02_demo1003_holdout", "s05_hand_fractions_holdout", "se06_anomaly_only_for_longest"],
)
def test_harness_works_with_reference_sweep_cli(name: str, tmp_path: Path) -> None:
    """C++ 版の代わりにリファレンスのコマンドを入れて、答え合わせの仕組み自体が動くことを確かめる。"""
    command = [sys.executable, "-m", "engine.reference.sweep_cli"]
    assert run_and_compare(command, name, tmp_path / "out", strict=True) == []


def test_compare_reports_a_changed_value(tmp_path: Path) -> None:
    """値が1つ違えば、どの組み合わせ・どの列かが分かる文で報告する。"""
    expected = read_combos(case_dir("s01_demo1001_small_grid") / "expected")
    changed = {"combos": [dict(row) for row in expected["combos"]]}
    changed["combos"][3]["trade_count"] += 1
    changed["combos"][5]["sharpe_ratio"] = (changed["combos"][5]["sharpe_ratio"] or 0) * (1 + 1e-6)
    differences = compare_combos(expected, changed)
    assert len(differences) == 2
    assert "trade_count" in differences[0] and "2日・11日" in differences[0]
    assert "sharpe_ratio" in differences[1]
    # 許容誤差の内側(相対 1e-12)の違いは、ふつうの比べ方では一致、--strict では違い
    tiny = {"combos": [dict(row) for row in expected["combos"]]}
    tiny["combos"][0]["final_equity"] *= 1 + 1e-12
    assert compare_combos(expected, tiny) == []
    assert len(compare_combos(expected, tiny, strict=True)) == 1

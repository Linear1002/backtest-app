"""ゴールデンケース(tests/golden)のテスト。

1. リファレンス実装が、保存してある正解をビット単位で再現すること(うっかり計算を変えていないか)
2. C++ 版の backtest_cli がビルドされていれば、正解と docs/mvp.md 6章の基準で一致すること

C++ 版のテストだけを動かす:make test-cpp(段階1だけなら make test-cpp STAGE=1)
環境変数:
  BACKTEST_CPP_CLI    … C++ 版のコマンドの場所(既定: build/engine/cpp/backtest_cli)
  BACKTEST_CPP_STAGE  … どの段階までのケースを比べるか(1 か 2。既定: 2)
  BACKTEST_CPP_ONLY   … 比べる項目を絞る(例: "signals.date,signals.side,daily.short_ma")
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from engine.reference import EngineDataError, EngineInputError, run_backtest
from engine.reference.compare import compare_results
from engine.reference.contract import to_contract_dict
from engine.reference.csvio import read_bars_csv, read_outputs, read_params

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "golden"
MANIFEST = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))["cases"]
CASES = {case["name"]: case for case in MANIFEST}


def case_dir(name: str) -> Path:
    return GOLDEN / "cases" / name


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


def test_manifest_covers_both_stages_and_errors() -> None:
    stages = {case["stage"] for case in MANIFEST}
    kinds = {case["kind"] for case in MANIFEST}
    assert stages == {1, 2} and kinds == {"hand", "error", "demo"}


def cpp_cli() -> Path | None:
    configured = os.environ.get("BACKTEST_CPP_CLI")
    path = Path(configured) if configured else ROOT / "build" / "engine" / "cpp" / "backtest_cli"
    return path if path.exists() else None


def run_and_compare(command: list[str], name: str, out: Path, only: set[str] | None) -> list[str]:
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
    return compare_results(expected, read_outputs(out), only=only)


@pytest.mark.parametrize("name", list(CASES))
def test_cpp_matches_golden(name: str, tmp_path: Path) -> None:
    cli = cpp_cli()
    if cli is None:
        pytest.skip("C++ 版の backtest_cli がまだありません(docs/cpp/README.md)")
    case = CASES[name]
    stage = int(os.environ.get("BACKTEST_CPP_STAGE", "2"))
    if case["stage"] > stage:
        pytest.skip(f"段階{case['stage']}のケース(BACKTEST_CPP_STAGE={stage})")
    only = {s.strip() for s in os.environ.get("BACKTEST_CPP_ONLY", "").split(",") if s.strip()}
    differences = run_and_compare([str(cli)], name, tmp_path / "out", only or None)
    assert differences == [], f"{case['title']}\n" + "\n".join(differences)


@pytest.mark.parametrize(
    "name", ["h01_round_trip", "h08_repeated_splits_fraction", "e01_unrecoverable_factor"]
)
def test_harness_works_with_reference_cli(name: str, tmp_path: Path) -> None:
    """C++ 版の代わりにリファレンスのコマンドを入れて、答え合わせの仕組み自体が動くことを確かめる。"""
    command = [sys.executable, "-m", "engine.reference.cli"]
    assert run_and_compare(command, name, tmp_path / "out", None) == []

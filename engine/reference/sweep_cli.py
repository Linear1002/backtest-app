"""総当たりのリファレンス実装を、C++ 版・CUDA 版と同じ形のコマンドとして動かす(docs/sweep.md 11章)。

    uv run python -m engine.reference.sweep_cli 入力フォルダ 出力フォルダ
    uv run python -m engine.reference.sweep_cli 正解のフォルダ 比べるフォルダ --compare [--strict]

入力フォルダには bars.csv と sweep.txt を置く。終了コードは、成功 0・入力やデータの誤り 2。
C++ 版の sweep_cli も、同じ引数・同じ出力・同じ終了コードにする。
--compare を付けると、2つの出力フォルダ(combos.csv)を docs/sweep.md 6章の基準で比べる。
"""

from __future__ import annotations

import sys
from pathlib import Path

from engine.reference.csvio import read_bars_csv, write_error
from engine.reference.sweep import run_sweep
from engine.reference.sweep_files import (
    combo_rows,
    compare_combos,
    read_combos,
    read_sweep_input,
    write_combos,
)
from engine.reference.types import EngineDataError, EngineInputError

EXIT_OK = 0
EXIT_REJECTED = 2
USAGE = (
    "使い方: python -m engine.reference.sweep_cli 入力フォルダ 出力フォルダ\n"
    "        python -m engine.reference.sweep_cli 正解のフォルダ 比べるフォルダ --compare [--strict]"
)


def run_case(input_dir: Path, output_dir: Path) -> int:
    bars = read_bars_csv(input_dir / "bars.csv")
    start, end, holdout_start, grid, costs = read_sweep_input(input_dir / "sweep.txt")
    try:
        result = run_sweep(bars, start, end, grid, costs, holdout_start)
    except EngineInputError as error:
        write_error(output_dir, "input", str(error))
        return EXIT_REJECTED
    except EngineDataError as error:
        write_error(output_dir, "data", str(error))
        return EXIT_REJECTED
    write_combos(output_dir, combo_rows(result))
    return EXIT_OK


def compare_dirs(expected_dir: Path, actual_dir: Path, *, strict: bool) -> int:
    try:
        actual = read_combos(actual_dir)
    except (FileNotFoundError, ValueError) as error:
        print(f"比べるフォルダの出力を読めませんでした:{error}")
        return 1
    differences = compare_combos(read_combos(expected_dir), actual, strict=strict)
    if not differences:
        print("一致しました")
        return 0
    print(f"違いがあります({len(differences)}件まで表示):")
    for line in differences:
        print(f"  - {line}")
    return 1


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    flags = {a for a in args if a.startswith("--")}
    paths = [a for a in args if not a.startswith("--")]
    if len(paths) != 2 or not flags <= {"--compare", "--strict"}:
        print(USAGE, file=sys.stderr)
        return 64
    if "--compare" in flags:
        return compare_dirs(Path(paths[0]), Path(paths[1]), strict="--strict" in flags)
    return run_case(Path(paths[0]), Path(paths[1]))


if __name__ == "__main__":
    sys.exit(main())

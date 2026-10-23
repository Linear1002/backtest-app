"""リファレンス実装を、C++ 版と同じ形のコマンドとして動かす(docs/cpp/contract.md)。

    uv run python -m engine.reference.cli 入力フォルダ 出力フォルダ

入力フォルダには bars.csv と params.txt を置く。終了コードは、成功 0・入力やデータの誤り 2。
C++ 版の backtest_cli も、同じ引数・同じ出力・同じ終了コードにする。
"""

from __future__ import annotations

import sys
from pathlib import Path

from engine.reference import EngineDataError, EngineInputError, run_backtest
from engine.reference.contract import to_contract_dict
from engine.reference.csvio import read_bars_csv, read_params, write_error, write_outputs

EXIT_OK = 0
EXIT_REJECTED = 2


def run_case(input_dir: Path, output_dir: Path) -> int:
    bars = read_bars_csv(input_dir / "bars.csv")
    start, end, params = read_params(input_dir / "params.txt")
    try:
        result = run_backtest(bars, start, end, params)
    except EngineInputError as error:
        write_error(output_dir, "input", str(error))
        return EXIT_REJECTED
    except EngineDataError as error:
        write_error(output_dir, "data", str(error))
        return EXIT_REJECTED
    write_outputs(output_dir, to_contract_dict(result))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("使い方: python -m engine.reference.cli 入力フォルダ 出力フォルダ", file=sys.stderr)
        return 64
    return run_case(Path(args[0]), Path(args[1]))


if __name__ == "__main__":
    sys.exit(main())

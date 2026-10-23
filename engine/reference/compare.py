"""2つの結果(リファレンスと C++ 版など)を、docs/mvp.md 6章の基準で比べる。

- 完全に一致させる項目(contract.EXACT_FIELDS):日付・株数・シグナル・取引回数など
- それ以外の数値:|a − b| ≤ 1e-12 + 1e-9 × |b|(b が正解の値)

コマンドとしても使える:
    uv run python -m engine.reference.compare 正解のフォルダ 比べるフォルダ [--only signals.date,signals.side]
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

from engine.reference.contract import EXACT_FIELDS
from engine.reference.csvio import KEY_VALUES, TABLES, read_outputs

ABS_TOL = 1e-12
REL_TOL = 1e-9


def values_match(expected: Any, actual: Any, *, exact: bool) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    if isinstance(expected, float) or isinstance(actual, float):
        if exact:
            return float(expected) == float(actual)
        a, b = float(actual), float(expected)
        return math.isfinite(a) and abs(a - b) <= ABS_TOL + REL_TOL * abs(b)
    return expected == actual


def compare_results(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    only: set[str] | None = None,
    strict: bool = False,
    limit: int = 30,
) -> list[str]:
    """違いを日本語の文の一覧で返す。空なら一致。

    only:比べる項目を「ファイル名.列名」で絞る(例: {"signals.date", "signals.side"})。ファイル名だけでもよい
    strict:True なら、許容誤差を使わずすべて完全一致で比べる(リファレンス同士の比較用)
    """
    differences: list[str] = []

    def wanted(name: str, column: str) -> bool:
        return only is None or name in only or f"{name}.{column}" in only

    def note(text: str) -> None:
        differences.append(text)

    if "error" in expected or "error" in actual:
        e_kind = expected.get("error", {}).get("kind")
        a_kind = actual.get("error", {}).get("kind")
        if e_kind != a_kind:
            note(
                f"エラーの有無・種類が違います:正解={e_kind or 'エラーなし'}、結果={a_kind or 'エラーなし'}"
            )
        return differences

    for name, columns in TABLES.items():
        names = [column for column, _ in columns if wanted(name, column)]
        if not names:
            continue
        rows_e, rows_a = expected[name], actual[name]
        if len(rows_e) != len(rows_a):
            note(f"{name}.csv の行数が違います:正解={len(rows_e)}、結果={len(rows_a)}")
        for i, (row_e, row_a) in enumerate(zip(rows_e, rows_a, strict=False)):
            for column in names:
                exact = strict or column in EXACT_FIELDS.get(name, ())
                if not values_match(row_e[column], row_a[column], exact=exact):
                    key = row_e.get("date") or row_e.get("entry_date") or i
                    note(
                        f"{name}.csv {i + 1}行目({key})の {column}:"
                        f"正解={row_e[column]!r}、結果={row_a[column]!r}"
                    )
                    if len(differences) >= limit:
                        return differences
    for name, keys in KEY_VALUES.items():
        for key, _ in keys:
            if not wanted(name, key):
                continue
            exact = strict or key in EXACT_FIELDS.get(name, ())
            if not values_match(expected[name][key], actual[name][key], exact=exact):
                note(
                    f"{name}.txt の {key}:正解={expected[name][key]!r}、結果={actual[name][key]!r}"
                )
    return differences[:limit]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="2つの出力フォルダを docs/mvp.md 6章の基準で比べる"
    )
    parser.add_argument("expected", type=Path, help="正解(リファレンス)の出力フォルダ")
    parser.add_argument("actual", type=Path, help="比べる出力フォルダ")
    parser.add_argument(
        "--only", default="", help="比べる項目(例: signals.date,signals.side,daily)"
    )
    args = parser.parse_args(argv)
    only = {item.strip() for item in args.only.split(",") if item.strip()} or None
    differences = compare_results(read_outputs(args.expected), read_outputs(args.actual), only=only)
    if not differences:
        print("一致しました")
        return 0
    print(f"違いがあります({len(differences)}件まで表示):")
    for line in differences:
        print(f"  - {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

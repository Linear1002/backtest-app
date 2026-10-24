"""総当たりの答え合わせに使うファイル(docs/sweep.md 11章)。

入力:bars.csv(単体のバックテストと同じ)と sweep.txt(期間・格子・費用。key=value)
出力:combos.csv(組み合わせごと・期間ごとの成績)。エラーのときは error.txt だけ

値の書き方・読み方(Null は空欄、小数は元の値に戻せる表記)は csvio.py と同じ。
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Any

from engine.reference.compare import values_match
from engine.reference.csvio import format_value, parse_value, read_key_values
from engine.reference.sweep import SweepCosts, SweepGrid, SweepResult
from engine.reference.types import TRADING_DAYS_PER_YEAR

SWEEP_KEYS = (
    "start",
    "end",
    "holdout_start",
    "short_min",
    "short_max",
    "short_step",
    "long_min",
    "long_max",
    "long_step",
    "fee_rate",
    "slippage_rate",
    "initial_cash",
    "lot_size",
    "trading_days_per_year",
)

COMBO_COLUMNS: tuple[tuple[str, str], ...] = (
    ("short_window", "int"),
    ("long_window", "int"),
    ("segment", "str"),
    ("total_return", "float"),
    ("annualized_return", "float"),
    ("max_drawdown", "float"),
    ("sharpe_ratio", "float"),
    ("win_rate", "float"),
    ("trade_count", "int"),
    ("winning_trades", "int"),
    ("return_count", "int"),
    ("insufficient_cash_count", "int"),
    ("final_equity", "float"),
)

# 完全に一致させる列(docs/sweep.md 6章)。それ以外の小数は許容誤差内で比べる
EXACT_COMBO_COLUMNS = (
    "short_window",
    "long_window",
    "segment",
    "win_rate",
    "trade_count",
    "winning_trades",
    "return_count",
    "insufficient_cash_count",
)


# --- 入力 ---------------------------------------------------------------------------


def write_sweep_input(
    path: Path,
    start: dt.date,
    end: dt.date,
    holdout_start: dt.date | None,
    grid: SweepGrid,
    costs: SweepCosts,
) -> None:
    values: dict[str, Any] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "holdout_start": holdout_start.isoformat() if holdout_start else None,
        "short_min": grid.short_min,
        "short_max": grid.short_max,
        "short_step": grid.short_step,
        "long_min": grid.long_min,
        "long_max": grid.long_max,
        "long_step": grid.long_step,
        "fee_rate": costs.fee_rate,
        "slippage_rate": costs.slippage_rate,
        "initial_cash": costs.initial_cash,
        "lot_size": costs.lot_size,
        "trading_days_per_year": costs.trading_days_per_year,
    }
    path.write_text(
        "".join(f"{key}={format_value(values[key])}\n" for key in SWEEP_KEYS), encoding="utf-8"
    )


def read_sweep_input(
    path: Path,
) -> tuple[dt.date, dt.date, dt.date | None, SweepGrid, SweepCosts]:
    v = read_key_values(path)
    holdout = v.get("holdout_start", "")
    return (
        dt.date.fromisoformat(v["start"]),
        dt.date.fromisoformat(v["end"]),
        dt.date.fromisoformat(holdout) if holdout else None,
        SweepGrid(
            short_min=int(v["short_min"]),
            short_max=int(v["short_max"]),
            short_step=int(v["short_step"]),
            long_min=int(v["long_min"]),
            long_max=int(v["long_max"]),
            long_step=int(v["long_step"]),
        ),
        SweepCosts(
            fee_rate=float(v["fee_rate"]),
            slippage_rate=float(v["slippage_rate"]),
            initial_cash=float(v["initial_cash"]),
            lot_size=int(v["lot_size"]),
            trading_days_per_year=int(v.get("trading_days_per_year", TRADING_DAYS_PER_YEAR)),
        ),
    )


# --- 出力 ---------------------------------------------------------------------------


def combo_rows(result: SweepResult) -> list[dict[str, Any]]:
    """結果を combos.csv の行(列名 → 値)にする。"""
    rows = []
    for row in result.rows:
        m = row.metrics
        rows.append(
            {
                "short_window": row.short_window,
                "long_window": row.long_window,
                "segment": row.segment,
                "total_return": m.total_return,
                "annualized_return": m.annualized_return,
                "max_drawdown": m.max_drawdown,
                "sharpe_ratio": m.sharpe_ratio,
                "win_rate": m.win_rate,
                "trade_count": m.trade_count,
                "winning_trades": m.winning_trades,
                "return_count": m.return_count,
                "insufficient_cash_count": m.insufficient_cash_count,
                "final_equity": m.final_equity,
            }
        )
    return rows


def write_combos(out_dir: Path, rows: list[dict[str, Any]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "combos.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow([column for column, _ in COMBO_COLUMNS])
        for row in rows:
            writer.writerow([format_value(row[column]) for column, _ in COMBO_COLUMNS])


def read_combos(out_dir: Path) -> dict[str, Any]:
    """出力フォルダを読む。{"combos": [...]} か、エラーなら {"error": {...}}。"""
    error = out_dir / "error.txt"
    if error.exists():
        return {"error": read_key_values(error)}
    path = out_dir / "combos.csv"
    if not path.exists():
        raise FileNotFoundError("出力フォルダに combos.csv がありません")
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        expected = [column for column, _ in COMBO_COLUMNS]
        if header != expected:
            raise ValueError(f"combos.csv の見出しが違います: {header}(正しくは {expected})")
        return {
            "combos": [
                {
                    column: parse_value(text, kind)
                    for (column, kind), text in zip(COMBO_COLUMNS, row, strict=True)
                }
                for row in reader
                if row
            ]
        }


# --- 比べる -------------------------------------------------------------------------


def compare_combos(
    expected: dict[str, Any], actual: dict[str, Any], *, strict: bool = False, limit: int = 30
) -> list[str]:
    """2つの出力(read_combos の形)を docs/sweep.md 6章の基準で比べる。違いの文の一覧(空なら一致)。"""
    if "error" in expected or "error" in actual:
        e_kind = expected.get("error", {}).get("kind")
        a_kind = actual.get("error", {}).get("kind")
        if e_kind != a_kind:
            return [
                f"エラーの有無・種類が違います:正解={e_kind or 'エラーなし'}、結果={a_kind or 'エラーなし'}"
            ]
        return []
    differences: list[str] = []
    rows_e, rows_a = expected["combos"], actual["combos"]
    if len(rows_e) != len(rows_a):
        differences.append(f"combos.csv の行数が違います:正解={len(rows_e)}、結果={len(rows_a)}")
    for i, (row_e, row_a) in enumerate(zip(rows_e, rows_a, strict=False)):
        label = f"{row_e['short_window']}日・{row_e['long_window']}日・{row_e['segment']}"
        for column, _ in COMBO_COLUMNS:
            exact = strict or column in EXACT_COMBO_COLUMNS
            if not values_match(row_e[column], row_a[column], exact=exact):
                differences.append(
                    f"combos.csv {i + 2}行目({label})の {column}:"
                    f"正解={row_e[column]!r}、結果={row_a[column]!r}"
                )
                if len(differences) >= limit:
                    return differences
    return differences

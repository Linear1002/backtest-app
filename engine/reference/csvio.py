"""C++ 版と答え合わせするためのファイル形式(docs/cpp/contract.md)。

入力:bars.csv(日足)と params.txt(期間とパラメータ)
出力:daily.csv・signals.csv・fills.csv・skipped_orders.csv・events.csv・trades.csv(表)と
      warmup.txt・metrics.txt(key=value)。エラーのときは error.txt だけ。

- Null は空欄
- 小数は Python の repr(元の値に戻せる最短の表記)で書く。読むときは文字列から float に戻すので、
  C++ 側は %.17g で書けば同じ値に戻る
- 真偽値は true / false
"""

from __future__ import annotations

import csv
import datetime as dt
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from engine.reference.types import Bar, MaCrossParams

BAR_COLUMNS = ("date", "open", "high", "low", "close", "volume", "adj_factor", "ex_rt")

PARAM_KEYS = (
    "start",
    "end",
    "short_window",
    "long_window",
    "fee_rate",
    "slippage_rate",
    "initial_cash",
    "lot_size",
)

# 出力の表:ファイル名 → (列名, 型) の並び。型は str / int / float / bool
TABLES: dict[str, tuple[tuple[str, str], ...]] = {
    "daily": (
        ("date", "str"),
        ("close", "float"),
        ("short_ma", "float"),
        ("long_ma", "float"),
        ("cash", "float"),
        ("shares", "int"),
        ("valuation_price", "float"),
        ("equity", "float"),
    ),
    "signals": (("date", "str"), ("side", "str"), ("action", "str")),
    "fills": (
        ("date", "str"),
        ("signal_date", "str"),
        ("side", "str"),
        ("open_price", "float"),
        ("fill_price", "float"),
        ("shares", "int"),
        ("notional", "float"),
        ("fee", "float"),
        ("cash_after", "float"),
    ),
    "skipped_orders": (
        ("date", "str"),
        ("signal_date", "str"),
        ("open_price", "float"),
        ("fill_price", "float"),
        ("cash", "float"),
    ),
    "events": (
        ("date", "str"),
        ("ex_rt", "int"),
        ("adj_factor", "float"),
        ("p", "int"),
        ("q", "int"),
        ("shares_before", "int"),
        ("shares_after", "int"),
        ("fraction_shares", "float"),
        ("fraction_cash", "float"),
        ("closed_position", "bool"),
    ),
    "trades": (
        ("entry_date", "str"),
        ("entry_price", "float"),
        ("entry_shares", "int"),
        ("buy_cost", "float"),
        ("exit_date", "str"),
        ("exit_price", "float"),
        ("exit_shares", "int"),
        ("sell_proceeds", "float"),
        ("fraction_cash", "float"),
        ("pnl", "float"),
        ("closed_by", "str"),
    ),
}

# 出力の key=value ファイル
KEY_VALUES: dict[str, tuple[tuple[str, str], ...]] = {
    "warmup": (
        ("first_date", "str"),
        ("last_date", "str"),
        ("valid_days", "int"),
        ("sufficient", "bool"),
        ("signals_unavailable_until", "str"),
    ),
    "metrics": (
        ("total_return", "float"),
        ("annualized_return", "float"),
        ("max_drawdown", "float"),
        ("sharpe_ratio", "float"),
        ("win_rate", "float"),
        ("trade_count", "int"),
        ("winning_trades", "int"),
        ("return_count", "int"),
    ),
}


# --- 値の書き方・読み方 ---------------------------------------------------------------


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"有限でない値は書けません: {value}")
        return repr(value)
    return str(value)


def parse_value(text: str, kind: str) -> Any:
    text = text.strip()
    if text == "":
        return None
    if kind == "str":
        return text
    if kind == "int":
        return int(text)
    if kind == "float":
        return float(text)
    if kind == "bool":
        if text not in ("true", "false"):
            raise ValueError(f"true か false のはずの値が {text!r} です")
        return text == "true"
    raise ValueError(f"知らない型です: {kind}")


# --- 入力 ---------------------------------------------------------------------------


def write_bars_csv(path: Path, bars: Sequence[Bar]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(BAR_COLUMNS)
        for bar in bars:
            writer.writerow(
                [
                    bar.date.isoformat(),
                    format_value(bar.open),
                    format_value(bar.high),
                    format_value(bar.low),
                    format_value(bar.close),
                    format_value(bar.volume),
                    format_value(bar.adj_factor),
                    format_value(bar.ex_rt),
                ]
            )


def read_bars_csv(path: Path) -> list[Bar]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        if tuple(header) != BAR_COLUMNS:
            raise ValueError(f"bars.csv の見出しが違います: {header}")
        bars = []
        for row in reader:
            if not row:
                continue
            values = dict(zip(BAR_COLUMNS, row, strict=True))
            bars.append(
                Bar(
                    date=dt.date.fromisoformat(values["date"]),
                    open=parse_value(values["open"], "float"),
                    high=parse_value(values["high"], "float"),
                    low=parse_value(values["low"], "float"),
                    close=parse_value(values["close"], "float"),
                    volume=parse_value(values["volume"], "float"),
                    adj_factor=parse_value(values["adj_factor"], "float"),
                    ex_rt=parse_value(values["ex_rt"], "int"),
                )
            )
        return bars


def write_params(path: Path, start: dt.date, end: dt.date, params: MaCrossParams) -> None:
    values = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "short_window": params.short_window,
        "long_window": params.long_window,
        "fee_rate": params.fee_rate,
        "slippage_rate": params.slippage_rate,
        "initial_cash": params.initial_cash,
        "lot_size": params.lot_size,
    }
    path.write_text(
        "".join(f"{key}={format_value(values[key])}\n" for key in PARAM_KEYS), encoding="utf-8"
    )


def read_key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            raise ValueError(f"{path.name} の行が key=value の形ではありません: {line!r}")
        values[key.strip()] = value.strip()
    return values


def read_params(path: Path) -> tuple[dt.date, dt.date, MaCrossParams]:
    v = read_key_values(path)
    return (
        dt.date.fromisoformat(v["start"]),
        dt.date.fromisoformat(v["end"]),
        MaCrossParams(
            short_window=int(v["short_window"]),
            long_window=int(v["long_window"]),
            fee_rate=float(v["fee_rate"]),
            slippage_rate=float(v["slippage_rate"]),
            initial_cash=float(v["initial_cash"]),
            lot_size=int(v["lot_size"]),
        ),
    )


# --- 出力 ---------------------------------------------------------------------------


def write_outputs(out_dir: Path, result: dict[str, Any]) -> None:
    """engine.reference.contract.to_contract_dict の形を、ファイルに書く。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, columns in TABLES.items():
        with open(out_dir / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow([column for column, _ in columns])
            for row in result[name]:
                writer.writerow([format_value(row[column]) for column, _ in columns])
    for name, keys in KEY_VALUES.items():
        (out_dir / f"{name}.txt").write_text(
            "".join(f"{key}={format_value(result[name][key])}\n" for key, _ in keys),
            encoding="utf-8",
        )


def write_error(out_dir: Path, kind: str, message: str) -> None:
    """エラーのとき。kind は input(パラメータ・期間の誤り)か data(データの異常)。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    one_line = " ".join(message.splitlines())
    (out_dir / "error.txt").write_text(f"kind={kind}\nmessage={one_line}\n", encoding="utf-8")


def read_outputs(out_dir: Path) -> dict[str, Any]:
    """出力のファイルを読み、to_contract_dict と同じ形の dict にする。エラーなら {"error": {...}}。"""
    error = out_dir / "error.txt"
    if error.exists():
        return {"error": read_key_values(error)}
    result: dict[str, Any] = {}
    for name, columns in TABLES.items():
        path = out_dir / f"{name}.csv"
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            expected = [column for column, _ in columns]
            if header != expected:
                raise ValueError(f"{path.name} の見出しが違います: {header}(正しくは {expected})")
            result[name] = [
                {
                    column: parse_value(text, kind)
                    for (column, kind), text in zip(columns, row, strict=True)
                }
                for row in reader
                if row
            ]
    for name, keys in KEY_VALUES.items():
        values = read_key_values(out_dir / f"{name}.txt")
        result[name] = {key: parse_value(values.get(key, ""), kind) for key, kind in keys}
    return result

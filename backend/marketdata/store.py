"""取得したデータを Parquet で保存・読み込みする(docs/mvp.md 3.3「保存と更新のルール」)。

- 保存するのは未調整の値・調整係数・権利落ちの種類だけ。調整済み株価は保存しない
  (新しい分割があると過去の値までさかのぼって書き換わるため)
- 取得日時は Parquet ファイル自身のメタデータに書く。別ファイルで管理すると、片方だけ更新されて食い違うことがあるため
- 保存先(既定は data/)は Git 管理外。J-Quants のデータは私的使用のみで、配布できない(3.2)
"""

from __future__ import annotations

import datetime as dt
import os
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from backend.marketdata.models import DailyBar, SymbolId, SymbolInfo

SCHEMA_VERSION = "1"

BAR_SCHEMA = pa.schema(
    [
        pa.field("date", pa.date32(), nullable=False),
        pa.field("open", pa.float64()),
        pa.field("high", pa.float64()),
        pa.field("low", pa.float64()),
        pa.field("close", pa.float64()),
        pa.field("volume", pa.float64()),
        pa.field("turnover", pa.float64()),
        pa.field("adj_factor", pa.float64()),
        pa.field("ex_rt", pa.int8()),
        pa.field("upper_limit", pa.bool_()),
        pa.field("lower_limit", pa.bool_()),
    ]
)

SYMBOL_SCHEMA = pa.schema(
    [
        pa.field("symbol_id", pa.string(), nullable=False),
        pa.field("name", pa.string(), nullable=False),
        pa.field("name_en", pa.string()),
        pa.field("segment", pa.string()),
        pa.field("sector", pa.string()),
    ]
)

_BAR_COLUMNS = [field.name for field in BAR_SCHEMA]


class ParquetStore:
    """1つのデータソース分の保存場所(例: data/jquants)。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # --- 日足 ---

    def bars_path(self, symbol_id: SymbolId) -> Path:
        return self.root / "bars" / f"{symbol_id.filename_stem()}.parquet"

    def write_bars(
        self, symbol_id: SymbolId, bars: list[DailyBar], fetched_at: dt.datetime
    ) -> None:
        columns: dict[str, list[object]] = {name: [] for name in _BAR_COLUMNS}
        for bar in sorted(bars, key=lambda b: b.date):
            for name in _BAR_COLUMNS:
                columns[name].append(getattr(bar, name))
        table = pa.table(columns, schema=BAR_SCHEMA).replace_schema_metadata(
            _metadata(fetched_at, symbol_id=str(symbol_id))
        )
        _write_atomically(table, self.bars_path(symbol_id))

    def read_bars(self, symbol_id: SymbolId) -> list[DailyBar] | None:
        path = self.bars_path(symbol_id)
        if not path.exists():
            return None
        table = pq.read_table(path)
        rows = table.to_pylist()
        return [DailyBar(**{name: row[name] for name in _BAR_COLUMNS}) for row in rows]

    def bars_fetched_at(self, symbol_id: SymbolId) -> dt.datetime | None:
        return _read_fetched_at(self.bars_path(symbol_id))

    # --- 銘柄一覧 ---

    @property
    def symbols_path(self) -> Path:
        return self.root / "symbols.parquet"

    def write_symbols(self, symbols: list[SymbolInfo], fetched_at: dt.datetime) -> None:
        table = pa.table(
            {
                "symbol_id": [str(s.symbol_id) for s in symbols],
                "name": [s.name for s in symbols],
                "name_en": [s.name_en for s in symbols],
                "segment": [s.segment for s in symbols],
                "sector": [s.sector for s in symbols],
            },
            schema=SYMBOL_SCHEMA,
        ).replace_schema_metadata(_metadata(fetched_at))
        _write_atomically(table, self.symbols_path)

    def read_symbols(self) -> list[SymbolInfo] | None:
        if not self.symbols_path.exists():
            return None
        rows = pq.read_table(self.symbols_path).to_pylist()
        return [
            SymbolInfo(
                symbol_id=SymbolId.parse(row["symbol_id"]),
                name=row["name"],
                name_en=row["name_en"],
                segment=row["segment"],
                sector=row["sector"],
            )
            for row in rows
        ]

    def symbols_fetched_at(self) -> dt.datetime | None:
        return _read_fetched_at(self.symbols_path)

    def cached_symbol_ids(self) -> list[SymbolId]:
        """日足を保存済みの銘柄。"""
        bars_dir = self.root / "bars"
        if not bars_dir.exists():
            return []
        ids = []
        for path in sorted(bars_dir.glob("*.parquet")):
            market, _, code = path.stem.partition("_")
            try:
                ids.append(SymbolId.parse(f"{market}:{code}"))
            except ValueError:
                continue
        return ids


def _metadata(fetched_at: dt.datetime, **extra: str) -> dict[bytes, bytes]:
    if fetched_at.tzinfo is None:
        raise ValueError("fetched_at にはタイムゾーン付きの日時を渡してください")
    metadata = {"fetched_at": fetched_at.isoformat(), "schema_version": SCHEMA_VERSION}
    metadata.update(extra)
    return {key.encode(): value.encode() for key, value in metadata.items()}


def _read_fetched_at(path: Path) -> dt.datetime | None:
    if not path.exists():
        return None
    metadata = pq.read_schema(path).metadata or {}
    raw = metadata.get(b"fetched_at")
    return dt.datetime.fromisoformat(raw.decode()) if raw else None


def _write_atomically(table: pa.Table, path: Path) -> None:
    """一時ファイルに書いてから置き換える。書き込み中に止まっても、壊れたファイルが残らないようにするため。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    os.close(fd)
    try:
        pq.write_table(table, tmp_name)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise

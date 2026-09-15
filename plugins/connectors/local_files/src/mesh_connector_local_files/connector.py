from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.json as pa_json
import pyarrow.parquet as pq

from mesh_common.schemas import ColumnSchema, TableSchema

__version__ = "0.1.0"

_FORMATS = {
    ".csv": "csv",
    ".tsv": "csv",
    ".parquet": "parquet",
    ".pq": "parquet",
    ".json": "json",
    ".jsonl": "json",
    ".ndjson": "json",
}


def _safe_name(path: Path, root: Path, used: set[str]) -> str:
    stem = re.sub(r"[^A-Za-z0-9_]", "_", path.stem).lower()
    if not stem or stem[0].isdigit():
        stem = f"t_{stem}" if stem else "table"
    name = stem
    if name in used:
        rel = path.relative_to(root).with_suffix("")
        name = re.sub(r"[^A-Za-z0-9_]", "_", str(rel)).lower()
        if not name or name[0].isdigit():
            name = f"t_{name}" if name else "table"
    original = name
    suffix = 2
    while name in used:
        name = f"{original}_{suffix}"
        suffix += 1
    used.add(name)
    return name


def _read_table(path: Path) -> pa.Table:
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        parse_options = pa_csv.ParseOptions(delimiter="\t" if suffix == ".tsv" else ",")
        return pa_csv.read_csv(path, parse_options=parse_options)
    if suffix in {".parquet", ".pq"}:
        return pq.read_table(path)
    if suffix in {".json", ".jsonl", ".ndjson"}:
        text = path.read_text(encoding="utf-8").lstrip()
        if text.startswith("["):
            rows = json.loads(text)
            if not isinstance(rows, list):
                raise ValueError(f"{path} JSON root must be an array of objects")
            return pa.Table.from_pylist(rows)
        return pa_json.read_json(path)
    raise ValueError(f"unsupported file type: {path}")


class LocalFilesConnector:
    def __init__(
        self,
        root: Path | str,
        connector_id: str = "local_files",
        labels: list[str] | None = None,
    ) -> None:
        self.root = Path(root)
        self.id = connector_id
        self.version = __version__
        self.sensitivity_labels = list(labels or [])

    def discover_schema(self) -> list[TableSchema]:
        if not self.root.exists():
            return []
        used: set[str] = set()
        tables: list[TableSchema] = []
        for path in sorted(self.root.rglob("*"), key=lambda item: (len(item.relative_to(self.root).parts), str(item))):
            if not path.is_file() or path.suffix.lower() not in _FORMATS:
                continue
            table = _read_table(path)
            tables.append(
                TableSchema(
                    name=_safe_name(path, self.root, used),
                    connector_id=self.id,
                    columns=[ColumnSchema(name=field.name, type=str(field.type)) for field in table.schema],
                    source_path=str(path.resolve()),
                    format=_FORMATS[path.suffix.lower()],
                )
            )
        return tables

    def scan(
        self,
        table_or_path: str,
        projection: list[str] | None = None,
        filter_expr: str | None = None,
    ) -> Iterator[pa.RecordBatch]:
        del filter_expr
        source = self._resolve(table_or_path)
        table = _read_table(source)
        if projection:
            table = table.select(projection)
        for batch in table.to_batches():
            yield batch

    def _resolve(self, table_or_path: str) -> Path:
        candidate = Path(table_or_path)
        if candidate.exists():
            return candidate
        for table in self.discover_schema():
            if table.name == table_or_path and table.source_path:
                return Path(table.source_path)
        raise FileNotFoundError(f"unknown table or path: {table_or_path}")

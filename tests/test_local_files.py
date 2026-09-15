from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from mesh_connector_local_files import LocalFilesConnector


def _write_sample_files(root: Path, sales_csv_text: str) -> None:
    (root / "sales.csv").write_text(sales_csv_text)
    table = pa.table({"sku": ["a", "b"], "qty": [1, 2]})
    pq.write_table(table, root / "inventory.parquet")
    (root / "regions.json").write_text(
        json.dumps([{"region": "west", "code": "W"}, {"region": "east", "code": "E"}])
    )
    (root / "notes.txt").write_text("ignore me")


def test_discovers_csv_parquet_json(tmp_path: Path, sales_csv_text: str):
    _write_sample_files(tmp_path, sales_csv_text)
    connector = LocalFilesConnector(root=tmp_path, connector_id="local_files")
    tables = {t.name: t for t in connector.discover_schema()}

    assert set(tables) == {"sales", "inventory", "regions"}
    assert tables["sales"].format == "csv"
    assert tables["inventory"].format == "parquet"
    assert tables["regions"].format == "json"
    assert "order_id" in {c.name for c in tables["sales"].columns}
    assert connector.id == "local_files"
    assert connector.version


def test_scan_returns_arrow_batches(tmp_path: Path, sales_csv_text: str):
    _write_sample_files(tmp_path, sales_csv_text)
    connector = LocalFilesConnector(root=tmp_path)
    batches = list(connector.scan("sales"))
    assert batches
    table = pa.Table.from_batches(batches)
    assert table.num_rows == 6
    assert "product" in table.column_names


def test_scan_projection(tmp_path: Path, sales_csv_text: str):
    _write_sample_files(tmp_path, sales_csv_text)
    connector = LocalFilesConnector(root=tmp_path)
    table = pa.Table.from_batches(list(connector.scan("sales", projection=["product", "amount"])))
    assert table.column_names == ["product", "amount"]


def test_ignores_unknown_extensions(tmp_path: Path, sales_csv_text: str):
    _write_sample_files(tmp_path, sales_csv_text)
    connector = LocalFilesConnector(root=tmp_path)
    names = {t.name for t in connector.discover_schema()}
    assert "notes" not in names

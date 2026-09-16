from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from mesh_common.uploads import UPLOADS_DIRNAME
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


def test_nested_duplicate_stems_get_unique_table_names(tmp_path: Path, sales_csv_text: str):
    (tmp_path / "sales.csv").write_text(sales_csv_text)
    nested = tmp_path / "node-b"
    nested.mkdir()
    (nested / "sales.csv").write_text(
        "order_id,product,region,amount,sold_on\n1,babylon-sprocket,west,99.0,2026-02-01\n"
    )
    tables = LocalFilesConnector(root=tmp_path).discover_schema()
    names = [item.name for item in tables]
    assert len(names) == len(set(names))
    assert "sales" in names
    assert any(name != "sales" for name in names)


def test_example_samples_dir_exposes_sales(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    discovered = LocalFilesConnector(root=repo / "data/samples").discover_schema()
    names = [item.name for item in discovered]
    assert len(names) == len(set(names))
    tables = {item.name: item for item in discovered}
    assert "sales" in tables
    assert tables["sales"].source_path.endswith("data/samples/sales.csv")


def test_uploads_dir_defaults_under_root(tmp_path: Path):
    connector = LocalFilesConnector(root=tmp_path, connector_id="local_files")
    assert connector.uploads_dir == (tmp_path / UPLOADS_DIRNAME).resolve()


def test_ignores_unknown_extensions(tmp_path: Path, sales_csv_text: str):
    _write_sample_files(tmp_path, sales_csv_text)
    connector = LocalFilesConnector(root=tmp_path)
    names = {t.name for t in connector.discover_schema()}
    assert "notes" not in names

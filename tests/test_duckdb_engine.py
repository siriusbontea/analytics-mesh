from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from mesh_common.schemas import QueryPlan, TableSchema
from mesh_connector_local_files import LocalFilesConnector
from mesh_engine_duckdb import DuckDBEngine, SqlGuardError


def _plan(data_dir: Path, artifact_dir: Path, sql: str, row_limit: int = 100) -> QueryPlan:
    connector = LocalFilesConnector(root=data_dir)
    return QueryPlan(
        sql=sql,
        row_limit=row_limit,
        timeout_seconds=10,
        artifact_dir=artifact_dir,
        tables=connector.discover_schema(),
    )


def test_sql_over_csv_writes_parquet_artifact(data_dir: Path, tmp_path: Path):
    engine = DuckDBEngine()
    artifact = engine.execute(
        _plan(
            data_dir,
            tmp_path / "artifacts",
            "SELECT product, SUM(amount) AS total FROM sales GROUP BY product",
        )
    )
    assert artifact.format == "parquet"
    assert artifact.row_count == 3
    assert Path(artifact.path).is_file()
    table = pq.read_table(artifact.path)
    assert table.num_rows == 3
    assert artifact.sha256
    assert engine.id == "duckdb"
    assert engine.version


def test_row_limit_applied(data_dir: Path, tmp_path: Path):
    engine = DuckDBEngine()
    artifact = engine.execute(_plan(data_dir, tmp_path / "artifacts", "SELECT * FROM sales", row_limit=2))
    assert artifact.row_count == 2


def test_rejects_insert(data_dir: Path, tmp_path: Path):
    engine = DuckDBEngine()
    with pytest.raises(SqlGuardError):
        engine.execute(_plan(data_dir, tmp_path / "artifacts", "INSERT INTO sales VALUES (99, 'x', 'y', 1, '2026-01-01')"))


def test_rejects_file_read_function(data_dir: Path, tmp_path: Path):
    engine = DuckDBEngine()
    with pytest.raises(SqlGuardError):
        engine.execute(_plan(data_dir, tmp_path / "artifacts", "SELECT * FROM read_csv_auto('sales.csv')"))

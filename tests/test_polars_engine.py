from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from mesh_common.schemas import QueryPlan, TableSchema
from mesh_connector_local_files import LocalFilesConnector
from mesh_engine_duckdb import SqlGuardError
from mesh_engine_polars import PolarsEngine
from mesh_node.app import create_app
from mesh_node.config import ConnectorConfig, LimitsConfig, NodeConfig
from mesh_node.runtime import NodeRuntime

REPO = Path(__file__).resolve().parents[1]


def _plan(data_dir: Path, artifact_dir: Path, sql: str, row_limit: int = 100) -> QueryPlan:
    connector = LocalFilesConnector(root=data_dir)
    return QueryPlan(
        sql=sql,
        row_limit=row_limit,
        timeout_seconds=10,
        artifact_dir=artifact_dir,
        tables=connector.discover_schema(),
    )


def test_polars_sql_over_csv_writes_parquet(data_dir: Path, tmp_path: Path):
    engine = PolarsEngine()
    artifact = engine.execute(
        _plan(
            data_dir,
            tmp_path / "artifacts",
            "SELECT product, SUM(amount) AS total FROM sales GROUP BY product",
        )
    )
    assert engine.id == "polars"
    assert engine.version
    assert artifact.format == "parquet"
    assert artifact.row_count == 3
    assert Path(artifact.path).is_file()
    table = pq.read_table(artifact.path)
    assert table.num_rows == 3
    assert "product" in table.column_names
    assert "total" in table.column_names


def test_polars_row_limit_and_arrow_tables(tmp_path: Path):
    engine = PolarsEngine()
    artifact = engine.execute(
        QueryPlan(
            sql="SELECT n FROM nums",
            row_limit=2,
            timeout_seconds=5,
            artifact_dir=tmp_path / "artifacts",
            tables=[TableSchema(name="nums", connector_id="mem", format="postgres")],
        ),
        arrow_tables={"nums": pa.table({"n": [1, 2, 3]})},
    )
    assert artifact.row_count == 2


def test_polars_rejects_dml(data_dir: Path, tmp_path: Path):
    engine = PolarsEngine()
    with pytest.raises(SqlGuardError):
        engine.execute(_plan(data_dir, tmp_path / "artifacts", "DELETE FROM sales"))


def test_run_polars_analytic_via_node(tmp_path: Path, data_dir: Path):
    cfg = NodeConfig(
        node_id="polars-node",
        artifact_dir=tmp_path / "artifacts",
        receipt_db=tmp_path / "receipts.sqlite",
        connectors=[ConnectorConfig(id="local_files", type="local_files", root=data_dir)],
        limits=LimitsConfig(default_row_limit=100, max_row_limit=1000, query_timeout_seconds=10),
        analytics_dir=REPO / "analytics",
    )
    runtime = NodeRuntime(cfg)
    assert "duckdb" in runtime.engines
    assert "polars" in runtime.engines
    assert runtime.engine.id == "duckdb"
    client = TestClient(create_app(cfg))
    listed = client.get("/analytics").json()["analytics"]
    ids = {item["analytic_id"] for item in listed}
    assert "top_products_polars" in ids
    response = client.post("/analytics/run", json={"analytic_id": "top_products_polars", "principal": "tester"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["artifact"]["row_count"] == 3
    assert body["receipt"]["action"] == "run_analytic"
    assert body["receipt"]["status"] == "succeeded"
    assert "polars" in body["receipt"]["engine_version"] or body["receipt"]["params"]["engine"] == "polars"

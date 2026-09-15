from __future__ import annotations

import os
from pathlib import Path

import pytest

from mesh_connector_postgres.sql import (
    discover_columns_sql,
    quote_ident,
    select_sql,
)
from mesh_node.config import ConnectorConfig, NodeConfig


def test_quote_ident_rejects_unsafe_names():
    assert quote_ident("sales") == '"sales"'
    assert quote_ident("public") == '"public"'
    with pytest.raises(ValueError):
        quote_ident('sales"; DROP TABLE t; --')
    with pytest.raises(ValueError):
        quote_ident("order-id")


def test_select_sql_is_read_only_projection():
    sql = select_sql("public", "sales", ["product", "amount"])
    assert sql == 'SELECT "product", "amount" FROM "public"."sales"'
    assert "INSERT" not in sql
    assert "UPDATE" not in sql
    star = select_sql("analytics", "facts")
    assert star == 'SELECT * FROM "analytics"."facts"'


def test_discover_columns_sql_filters_schemas():
    sql, params = discover_columns_sql(["public", "analytics"])
    assert "information_schema.columns" in sql.lower()
    assert params == ["public", "analytics"]
    assert "INSERT" not in sql.upper()


def test_postgres_connector_config_uses_dsn_env(tmp_path: Path):
    cfg = NodeConfig(
        node_id="pg-node",
        artifact_dir=tmp_path / "artifacts",
        receipt_db=tmp_path / "receipts.sqlite",
        connectors=[
            ConnectorConfig(
                id="sales_pg",
                type="postgres",
                dsn_env="MESH_POSTGRES_DSN",
                schemas=["public"],
                labels=["work"],
            )
        ],
    )
    item = cfg.connectors[0]
    assert item.type == "postgres"
    assert item.root is None
    assert item.dsn_env == "MESH_POSTGRES_DSN"
    assert item.schemas == ["public"]


def test_postgres_connector_builds_without_live_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from mesh_connector_postgres import PostgresConnector

    monkeypatch.setenv("MESH_POSTGRES_DSN", "postgresql://mesh:mesh@127.0.0.1:5432/mesh")
    connector = PostgresConnector(
        connector_id="sales_pg",
        dsn_env="MESH_POSTGRES_DSN",
        schemas=["public"],
        labels=["work"],
    )
    assert connector.id == "sales_pg"
    assert connector.dsn.startswith("postgresql://")
    assert connector.version
    assert "work" in connector.sensitivity_labels


@pytest.mark.integration
def test_postgres_discover_and_scan_live():
    dsn = os.environ.get("MESH_POSTGRES_DSN")
    container = None
    if not dsn:
        try:
            from testcontainers.postgres import PostgresContainer
        except ImportError:
            pytest.skip("MESH_POSTGRES_DSN unset and testcontainers not installed")
        try:
            container = PostgresContainer("postgres:16-alpine")
            container.start()
            dsn = container.get_connection_url()
            if dsn.startswith("postgresql+psycopg2://"):
                dsn = dsn.replace("postgresql+psycopg2://", "postgresql://", 1)
        except Exception as exc:  # noqa: BLE001 — optional live DB
            pytest.skip(f"could not start postgres container: {exc}")
    try:
        import psycopg

        from mesh_connector_postgres import PostgresConnector

        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS sales (product text, amount numeric)")
            conn.execute("DELETE FROM sales")
            conn.execute("INSERT INTO sales (product, amount) VALUES ('widget', 12.5), ('gadget', 30)")

        connector = PostgresConnector(connector_id="sales_pg", dsn=dsn, schemas=["public"])
        tables = connector.discover_schema()
        names = {table.name for table in tables}
        assert "sales" in names
        sales = next(table for table in tables if table.name == "sales")
        assert sales.format == "postgres"
        batches = list(connector.scan("sales", projection=["product", "amount"]))
        rows = [dict(zip(batch.schema.names, row)) for batch in batches for row in zip(*[col.to_pylist() for col in batch.columns])]
        products = {row["product"] for row in rows}
        assert products == {"widget", "gadget"}
    finally:
        if container is not None:
            container.stop()

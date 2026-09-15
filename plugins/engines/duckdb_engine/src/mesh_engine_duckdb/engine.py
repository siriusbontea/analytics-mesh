from __future__ import annotations

import re
import threading
from pathlib import Path
from uuid import uuid4

import duckdb
import pyarrow.parquet as pq

from typing import Any

from mesh_common.hashing import sha256_file
from mesh_common.schemas import ArtifactRef, QueryPlan, TableSchema
from mesh_engine_duckdb.sql_guard import SqlGuardError, validate_sql

__version__ = "0.1.0"


def _quote_ident(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise SqlGuardError(f"invalid table name: {name}")
    return name


def _quote_path(path: str) -> str:
    return path.replace("'", "''")


def _view_sql(table: TableSchema) -> str:
    if not table.source_path:
        raise SqlGuardError(f"table {table.name} has no source_path")
    ident = _quote_ident(table.name)
    path = _quote_path(table.source_path)
    if table.format == "csv":
        reader = f"read_csv_auto('{path}')"
    elif table.format == "parquet":
        reader = f"read_parquet('{path}')"
    elif table.format == "json":
        reader = f"read_json_auto('{path}')"
    else:
        raise SqlGuardError(f"unsupported table format: {table.format}")
    return f"CREATE TABLE {ident} AS SELECT * FROM {reader}"


class DuckDBEngine:
    id = "duckdb"
    version = __version__

    def execute(self, plan: QueryPlan, arrow_tables: dict[str, Any] | None = None) -> ArtifactRef:
        sql = validate_sql(plan.sql)
        artifact_dir = Path(plan.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        registered = arrow_tables or {}

        con = duckdb.connect(":memory:")
        try:
            con.execute("SET enable_progress_bar = false")
            con.execute("SET memory_limit = '256MB'")
            for table in plan.tables:
                if table.name in registered:
                    con.register(_quote_ident(table.name), registered[table.name])
                elif table.format in {"csv", "parquet", "json"}:
                    con.execute(_view_sql(table))
                else:
                    raise SqlGuardError(f"table {table.name} has no scan data")
            con.execute("SET enable_external_access = false")

            wrapped = f"SELECT * FROM (\n{sql}\n) AS _mesh_q LIMIT {int(plan.row_limit)}"
            timer = threading.Timer(plan.timeout_seconds, con.interrupt)
            timer.start()
            try:
                arrow = con.sql(wrapped).to_arrow_table()
            finally:
                timer.cancel()
        finally:
            con.close()

        artifact_id = str(uuid4())
        path = artifact_dir / f"{artifact_id}.parquet"
        pq.write_table(arrow, path)
        return ArtifactRef(
            artifact_id=artifact_id,
            path=str(path.resolve()),
            format="parquet",
            sha256=sha256_file(path),
            row_count=arrow.num_rows,
            column_names=list(arrow.column_names),
        )

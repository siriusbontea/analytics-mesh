from __future__ import annotations

import os
from collections.abc import Iterator

import pyarrow as pa

from mesh_common.schemas import ColumnSchema, TableSchema
from mesh_connector_postgres.sql import discover_columns_sql, select_sql

__version__ = "0.1.0"


class PostgresConnector:
    """Read-only Postgres connector. Engines pull Arrow batches; this plugin never runs user SQL."""

    def __init__(
        self,
        connector_id: str = "postgres",
        dsn: str | None = None,
        dsn_env: str | None = None,
        schemas: list[str] | None = None,
        labels: list[str] | None = None,
    ) -> None:
        self.id = connector_id
        self.version = __version__
        self.sensitivity_labels = list(labels or [])
        self.schemas = list(schemas or ["public"])
        env_name = dsn_env or "MESH_POSTGRES_DSN"
        self.dsn = dsn or os.environ.get(env_name, "")
        if not self.dsn:
            raise ValueError(f"postgres DSN missing (set dsn or {env_name})")
        self._table_map: dict[str, tuple[str, str]] = {}

    def discover_schema(self) -> list[TableSchema]:
        import psycopg

        sql, params = discover_columns_sql(self.schemas)
        with psycopg.connect(self.dsn) as conn:
            conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
            rows = conn.execute(sql, params).fetchall()

        grouped: dict[tuple[str, str], list[ColumnSchema]] = {}
        for schema, table, column, data_type, _ord in rows:
            grouped.setdefault((schema, table), []).append(ColumnSchema(name=column, type=str(data_type)))

        used: set[str] = set()
        tables: list[TableSchema] = []
        self._table_map = {}
        multi = len({schema for schema, _table in grouped}) > 1
        for (schema, table), columns in grouped.items():
            name = f"{schema}_{table}" if multi and schema != "public" else table
            original = name
            suffix = 2
            while name in used:
                name = f"{original}_{suffix}"
                suffix += 1
            used.add(name)
            self._table_map[name] = (schema, table)
            tables.append(
                TableSchema(
                    name=name,
                    connector_id=self.id,
                    columns=columns,
                    source_path=f"{schema}.{table}",
                    format="postgres",
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
        import psycopg

        schema, table = self._resolve(table_or_path)
        sql = select_sql(schema, table, projection)
        with psycopg.connect(self.dsn) as conn:
            conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
            result = conn.execute(sql)
            cols = [desc.name for desc in (result.description or [])]
            data = result.fetchall()
        if not data:
            empty = pa.Table.from_arrays([pa.array([], type=pa.string()) for _ in cols], names=cols)
            for batch in empty.to_batches():
                yield batch
            return
        arrow = pa.Table.from_pylist([dict(zip(cols, row, strict=True)) for row in data])
        yield from arrow.to_batches()

    def _resolve(self, table_or_path: str) -> tuple[str, str]:
        if "." in table_or_path and table_or_path not in self._table_map:
            schema, table = table_or_path.split(".", 1)
            return schema, table
        if table_or_path in self._table_map:
            return self._table_map[table_or_path]
        if not self._table_map:
            self.discover_schema()
        if table_or_path in self._table_map:
            return self._table_map[table_or_path]
        raise FileNotFoundError(f"unknown postgres table: {table_or_path}")

"""Sandboxed DuckDB SQL engine."""

from mesh_engine_duckdb.engine import DuckDBEngine
from mesh_engine_duckdb.sql_guard import SqlGuardError, validate_sql

__version__ = "0.1.0"

__all__ = ["DuckDBEngine", "SqlGuardError", "validate_sql"]

"""Read-only Postgres connector."""

from mesh_connector_postgres.connector import PostgresConnector
from mesh_connector_postgres.sql import discover_columns_sql, quote_ident, select_sql

__version__ = "0.1.0"

__all__ = ["PostgresConnector", "discover_columns_sql", "quote_ident", "select_sql"]

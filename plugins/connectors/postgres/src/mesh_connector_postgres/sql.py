from __future__ import annotations

import re

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_ident(name: str) -> str:
    if not _IDENT.fullmatch(name):
        raise ValueError(f"invalid identifier: {name}")
    return f'"{name}"'


def select_sql(schema: str, table: str, projection: list[str] | None = None) -> str:
    cols = ", ".join(quote_ident(column) for column in projection) if projection else "*"
    return f"SELECT {cols} FROM {quote_ident(schema)}.{quote_ident(table)}"


def discover_columns_sql(schemas: list[str]) -> tuple[str, list[str]]:
    placeholders = ", ".join(["%s"] * len(schemas))
    sql = (
        "SELECT table_schema, table_name, column_name, data_type, ordinal_position "
        "FROM information_schema.columns "
        f"WHERE table_schema IN ({placeholders}) "
        "ORDER BY table_schema, table_name, ordinal_position"
    )
    return sql, list(schemas)

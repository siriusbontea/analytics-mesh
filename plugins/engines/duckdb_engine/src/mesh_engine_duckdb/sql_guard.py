from __future__ import annotations

import re

class SqlGuardError(ValueError):
    """Raised when SQL is not a single sandboxed SELECT."""


_COMMENT_LINE = re.compile(r"--[^\n]*")
_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_FORBIDDEN = re.compile(
    r"\b("
    r"ATTACH|DETACH|INSTALL|LOAD|PRAGMA|CREATE|DROP|INSERT|UPDATE|DELETE|ALTER|"
    r"COPY|EXPORT|IMPORT|CALL|CHECKPOINT|VACUUM|MERGE|REPLACE|TRUNCATE|GRANT|REVOKE|"
    r"SET|RESET|USE|BEGIN|COMMIT|ROLLBACK|PREPARE|EXECUTE|DEALLOCATE|"
    r"SECRET|PIVOT|UNPIVOT|"
    r"READ_CSV|READ_CSV_AUTO|READ_PARQUET|READ_JSON|READ_JSON_AUTO|READ_NDJSON|"
    r"GLOB|PARQUET_SCAN|DELTA_SCAN|ICEBERG"
    r")\b",
    re.IGNORECASE,
)


def strip_sql_comments(sql: str) -> str:
    return _COMMENT_LINE.sub("", _COMMENT_BLOCK.sub("", sql))


def validate_sql(sql: str) -> str:
    stripped = strip_sql_comments(sql).strip()
    if not stripped:
        raise SqlGuardError("empty SQL")
    if ";" in stripped.rstrip(";"):
        raise SqlGuardError("multiple statements are not allowed")
    stripped = stripped.rstrip(";").strip()
    if _FORBIDDEN.search(stripped):
        raise SqlGuardError("SQL contains a disallowed statement or file function")
    if not re.match(r"^(SELECT|WITH)\b", stripped, re.IGNORECASE):
        raise SqlGuardError("only SELECT / WITH queries are allowed")
    return stripped

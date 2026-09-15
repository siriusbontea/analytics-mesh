from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from mesh_common.schemas import ResultPreview

DEFAULT_PREVIEW_ROWS = 200


def preview_parquet(path: Path | str, limit: int = DEFAULT_PREVIEW_ROWS) -> ResultPreview:
    table = pq.read_table(path)
    truncated = table.num_rows > limit
    sliced = table.slice(0, limit) if truncated else table
    rows = [{key: _json_cell(value) for key, value in row.items()} for row in sliced.to_pylist()]
    return ResultPreview(
        columns=list(table.column_names),
        rows=rows,
        row_count=table.num_rows,
        truncated=truncated,
    )


def _json_cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value

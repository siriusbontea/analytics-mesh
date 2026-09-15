from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Literal

from mesh_common.schemas import ResultPreview

MAX_BARS = 24

PreviewLike = ResultPreview | dict[str, Any] | None
ColumnKind = Literal["numeric", "label", "empty"]


@dataclass(frozen=True)
class BarChartSeries:
    """Columns and values for a simple categorical bar chart."""

    label_column: str
    value_column: str
    labels: list[str]
    values: list[float]


def pick_bar_chart(preview: PreviewLike, *, max_bars: int = MAX_BARS) -> BarChartSeries | None:
    """First string-ish column as labels, first numeric column as values.

    Returns None when the preview has no usable categorical + numeric pair,
    no finite plotted rows, or more than ``max_bars`` rows (too crowded).
    """
    columns, rows = _preview_parts(preview)
    if not columns or not rows:
        return None

    kinds = {column: _column_kind(rows, column) for column in columns}
    label_column = next((column for column in columns if kinds[column] == "label"), None)
    value_column = next((column for column in columns if kinds[column] == "numeric"), None)
    if label_column is None or value_column is None:
        return None

    labels: list[str] = []
    values: list[float] = []
    for row in rows:
        label = row.get(label_column)
        number = _as_number(row.get(value_column))
        if _is_missing(label) or number is None:
            continue
        labels.append(str(label))
        values.append(number)

    if not labels or len(labels) > max_bars:
        return None
    return BarChartSeries(
        label_column=label_column,
        value_column=value_column,
        labels=labels,
        values=values,
    )


def _preview_parts(preview: PreviewLike) -> tuple[list[str], list[dict[str, Any]]]:
    if preview is None:
        return [], []
    if isinstance(preview, ResultPreview):
        return list(preview.columns), list(preview.rows)
    columns = preview.get("columns") or []
    rows = preview.get("rows") or []
    return list(columns), list(rows)


def _column_kind(rows: Iterable[dict[str, Any]], column: str) -> ColumnKind:
    saw_value = False
    for row in rows:
        value = row.get(column)
        if _is_missing(value):
            continue
        saw_value = True
        if _as_number(value) is None:
            return "label"
    return "numeric" if saw_value else "empty"


def _as_number(value: Any) -> float | None:
    if _is_missing(value) or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")

from __future__ import annotations

from mesh_common.chart import MAX_BARS, pick_bar_chart
from mesh_common.schemas import ResultPreview


def test_picks_first_string_column_and_first_numeric_column():
    preview = ResultPreview(
        columns=["product", "total"],
        rows=[
            {"product": "gadget", "total": 60.0},
            {"product": "widget", "total": 37.5},
            {"product": "sprocket", "total": 8.0},
        ],
        row_count=3,
    )
    series = pick_bar_chart(preview)
    assert series is not None
    assert series.label_column == "product"
    assert series.value_column == "total"
    assert series.labels == ["gadget", "widget", "sprocket"]
    assert series.values == [60.0, 37.5, 8.0]


def test_skips_leading_numeric_column_when_a_label_column_follows():
    preview = ResultPreview(
        columns=["order_id", "product", "amount"],
        rows=[
            {"order_id": 1, "product": "widget", "amount": 12.5},
            {"order_id": 2, "product": "gadget", "amount": 30.0},
        ],
        row_count=2,
    )
    series = pick_bar_chart(preview)
    assert series is not None
    assert series.label_column == "product"
    assert series.value_column == "order_id"
    assert series.labels == ["widget", "gadget"]
    assert series.values == [1.0, 2.0]


def test_treats_numeric_strings_as_values_not_labels():
    preview = {
        "columns": ["region", "total"],
        "rows": [
            {"region": "west", "total": "42"},
            {"region": "east", "total": "11.5"},
        ],
    }
    series = pick_bar_chart(preview)
    assert series is not None
    assert series.label_column == "region"
    assert series.value_column == "total"
    assert series.values == [42.0, 11.5]


def test_hides_when_only_numeric_columns():
    preview = ResultPreview(
        columns=["a", "b"],
        rows=[{"a": 1, "b": 2}, {"a": 3, "b": 4}],
        row_count=2,
    )
    assert pick_bar_chart(preview) is None


def test_hides_when_only_label_columns():
    preview = ResultPreview(
        columns=["product", "region"],
        rows=[{"product": "widget", "region": "west"}],
        row_count=1,
    )
    assert pick_bar_chart(preview) is None


def test_hides_empty_or_unusable_preview():
    assert pick_bar_chart(None) is None
    assert pick_bar_chart({"columns": ["product", "total"], "rows": []}) is None
    assert pick_bar_chart(ResultPreview(columns=[], rows=[], row_count=0)) is None
    assert (
        pick_bar_chart(
            ResultPreview(
                columns=["product", "total"],
                rows=[{"product": None, "total": None}],
                row_count=1,
            )
        )
        is None
    )


def test_hides_when_too_many_bars():
    rows = [{"product": f"p{i}", "total": float(i)} for i in range(MAX_BARS + 1)]
    preview = ResultPreview(columns=["product", "total"], rows=rows, row_count=len(rows))
    assert pick_bar_chart(preview) is None
    assert pick_bar_chart(preview, max_bars=MAX_BARS + 1) is not None


def test_drops_null_rows_but_keeps_finite_values():
    preview = ResultPreview(
        columns=["product", "total"],
        rows=[
            {"product": "keep", "total": 4},
            {"product": None, "total": 9},
            {"product": "skip-nan", "total": float("nan")},
            {"product": "also", "total": 2},
        ],
        row_count=4,
    )
    series = pick_bar_chart(preview)
    assert series is not None
    assert series.labels == ["keep", "also"]
    assert series.values == [4.0, 2.0]


def test_bool_column_is_not_numeric():
    preview = ResultPreview(
        columns=["flag", "n"],
        rows=[{"flag": True, "n": 3}, {"flag": False, "n": 1}],
        row_count=2,
    )
    series = pick_bar_chart(preview)
    assert series is not None
    assert series.label_column == "flag"
    assert series.value_column == "n"
    assert series.labels == ["True", "False"]

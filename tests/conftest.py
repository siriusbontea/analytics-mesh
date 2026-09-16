from __future__ import annotations

from pathlib import Path

import pytest

SALES_CSV = """order_id,product,region,amount,sold_on
1,widget,west,12.5,2026-01-03
2,gadget,east,30.0,2026-01-04
3,widget,east,12.5,2026-01-05
4,sprocket,west,8.0,2026-01-06
5,gadget,west,30.0,2026-01-07
6,widget,west,12.5,2026-01-08
"""


def _wants_ui_tests(config: pytest.Config) -> bool:
    """Collect @pytest.mark.ui only when asked (`-m ui` or `tests/ui`)."""
    expr = " ".join((config.option.markexpr or "").split())
    if expr == "ui" or (expr and "ui" in expr and "not ui" not in expr):
        return True
    return False


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _wants_ui_tests(config):
        return
    if items and all("ui" in item.keywords for item in items):
        return
    items[:] = [item for item in items if "ui" not in item.keywords]


@pytest.fixture
def sales_csv_text() -> str:
    return SALES_CSV


@pytest.fixture
def data_dir(tmp_path: Path, sales_csv_text: str) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    (root / "sales.csv").write_text(sales_csv_text)
    return root

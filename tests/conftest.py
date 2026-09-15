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


@pytest.fixture
def sales_csv_text() -> str:
    return SALES_CSV


@pytest.fixture
def data_dir(tmp_path: Path, sales_csv_text: str) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    (root / "sales.csv").write_text(sales_csv_text)
    return root

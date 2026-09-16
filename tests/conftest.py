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
    tokens = (config.option.markexpr or "").replace("(", " ").replace(")", " ").split()
    if "ui" not in tokens:
        return False
    for index, token in enumerate(tokens):
        if token == "ui" and index > 0 and tokens[index - 1] == "not":
            return False
    return True


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _wants_ui_tests(config):
        return
    if items and all("ui" in item.keywords for item in items):
        return
    items[:] = [item for item in items if "ui" not in item.keywords]


@pytest.fixture(autouse=True)
def _clear_pair_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep pairing tests hermetic if a developer exported MESH_PAIR_TOKEN."""
    monkeypatch.delenv("MESH_PAIR_TOKEN", raising=False)


@pytest.fixture
def sales_csv_text() -> str:
    return SALES_CSV


@pytest.fixture
def data_dir(tmp_path: Path, sales_csv_text: str) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    (root / "sales.csv").write_text(sales_csv_text)
    return root

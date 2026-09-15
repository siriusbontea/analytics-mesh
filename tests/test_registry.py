from __future__ import annotations

from pathlib import Path

import pytest

from mesh_common.registry import AnalyticRegistry, AnalyticSpecError


def _write_analytic(
    root: Path,
    analytic_id: str = "top_products",
    version: str = "1.0.0",
    sql: str = "SELECT product, SUM(amount) AS total FROM sales GROUP BY product",
    filename: str | None = None,
    extra: str = "",
) -> Path:
    name = filename or f"{analytic_id}.yaml"
    sql_name = Path(name).with_suffix(".sql").name
    (root / sql_name).write_text(sql + "\n")
    (root / name).write_text(
        f"""analytic_id: {analytic_id}
version: {version}
engine: duckdb
entry: {sql_name}
allowed_connectors:
  - local_files
description: Rank products by total sales
{extra}
"""
    )
    return root / name


def test_load_yaml_and_sql_from_directory(tmp_path: Path):
    _write_analytic(tmp_path)
    registry = AnalyticRegistry.load(tmp_path)
    specs = registry.list()
    assert len(specs) == 1
    spec = specs[0]
    assert spec.analytic_id == "top_products"
    assert spec.version == "1.0.0"
    assert spec.engine == "duckdb"
    assert spec.allowed_connectors == ["local_files"]
    assert "GROUP BY product" in spec.sql
    assert spec.entry.endswith("top_products.sql")


def test_list_and_get_by_id_picks_latest_semver(tmp_path: Path):
    _write_analytic(tmp_path, version="1.0.0", filename="top_products.yaml")
    _write_analytic(
        tmp_path,
        version="1.1.0",
        filename="top_products-1.1.0.yaml",
        sql="SELECT product FROM sales",
    )
    registry = AnalyticRegistry.load(tmp_path)
    listed = registry.list()
    assert {item.version for item in listed} == {"1.0.0", "1.1.0"}
    latest = registry.get("top_products")
    assert latest.version == "1.1.0"
    pinned = registry.get("top_products", version="1.0.0")
    assert pinned.version == "1.0.0"
    assert "GROUP BY" in pinned.sql


def test_unknown_analytic_raises(tmp_path: Path):
    _write_analytic(tmp_path)
    registry = AnalyticRegistry.load(tmp_path)
    with pytest.raises(KeyError):
        registry.get("missing")


def test_invalid_semver_rejected(tmp_path: Path):
    _write_analytic(tmp_path, version="not-a-version")
    with pytest.raises(AnalyticSpecError, match="semver"):
        AnalyticRegistry.load(tmp_path)


def test_duplicate_id_and_version_rejected(tmp_path: Path):
    _write_analytic(tmp_path, filename="a.yaml")
    _write_analytic(tmp_path, filename="b.yaml")
    with pytest.raises(AnalyticSpecError, match="duplicate"):
        AnalyticRegistry.load(tmp_path)


def test_loads_repo_example_analytics():
    repo = Path(__file__).resolve().parents[1]
    registry = AnalyticRegistry.load(repo / "analytics")
    ids = {item.analytic_id for item in registry.list()}
    assert "top_products" in ids
    assert "sales_by_region" in ids
    spec = registry.get("top_products")
    assert spec.version == "1.0.0"
    assert spec.engine == "duckdb"
    assert "FROM sales" in spec.sql

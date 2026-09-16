from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from mesh_node.app import create_app
from mesh_node.config import ConnectorConfig, LimitsConfig, NodeConfig
from mesh_plane.app import create_app as create_plane_app
from mesh_plane.config import PlaneConfig

REPO = Path(__file__).resolve().parents[1]
UI_PATH = REPO / "packages/mesh_common/src/mesh_common/static/ui.html"

HELP_SECTION_IDS = (
    "getting-started",
    "concepts",
    "cli-vs-ui",
    "receipts",
    "plane-vs-node",
    "policy",
    "mcp",
)

TIP_IDS = (
    "tip-theme",
    "tip-principal",
    "tip-node",
    "tip-kind",
    "tip-analytic",
    "tip-sql",
    "tip-propose",
    "tip-confirm",
    "tip-explain",
    "tip-run",
    "tip-connectors-refresh",
    "tip-jobs-refresh",
    "tip-jobs",
    "tip-copy-receipt",
    "tip-verify-chain",
    "tip-download",
    "tip-chart",
    "tip-upload",
)


def _node_client(tmp_path: Path, data_dir: Path) -> TestClient:
    cfg = NodeConfig(
        node_id="test-node",
        artifact_dir=tmp_path / "artifacts",
        receipt_db=tmp_path / "receipts.sqlite",
        connectors=[ConnectorConfig(id="local_files", type="local_files", root=data_dir, labels=["personal"])],
        limits=LimitsConfig(default_row_limit=100, max_row_limit=1000, query_timeout_seconds=10),
        analytics_dir=REPO / "analytics",
    )
    return TestClient(create_app(cfg))


def test_help_drawer_hooks_in_static_file():
    html = UI_PATH.read_text(encoding="utf-8")
    assert 'id="helpBtn"' in html
    assert 'id="helpDrawer"' in html
    assert 'id="helpClose"' in html
    assert 'id="helpBackdrop"' in html
    assert 'id="helpSearch"' in html
    assert 'id="helpNav"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-controls="helpDrawer"' in html
    assert ".help-drawer[hidden]" in html
    assert "setPageInert" in html
    assert "#help" in html
    assert "#help=" in html
    for section in HELP_SECTION_IDS:
        assert f'id="help-{section}"' in html
        assert f'data-help-section="{section}"' in html
        assert f'data-help-nav="{section}"' in html


def test_help_content_matches_product_behavior():
    html = UI_PATH.read_text(encoding="utf-8").lower()
    assert "propose" in html and "confirm" in html
    assert "never auto-exec" in html or "never auto-executes" in html
    assert "hash chain" in html or "hash-chain" in html
    assert "source tables" in html
    assert "pointers" in html
    assert "list_analytics" in html
    assert "run_analytic" in html
    assert "get_receipt" in html
    assert "allowlist" in html
    assert "uv run mesh" in html
    assert "zero" in html and "llm" in html
    assert "ollama" in html or "node-with-models" in html
    assert "xai_api_key" in html or "node-with-grok" in html
    assert "mesh_pair_token" in html or "demo-pair-token" in html
    assert "upload" in html
    assert "selected node" in html
    assert "8090/ui" in html
    assert "127.0.0.1" in html
    assert "policy" in html
    assert "duckdb" in html
    assert "polars" in html


def test_tooltip_hooks_are_accessible():
    html = UI_PATH.read_text(encoding="utf-8")
    for tip_id in TIP_IDS:
        assert f'id="{tip_id}"' in html
        assert f'aria-describedby="{tip_id}"' in html
        assert f'role="tooltip"' in html
    assert 'id="themeToggle"' in html
    assert 'id="principal"' in html
    assert 'id="node"' in html
    assert 'id="kind"' in html
    assert 'id="analytic"' in html
    assert 'id="sql"' in html
    assert 'id="proposeBtn"' in html
    assert 'id="confirmSqlBtn"' in html
    assert 'id="assistBtn"' in html
    assert 'id="runBtn"' in html
    assert 'id="refreshConnectors"' in html
    assert 'id="refreshJobs"' in html
    assert 'id="copyReceiptBtn"' in html
    assert 'id="verifyChainBtn"' in html
    assert 'id="downloadLink"' in html
    assert 'id="chartPreview"' in html
    assert 'id="uploadZone"' in html
    assert 'id="uploadBrowse"' in html
    assert 'id="uploadFile"' in html


def test_help_ui_is_served_on_node(tmp_path: Path, data_dir: Path):
    html = _node_client(tmp_path, data_dir).get("/ui").text
    assert 'id="helpBtn"' in html
    assert 'id="helpDrawer"' in html
    assert 'id="tip-run"' in html
    assert "Getting started" in html
    assert "react" not in html.lower()
    assert "vite" not in html.lower()


def test_help_ui_is_served_on_plane(tmp_path: Path):
    cfg = PlaneConfig(plane_id="test-plane", store_path=tmp_path / "plane.sqlite")
    html = TestClient(create_plane_app(cfg)).get("/ui").text
    assert 'id="helpBtn"' in html
    assert 'id="help-plane-vs-node"' in html
    assert 'id="tip-jobs"' in html
    assert "#job=" in html

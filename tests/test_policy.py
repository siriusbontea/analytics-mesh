from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from mesh_common.policy import (
    PolicyDenied,
    PolicyEngine,
    YamlPolicy,
    load_policy,
)
from mesh_node.app import create_app
from mesh_node.config import ArtifactStoreConfig, ConnectorConfig, LimitsConfig, NodeConfig

REPO = Path(__file__).resolve().parents[1]


RESTRICTIVE = """
default_principal: local
deny_unknown_principals: true
principals:
  analyst:
    allow_adhoc_sql: true
    allow_assist: true
    connectors: ["local_files"]
    analytics: ["top_products"]
    nodes: ["test-node"]
    max_row_limit: 50
    query_timeout_seconds: 10
    model_mode: local_only
  viewer:
    allow_adhoc_sql: false
    allow_assist: false
    connectors: ["local_files"]
    analytics: ["top_products"]
    nodes: ["test-node"]
    max_row_limit: 10
    query_timeout_seconds: 5
    model_mode: local_only
  frontier-user:
    allow_adhoc_sql: true
    allow_assist: true
    connectors: ["*"]
    analytics: ["*"]
    nodes: ["*"]
    max_row_limit: 1000
    query_timeout_seconds: 30
    model_mode: allow_frontier
"""


def test_example_policy_loads():
    policy = load_policy(REPO / "configs/examples/policy.yaml")
    assert isinstance(policy, YamlPolicy)
    decision = policy.authorize(
        principal="local",
        action="run_query",
        node_id="local-dev",
        connector_ids=["local_files"],
    )
    assert decision.allowed is True
    assert decision.model_mode == "local_only"


def test_unknown_principal_denied():
    policy = YamlPolicy.from_yaml(RESTRICTIVE)
    decision = policy.authorize(principal="stranger", action="run_query", node_id="test-node")
    assert decision.allowed is False
    assert "unknown principal" in (decision.reason or "").lower()


def test_default_principal_does_not_alias_unknown_names():
    policy = load_policy(REPO / "configs/examples/policy.yaml")
    denied = policy.authorize(principal="ghost", action="run_query", node_id="local-dev")
    assert denied.allowed is False
    allowed = policy.authorize(principal="", action="run_query", node_id="local-dev")
    assert allowed.allowed is True


def test_viewer_cannot_run_adhoc_sql():
    policy = YamlPolicy.from_yaml(RESTRICTIVE)
    decision = policy.authorize(
        principal="viewer",
        action="run_query",
        node_id="test-node",
        connector_ids=["local_files"],
    )
    assert decision.allowed is False
    assert "adhoc" in (decision.reason or "").lower() or "sql" in (decision.reason or "").lower()


def test_viewer_can_run_allowed_analytic():
    policy = YamlPolicy.from_yaml(RESTRICTIVE)
    decision = policy.authorize(
        principal="viewer",
        action="run_analytic",
        node_id="test-node",
        analytic_id="top_products",
        connector_ids=["local_files"],
    )
    assert decision.allowed is True
    assert decision.max_row_limit == 10


def test_analyst_cannot_run_unlisted_analytic():
    policy = YamlPolicy.from_yaml(RESTRICTIVE)
    decision = policy.authorize(
        principal="analyst",
        action="run_analytic",
        node_id="test-node",
        analytic_id="sales_by_region",
        connector_ids=["local_files"],
    )
    assert decision.allowed is False


def test_connector_and_node_allowlists():
    policy = YamlPolicy.from_yaml(RESTRICTIVE)
    denied_connector = policy.authorize(
        principal="analyst",
        action="run_query",
        node_id="test-node",
        connector_ids=["postgres"],
    )
    assert denied_connector.allowed is False
    denied_node = policy.authorize(
        principal="analyst",
        action="run_query",
        node_id="other-node",
        connector_ids=["local_files"],
    )
    assert denied_node.allowed is False


def test_local_only_blocks_frontier_assist():
    policy = YamlPolicy.from_yaml(RESTRICTIVE)
    decision = policy.authorize(
        principal="analyst",
        action="assist_nl2sql",
        node_id="test-node",
        model_provider="frontier",
    )
    assert decision.allowed is False
    allowed_local = policy.authorize(
        principal="analyst",
        action="assist_nl2sql",
        node_id="test-node",
        model_provider="local",
    )
    assert allowed_local.allowed is True
    frontier_ok = policy.authorize(
        principal="frontier-user",
        action="assist_nl2sql",
        node_id="anywhere",
        model_provider="frontier",
    )
    assert frontier_ok.allowed is True


def test_allow_all_policy_when_no_file():
    policy = load_policy(None)
    decision = policy.authorize(principal="anyone", action="run_query", node_id="n")
    assert decision.allowed is True
    assert isinstance(policy, PolicyEngine)


def test_node_enforces_policy_on_query_and_analytic(tmp_path: Path, data_dir: Path):
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(RESTRICTIVE)
    cfg = NodeConfig(
        node_id="test-node",
        artifact_dir=tmp_path / "artifacts",
        receipt_db=tmp_path / "receipts.sqlite",
        connectors=[ConnectorConfig(id="local_files", type="local_files", root=data_dir)],
        limits=LimitsConfig(default_row_limit=100, max_row_limit=1000, query_timeout_seconds=10),
        analytics_dir=REPO / "analytics",
        policy_path=policy_path,
        artifacts=ArtifactStoreConfig(max_files=50, retention_days=7),
    )
    client = TestClient(create_app(cfg))

    denied = client.post("/query", json={"sql": "SELECT * FROM sales", "principal": "viewer"})
    assert denied.status_code == 403
    assert denied.json()["detail"]["receipt"]["status"] == "failed"

    allowed = client.post("/analytics/run", json={"analytic_id": "top_products", "principal": "viewer"})
    assert allowed.status_code == 200
    assert allowed.json()["artifact"]["row_count"] <= 10

    unknown = client.post("/query", json={"sql": "SELECT * FROM sales", "principal": "ghost"})
    assert unknown.status_code == 403


def test_policy_denied_is_exception():
    err = PolicyDenied("nope")
    assert str(err) == "nope"

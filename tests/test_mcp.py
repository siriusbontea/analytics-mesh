from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mesh_mcp.api import MeshApi
from mesh_mcp.server import ALLOWED_TOOLS, MeshMcpError, build_server, call_tool
from mesh_node.app import create_app
from mesh_node.config import ConnectorConfig, LimitsConfig, NodeConfig

REPO = Path(__file__).resolve().parents[1]


def _cfg(tmp_path: Path, data_dir: Path, policy_path: Path | None = None) -> NodeConfig:
    return NodeConfig(
        node_id="mcp-node",
        artifact_dir=tmp_path / "artifacts",
        receipt_db=tmp_path / "receipts.sqlite",
        connectors=[ConnectorConfig(id="local_files", type="local_files", root=data_dir)],
        limits=LimitsConfig(default_row_limit=100, max_row_limit=1000, query_timeout_seconds=10),
        analytics_dir=REPO / "analytics",
        policy_path=policy_path,
    )


def _api(app, principal: str = "local") -> MeshApi:
    return MeshApi(base_url="http://mesh-node", principal=principal, client=TestClient(app))


def test_mcp_toolset_is_analytics_only():
    assert ALLOWED_TOOLS == (
        "list_analytics",
        "run_analytic",
        "get_receipt",
        "list_connectors",
        "list_nodes",
    )
    server = build_server(_api(create_app(NodeConfig(node_id="x"))))
    names = set(server.tool_names())
    assert {"list_analytics", "run_analytic", "get_receipt"} <= names
    assert names <= set(ALLOWED_TOOLS)
    assert "run_query" not in names
    assert "query" not in names
    assert "shell" not in names


def test_mcp_tools_use_policy_gated_node_api(tmp_path: Path, data_dir: Path):
    app = create_app(_cfg(tmp_path, data_dir))
    api = _api(app)
    listed = call_tool(api, "list_analytics", {})
    ids = {item["analytic_id"] for item in listed["analytics"]}
    assert "top_products" in ids
    connectors = call_tool(api, "list_connectors", {})
    assert connectors["connectors"][0]["id"] == "local_files"
    ran = call_tool(api, "run_analytic", {"analytic_id": "top_products"})
    assert ran["receipt"]["action"] == "run_analytic"
    assert ran["receipt"]["status"] == "succeeded"
    assert ran["artifact"]["row_count"] == 3
    receipt = call_tool(api, "get_receipt", {"receipt_id": ran["receipt"]["receipt_id"]})
    assert receipt["receipt_id"] == ran["receipt"]["receipt_id"]
    assert receipt["receipt_hash"] == ran["receipt"]["receipt_hash"]


def test_mcp_run_analytic_is_denied_by_policy(tmp_path: Path, data_dir: Path):
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        """
deny_unknown_principals: true
principals:
  viewer:
    allow_adhoc_sql: false
    allow_assist: false
    connectors: ["*"]
    analytics: []
    nodes: ["*"]
"""
    )
    app = create_app(_cfg(tmp_path, data_dir, policy_path))
    api = _api(app, principal="viewer")
    with pytest.raises(MeshMcpError) as exc:
        call_tool(api, "run_analytic", {"analytic_id": "top_products", "principal": "viewer"})
    assert exc.value.status_code == 403


def test_mcp_rejects_unknown_and_query_tools(tmp_path: Path, data_dir: Path):
    api = _api(create_app(_cfg(tmp_path, data_dir)))
    with pytest.raises(MeshMcpError, match="not an allowed"):
        call_tool(api, "run_query", {"sql": "SELECT * FROM sales"})
    with pytest.raises(MeshMcpError, match="not an allowed"):
        call_tool(api, "shell", {"cmd": "cat /etc/passwd"})


def test_mcp_list_nodes_on_direct_node_is_clear(tmp_path: Path, data_dir: Path):
    api = _api(create_app(_cfg(tmp_path, data_dir)))
    with pytest.raises(MeshMcpError):
        call_tool(api, "list_nodes", {})


@pytest.mark.asyncio
async def test_mcp_protocol_server_registers_only_analytics_tools():
    from mesh_mcp.server import build_mcp_protocol_server

    server = build_mcp_protocol_server(_api(create_app(NodeConfig(node_id="proto"))))
    tools = await server.list_tools()
    names = {item.name for item in tools}
    assert {"list_analytics", "run_analytic", "get_receipt"} <= names
    assert names <= set(ALLOWED_TOOLS)
    assert "run_query" not in names

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from mesh_mcp.api import MeshApi, MeshMcpError

ALLOWED_TOOLS = (
    "list_analytics",
    "run_analytic",
    "get_receipt",
    "list_connectors",
    "list_nodes",
)

_TOOL_DESCRIPTIONS = {
    "list_analytics": "List registered analytics on the target node. Same policy-gated GET /analytics as the CLI.",
    "run_analytic": "Run a registered analytic by id (optional version). Same POST /analytics/run as CLI/web. No ad-hoc SQL.",
    "get_receipt": "Fetch a hash-chained receipt by id from the owning node.",
    "list_connectors": "List connectors and discovered tables on the target node.",
    "list_nodes": "List nodes registered with the control plane (plane URL only).",
}


class MeshMcpServer:
    def __init__(self, api: MeshApi) -> None:
        self.api = api

    def tool_names(self) -> list[str]:
        return list(ALLOWED_TOOLS)


def build_server(api: MeshApi) -> MeshMcpServer:
    return MeshMcpServer(api)


def call_tool(api: MeshApi, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    if name not in ALLOWED_TOOLS:
        raise MeshMcpError(f"{name} is not an allowed analytics-mesh MCP tool", status_code=400)
    args = dict(arguments or {})
    if name == "list_analytics":
        return api.list_analytics()
    if name == "list_connectors":
        return api.list_connectors()
    if name == "list_nodes":
        return api.list_nodes()
    if name == "run_analytic":
        analytic_id = args.get("analytic_id")
        if not analytic_id:
            raise MeshMcpError("analytic_id is required", status_code=400)
        return api.run_analytic(
            analytic_id=str(analytic_id),
            version=args.get("version"),
            params=args.get("params"),
            row_limit=args.get("row_limit"),
            principal=args.get("principal"),
        )
    receipt_id = args.get("receipt_id")
    if not receipt_id:
        raise MeshMcpError("receipt_id is required", status_code=400)
    return api.get_receipt(str(receipt_id))


class ToolCallBody(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


def create_http_app(api: MeshApi) -> FastAPI:
    app = FastAPI(
        title="Analytics Mesh MCP",
        description="Analytics toolset only. Calls the same policy-gated node/plane APIs as the CLI.",
        version="0.1.0",
    )
    app.state.api = api

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "tools": list(ALLOWED_TOOLS)}

    @app.get("/tools")
    def tools() -> dict[str, object]:
        return {
            "tools": [
                {"name": name, "description": _TOOL_DESCRIPTIONS[name]} for name in ALLOWED_TOOLS
            ]
        }

    @app.post("/tools/{name}")
    def invoke(name: str, body: ToolCallBody | None = None) -> dict[str, Any]:
        try:
            return call_tool(api, name, (body.arguments if body else {}))
        except MeshMcpError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"message": exc.message, "body": exc.body}) from exc

    return app


def run_http(api: MeshApi, host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_http_app(api), host=host, port=port, log_level="info")


def build_mcp_protocol_server(api: MeshApi):
    """Official MCP 2.x server (stdio / streamable-http). Same toolset as call_tool()."""
    from mcp.server import MCPServer

    server = MCPServer("analytics-mesh")

    def _invoke(name: str, arguments: dict[str, Any] | None = None) -> str:
        try:
            return json.dumps(call_tool(api, name, arguments or {}), default=str)
        except MeshMcpError as exc:
            return json.dumps({"error": exc.message, "status_code": exc.status_code, "body": exc.body}, default=str)

    @server.tool(description=_TOOL_DESCRIPTIONS["list_analytics"])
    def list_analytics() -> str:
        return _invoke("list_analytics")

    @server.tool(description=_TOOL_DESCRIPTIONS["run_analytic"])
    def run_analytic(
        analytic_id: str,
        version: str | None = None,
        row_limit: int | None = None,
        principal: str | None = None,
    ) -> str:
        args: dict[str, Any] = {"analytic_id": analytic_id}
        if version is not None:
            args["version"] = version
        if row_limit is not None:
            args["row_limit"] = row_limit
        if principal is not None:
            args["principal"] = principal
        return _invoke("run_analytic", args)

    @server.tool(description=_TOOL_DESCRIPTIONS["get_receipt"])
    def get_receipt(receipt_id: str) -> str:
        return _invoke("get_receipt", {"receipt_id": receipt_id})

    @server.tool(description=_TOOL_DESCRIPTIONS["list_connectors"])
    def list_connectors() -> str:
        return _invoke("list_connectors")

    @server.tool(description=_TOOL_DESCRIPTIONS["list_nodes"])
    def list_nodes() -> str:
        return _invoke("list_nodes")

    return server


def run_stdio(api: MeshApi) -> None:
    build_mcp_protocol_server(api).run(transport="stdio")


def run_server(
    *,
    url: str,
    principal: str = "local",
    node_id: str | None = None,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    api = MeshApi.from_env(url=url, principal=principal, node_id=node_id)
    if transport == "http":
        run_http(api, host=host, port=port)
        return
    if transport == "streamable-http":
        build_mcp_protocol_server(api).run(transport="streamable-http", host=host, port=port)
        return
    if transport != "stdio":
        raise ValueError(f"unsupported MCP transport: {transport}")
    run_stdio(api)

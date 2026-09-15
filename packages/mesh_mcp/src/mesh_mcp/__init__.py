"""Analytics-only MCP adapter. Tools call the same policy-gated HTTP APIs as CLI/web."""

from mesh_mcp.api import MeshApi
from mesh_mcp.server import ALLOWED_TOOLS, MeshMcpError, MeshMcpServer, build_server, call_tool

__version__ = "0.1.0"

__all__ = [
    "ALLOWED_TOOLS",
    "MeshApi",
    "MeshMcpError",
    "MeshMcpServer",
    "build_server",
    "call_tool",
]

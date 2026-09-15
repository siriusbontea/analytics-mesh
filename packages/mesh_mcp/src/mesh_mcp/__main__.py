from __future__ import annotations

import os

from mesh_mcp.server import run_server


def main() -> None:
    run_server(
        url=os.environ.get("MESH_URL", "http://127.0.0.1:8080"),
        principal=os.environ.get("MESH_PRINCIPAL", "local"),
        node_id=os.environ.get("MESH_NODE") or None,
        transport=os.environ.get("MESH_MCP_TRANSPORT", "stdio"),
        host=os.environ.get("MESH_MCP_HOST", "127.0.0.1"),
        port=int(os.environ.get("MESH_MCP_PORT", "8765")),
    )


if __name__ == "__main__":
    main()

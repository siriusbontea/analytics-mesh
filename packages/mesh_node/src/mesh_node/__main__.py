from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from mesh_node.app import create_app
from mesh_node.config import load_config


def main() -> None:
    config = Path(os.environ.get("MESH_NODE_CONFIG", "configs/examples/node.yaml"))
    cfg = load_config(config)
    host = cfg.resolved_listen_host()
    port = cfg.resolved_listen_port()
    uvicorn.run(create_app(cfg), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from mesh_plane.app import create_app
from mesh_plane.config import load_config


def main() -> None:
    config = Path(os.environ.get("MESH_PLANE_CONFIG", "configs/examples/plane.yaml"))
    cfg = load_config(config)
    host = os.environ.get("MESH_LISTEN_HOST", cfg.listen_host)
    port = int(os.environ.get("MESH_LISTEN_PORT", str(cfg.listen_port)))
    uvicorn.run(create_app(cfg), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

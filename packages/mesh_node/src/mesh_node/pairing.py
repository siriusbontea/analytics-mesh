from __future__ import annotations

import httpx

from mesh_common.identity import build_registration
from mesh_node.config import NodeConfig
from mesh_node.runtime import NodeRuntime


def node_public_endpoint(config: NodeConfig) -> str:
    if config.plane and config.plane.public_endpoint:
        return config.plane.public_endpoint.rstrip("/")
    return f"http://{config.listen_host}:{config.listen_port}"


def register_with_plane(
    runtime: NodeRuntime,
    config: NodeConfig,
    plane_url: str | None = None,
    token: str | None = None,
    endpoint: str | None = None,
    timeout: float = 10.0,
) -> dict[str, object]:
    if plane_url is None:
        if config.plane is None:
            raise ValueError("plane URL is required to register")
        plane_url = config.plane.url
    if token is None:
        if config.plane is None:
            raise ValueError("registration token is required to register")
        token = config.plane.token
    body = build_registration(
        keys=runtime.identity,
        endpoint=endpoint or node_public_endpoint(config),
        token=token,
        labels=config.labels,
    )
    response = httpx.post(f"{plane_url.rstrip('/')}/nodes/register", json=body, timeout=timeout)
    response.raise_for_status()
    return response.json()

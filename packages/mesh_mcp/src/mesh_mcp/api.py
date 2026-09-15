from __future__ import annotations

import os
from typing import Any

import httpx


class MeshMcpError(Exception):
    """HTTP or tool-dispatch failure surfaced to an MCP client."""

    def __init__(self, message: str, status_code: int = 400, body: object | None = None) -> None:
        self.message = message
        self.status_code = status_code
        self.body = body
        super().__init__(message)


class MeshApi:
    """HTTP client for the same policy-gated node/plane APIs the CLI uses."""

    def __init__(
        self,
        base_url: str,
        principal: str = "local",
        node_id: str | None = None,
        client: httpx.Client | Any = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.principal = principal
        self.node_id = node_id
        self.client = client or httpx.Client(base_url=self.base_url, timeout=timeout)

    @classmethod
    def from_env(
        cls,
        url: str | None = None,
        principal: str | None = None,
        node_id: str | None = None,
    ) -> MeshApi:
        return cls(
            base_url=url or os.environ.get("MESH_URL", "http://127.0.0.1:8080"),
            principal=principal or os.environ.get("MESH_PRINCIPAL", "local"),
            node_id=node_id or os.environ.get("MESH_NODE") or None,
        )

    def list_analytics(self) -> dict[str, Any]:
        path = f"/nodes/{self.node_id}/analytics" if self.node_id else "/analytics"
        return self._request("GET", path)

    def list_connectors(self) -> dict[str, Any]:
        path = f"/nodes/{self.node_id}/connectors" if self.node_id else "/connectors"
        return self._request("GET", path)

    def list_nodes(self) -> dict[str, Any]:
        return self._request("GET", "/nodes")

    def run_analytic(
        self,
        analytic_id: str,
        version: str | None = None,
        params: dict[str, Any] | None = None,
        row_limit: int | None = None,
        principal: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "analytic_id": analytic_id,
            "principal": principal or self.principal,
        }
        if version is not None:
            payload["version"] = version
        if params:
            payload["params"] = params
        if row_limit is not None:
            payload["row_limit"] = row_limit
        if self.node_id is not None:
            payload["node_id"] = self.node_id
        return self._request("POST", "/analytics/run", json=payload)

    def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        if self.node_id:
            path = f"/nodes/{self.node_id}/receipts/{receipt_id}"
        else:
            path = f"/receipts/{receipt_id}"
        return self._request("GET", path)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise MeshMcpError(_error_message(response), status_code=response.status_code, body=_json_or_text(response))
        payload = response.json()
        if not isinstance(payload, dict):
            raise MeshMcpError("unexpected response from mesh API", status_code=502)
        return payload


def _json_or_text(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return response.text


def _error_message(response: httpx.Response) -> str:
    body = _json_or_text(response)
    if isinstance(body, dict):
        detail = body.get("detail", body)
        if isinstance(detail, dict) and detail.get("message"):
            return str(detail["message"])
        if isinstance(detail, str):
            return detail
    return f"mesh API returned HTTP {response.status_code}"

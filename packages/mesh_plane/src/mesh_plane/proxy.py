from __future__ import annotations

import httpx
from fastapi import HTTPException

from mesh_common.schemas import AnalyticRunRequest, QueryRequest, QueryResponse, Receipt


class NodeProxy:
    """HTTP client from plane to a node. Does not persist source data or artifacts."""

    def __init__(self, timeout: float = 60.0) -> None:
        self.timeout = timeout

    def run_query(self, endpoint: str, request: QueryRequest) -> QueryResponse:
        url = f"{endpoint.rstrip('/')}/query"
        response = httpx.post(url, json=request.model_dump(mode="json"), timeout=self.timeout)
        if response.status_code >= 400:
            detail = _json_or_text(response)
            receipt = _receipt_from_error(detail)
            if receipt is not None:
                return QueryResponse(artifact=None, receipt=receipt)
            raise HTTPException(status_code=response.status_code, detail=detail)
        return QueryResponse.model_validate(response.json())

    def run_analytic(self, endpoint: str, request: AnalyticRunRequest) -> QueryResponse:
        url = f"{endpoint.rstrip('/')}/analytics/run"
        response = httpx.post(url, json=request.model_dump(mode="json"), timeout=self.timeout)
        if response.status_code >= 400:
            detail = _json_or_text(response)
            receipt = _receipt_from_error(detail)
            if receipt is not None:
                return QueryResponse(artifact=None, receipt=receipt)
            raise HTTPException(status_code=response.status_code, detail=detail)
        return QueryResponse.model_validate(response.json())

    def list_analytics(self, endpoint: str) -> dict[str, object]:
        return self._get_json(endpoint, "/analytics")

    def list_connectors(self, endpoint: str) -> dict[str, object]:
        return self._get_json(endpoint, "/connectors")

    def upload(
        self,
        endpoint: str,
        *,
        filename: str,
        content: bytes,
        principal: str,
        content_type: str | None = None,
        connector_id: str | None = None,
    ) -> dict[str, object]:
        data: dict[str, str] = {"principal": principal}
        if connector_id:
            data["connector_id"] = connector_id
        files = {"file": (filename, content, content_type or "application/octet-stream")}
        response = httpx.post(
            f"{endpoint.rstrip('/')}/upload",
            data=data,
            files=files,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=_unwrap_detail(response))
        return response.json()

    def models_status(self, endpoint: str, probe: bool = False) -> dict[str, object]:
        suffix = "/models?probe=true" if probe else "/models"
        return self._get_json(endpoint, suffix)

    def assist_nl2sql(self, endpoint: str, payload: dict[str, object]) -> dict[str, object]:
        response = httpx.post(f"{endpoint.rstrip('/')}/assist/nl2sql", json=payload, timeout=self.timeout)
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=_json_or_text(response))
        return response.json()

    def assist_explain(self, endpoint: str, payload: dict[str, object]) -> dict[str, object]:
        response = httpx.post(f"{endpoint.rstrip('/')}/assist/explain", json=payload, timeout=self.timeout)
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=_json_or_text(response))
        return response.json()

    def preview(self, endpoint: str, artifact_id: str) -> dict[str, object]:
        return self._get_json(endpoint, f"/results/{artifact_id}/preview")

    def get_receipt(self, endpoint: str, receipt_id: str) -> dict[str, object]:
        response = httpx.get(f"{endpoint.rstrip('/')}/receipts/{receipt_id}", timeout=self.timeout)
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="receipt not found")
        response.raise_for_status()
        return response.json()

    def verify_chain(self, endpoint: str) -> dict[str, object]:
        response = httpx.get(f"{endpoint.rstrip('/')}/receipts/chain", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _get_json(self, endpoint: str, path: str) -> dict[str, object]:
        response = httpx.get(f"{endpoint.rstrip('/')}{path}", timeout=self.timeout)
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail=_json_or_text(response))
        response.raise_for_status()
        return response.json()

    def get_result(self, endpoint: str, artifact_id: str) -> httpx.Response:
        response = httpx.get(f"{endpoint.rstrip('/')}/results/{artifact_id}", timeout=self.timeout)
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="artifact not found")
        response.raise_for_status()
        return response


def _unwrap_detail(response: httpx.Response) -> object:
    detail = _json_or_text(response)
    if isinstance(detail, dict) and "detail" in detail:
        return detail["detail"]
    return detail


def _json_or_text(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return response.text


def _receipt_from_error(detail: object) -> Receipt | None:
    if not isinstance(detail, dict):
        return None
    payload = detail.get("detail", detail)
    if isinstance(payload, dict) and isinstance(payload.get("receipt"), dict):
        return Receipt.model_validate(payload["receipt"])
    return None

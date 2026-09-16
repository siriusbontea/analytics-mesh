from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from mesh_common.llm import llm_health_fields
from mesh_common.policy import PolicyDenied
from mesh_common.schemas import (
    AnalyticRunRequest,
    AssistExplainRequest,
    AssistNl2SqlRequest,
    QueryRequest,
    QueryResponse,
    UploadResponse,
)
from mesh_common.uploads import UploadRejected, read_upload_bytes
from mesh_common.web import mount_ui
from mesh_node.config import NodeConfig
from mesh_node.pairing import register_with_plane
from mesh_node.runtime import NodeRuntime

__version__ = "0.1.0"
logger = logging.getLogger("mesh_node")


def create_app(config: NodeConfig | None = None) -> FastAPI:
    cfg = config or NodeConfig()
    runtime = NodeRuntime(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if cfg.plane and cfg.plane.register_on_start:
            try:
                register_with_plane(runtime, cfg)
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("plane registration failed; pair later with `mesh pair`: %s", exc)
        yield

    app = FastAPI(title="Analytics Mesh Node", version=__version__, lifespan=lifespan)
    app.state.runtime = runtime
    app.state.config = cfg
    mount_ui(app)

    @app.get("/health")
    def health() -> dict[str, object]:
        body = {
            "status": "ok",
            "node_id": cfg.node_id,
            "version": __version__,
            "public_key": runtime.identity.public_key_hex,
            "engines": sorted(runtime.engines),
        }
        body.update(llm_health_fields(cfg.models))
        return body

    @app.get("/connectors")
    def list_connectors() -> dict[str, object]:
        return {"connectors": [item.model_dump(mode="json") for item in runtime.list_connectors()]}

    @app.post("/upload")
    async def upload_file(
        file: UploadFile = File(...),
        principal: str = Form("web"),
        connector_id: str | None = Form(None),
    ) -> UploadResponse:
        try:
            content = await read_upload_bytes(file, runtime.config.uploads.max_bytes)
            return runtime.upload_file(
                filename=file.filename,
                content=content,
                principal=principal,
                connector_id=connector_id,
            )
        except PolicyDenied as exc:
            raise HTTPException(status_code=403, detail=_policy_detail(exc)) from exc
        except UploadRejected as exc:
            detail: dict[str, object] = {"message": str(exc)}
            if exc.receipt is not None:
                receipt = exc.receipt
                detail["receipt"] = receipt.model_dump(mode="json") if hasattr(receipt, "model_dump") else receipt
            raise HTTPException(status_code=400, detail=detail) from exc
        finally:
            await file.close()

    @app.get("/analytics")
    def list_analytics() -> dict[str, object]:
        return {"analytics": [item.model_dump(mode="json") for item in runtime.list_analytics()]}

    @app.post("/query")
    def run_query(request: QueryRequest) -> QueryResponse:
        try:
            result = runtime.run_query(
                request.sql,
                request.principal,
                request.row_limit,
                assist_model_provider=request.assist_model_provider,
                assist_model_id=request.assist_model_id,
            )
        except PolicyDenied as exc:
            raise HTTPException(status_code=403, detail=_policy_detail(exc)) from exc
        if result.receipt.status == "failed":
            raise HTTPException(
                status_code=400,
                detail={"message": result.receipt.error or "query failed", "receipt": result.receipt.model_dump(mode="json")},
            )
        return result

    @app.post("/analytics/run")
    def run_analytic(request: AnalyticRunRequest) -> QueryResponse:
        try:
            result = runtime.run_analytic(
                request.analytic_id,
                request.principal,
                request.row_limit,
                version=request.version,
                params=request.params,
            )
        except PolicyDenied as exc:
            raise HTTPException(status_code=403, detail=_policy_detail(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown analytic: {exc.args[0]}") from exc
        if result.receipt.status == "failed":
            raise HTTPException(
                status_code=400,
                detail={"message": result.receipt.error or "analytic failed", "receipt": result.receipt.model_dump(mode="json")},
            )
        return result

    @app.get("/results/{artifact_id}/preview")
    def get_result_preview(artifact_id: str) -> dict[str, object]:
        preview = runtime.preview_artifact(artifact_id)
        if preview is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        return preview.model_dump(mode="json")

    @app.get("/results/{artifact_id}")
    def get_result(artifact_id: str) -> FileResponse:
        artifact = runtime.get_artifact(artifact_id)
        if artifact is None or not Path(artifact.path).is_file():
            raise HTTPException(status_code=404, detail="artifact not found")
        return FileResponse(
            artifact.path,
            media_type="application/vnd.apache.parquet",
            filename=f"{artifact_id}.parquet",
        )

    @app.get("/models")
    def models(probe: bool = False) -> dict[str, object]:
        return runtime.models_status(probe=probe)

    @app.post("/assist/nl2sql")
    def assist_nl2sql(request: AssistNl2SqlRequest) -> dict[str, object]:
        try:
            return runtime.propose_sql(request.question, request.principal)
        except PolicyDenied as exc:
            raise HTTPException(status_code=403, detail=_policy_detail(exc)) from exc

    @app.post("/assist/explain")
    def assist_explain(request: AssistExplainRequest) -> dict[str, object]:
        try:
            return runtime.explain_result(request.artifact_id, request.principal)
        except PolicyDenied as exc:
            raise HTTPException(status_code=403, detail=_policy_detail(exc)) from exc

    @app.get("/receipts/chain")
    def receipt_chain() -> dict[str, object]:
        return runtime.receipts.verify_chain().model_dump(mode="json")

    @app.get("/receipts/{receipt_id}")
    def get_receipt(receipt_id: str) -> dict[str, object]:
        receipt = runtime.receipts.get(receipt_id)
        if receipt is None:
            raise HTTPException(status_code=404, detail="receipt not found")
        return receipt.model_dump(mode="json")

    return app


def _policy_detail(exc: PolicyDenied) -> dict[str, object]:
    detail: dict[str, object] = {"message": exc.reason}
    if exc.receipt is not None:
        detail["receipt"] = exc.receipt.model_dump(mode="json")
    return detail

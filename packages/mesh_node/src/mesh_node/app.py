from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from mesh_common.schemas import QueryRequest, QueryResponse
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

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "node_id": cfg.node_id,
            "version": __version__,
            "public_key": runtime.identity.public_key_hex,
            "llm_configured": cfg.models.is_configured(),
        }

    @app.get("/connectors")
    def list_connectors() -> dict[str, object]:
        return {"connectors": [item.model_dump(mode="json") for item in runtime.list_connectors()]}

    @app.post("/query")
    def run_query(request: QueryRequest) -> QueryResponse:
        result = runtime.run_query(request.sql, request.principal, request.row_limit)
        if result.receipt.status == "failed":
            raise HTTPException(
                status_code=400,
                detail={"message": result.receipt.error or "query failed", "receipt": result.receipt.model_dump(mode="json")},
            )
        return result

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

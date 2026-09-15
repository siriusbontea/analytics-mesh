from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from mesh_common.hashing import sha256_text
from mesh_common.identity import NodeKeyPair, canonical_registration_payload
from mesh_common.schemas import (
    AnalyticRunRequest,
    JobRecord,
    NodeRecord,
    NodeRegistrationRequest,
    PlaneAnalyticRunRequest,
    PlaneQueryRequest,
    PlaneQueryResponse,
    QueryRequest,
    QueryResponse,
)
from mesh_common.web import mount_ui
from mesh_plane.config import PlaneConfig
from mesh_plane.proxy import NodeProxy
from mesh_plane.store import PlaneStore

__version__ = "0.1.0"


def create_app(config: PlaneConfig | None = None, proxy: NodeProxy | None = None) -> FastAPI:
    cfg = config or PlaneConfig()
    store = PlaneStore(cfg.store_path)
    node_proxy = proxy or NodeProxy()
    app = FastAPI(title="Analytics Mesh Plane", version=__version__)
    app.state.config = cfg
    app.state.store = store
    app.state.proxy = node_proxy
    mount_ui(app)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "plane_id": cfg.plane_id,
            "version": __version__,
            "node_count": len(store.list_nodes()),
        }

    @app.post("/nodes/register")
    def register_node(request: NodeRegistrationRequest) -> dict[str, object]:
        if request.token != cfg.registration_token:
            raise HTTPException(status_code=403, detail="invalid registration token")
        payload = canonical_registration_payload(
            node_id=request.node_id,
            endpoint=request.endpoint,
            public_key=request.public_key,
            signed_at=request.signed_at,
        )
        verifier = NodeKeyPair.from_public_hex(request.public_key, node_id=request.node_id)
        if not verifier.verify(payload, request.signature):
            raise HTTPException(status_code=403, detail="invalid registration signature")
        now = datetime.now(timezone.utc)
        record = store.upsert_node(
            NodeRecord(
                node_id=request.node_id,
                endpoint=request.endpoint.rstrip("/"),
                public_key=request.public_key,
                labels=request.labels,
                registered_at=now,
                last_seen=now,
            )
        )
        return {"node": record.model_dump(mode="json")}

    @app.get("/nodes")
    def list_nodes() -> dict[str, object]:
        return {"nodes": [item.model_dump(mode="json") for item in store.list_nodes()]}

    @app.get("/nodes/{node_id}")
    def get_node(node_id: str) -> dict[str, object]:
        node = store.get_node(node_id)
        if node is None:
            raise HTTPException(status_code=404, detail="unknown node")
        return node.model_dump(mode="json")

    @app.post("/query")
    def run_query(request: PlaneQueryRequest) -> PlaneQueryResponse:
        return _run_on_node(
            store,
            node_proxy,
            node_id=request.node_id,
            action="run_query",
            principal=request.principal,
            sql_hash=sha256_text(request.sql.strip()),
            invoke=lambda endpoint: node_proxy.run_query(
                endpoint,
                QueryRequest(
                    sql=request.sql,
                    row_limit=request.row_limit,
                    principal=request.principal,
                    assist_model_provider=request.assist_model_provider,
                    assist_model_id=request.assist_model_id,
                ),
            ),
        )

    @app.post("/analytics/run")
    def run_analytic(request: PlaneAnalyticRunRequest) -> PlaneQueryResponse:
        return _run_on_node(
            store,
            node_proxy,
            node_id=request.node_id,
            action="run_analytic",
            principal=request.principal,
            sql_hash=sha256_text(f"{request.analytic_id}@{request.version or 'latest'}"),
            invoke=lambda endpoint: node_proxy.run_analytic(
                endpoint,
                AnalyticRunRequest(
                    analytic_id=request.analytic_id,
                    version=request.version,
                    params=request.params,
                    row_limit=request.row_limit,
                    principal=request.principal,
                ),
            ),
        )

    @app.get("/nodes/{node_id}/analytics")
    def node_analytics(node_id: str) -> dict[str, object]:
        node = _require_node(store, node_id)
        return node_proxy.list_analytics(node.endpoint)

    @app.get("/nodes/{node_id}/connectors")
    def node_connectors(node_id: str) -> dict[str, object]:
        node = _require_node(store, node_id)
        return node_proxy.list_connectors(node.endpoint)

    @app.get("/nodes/{node_id}/models")
    def node_models(node_id: str, probe: bool = False) -> dict[str, object]:
        node = _require_node(store, node_id)
        return node_proxy.models_status(node.endpoint, probe=probe)

    @app.post("/nodes/{node_id}/assist/nl2sql")
    def node_nl2sql(node_id: str, payload: dict[str, object]) -> dict[str, object]:
        node = _require_node(store, node_id)
        return node_proxy.assist_nl2sql(node.endpoint, payload)

    @app.post("/nodes/{node_id}/assist/explain")
    def node_assist(node_id: str, payload: dict[str, object]) -> dict[str, object]:
        node = _require_node(store, node_id)
        return node_proxy.assist_explain(node.endpoint, payload)

    @app.get("/jobs/{job_id}/preview")
    def get_job_preview(job_id: str) -> dict[str, object]:
        job = _require_job(store, job_id)
        node = _require_node(store, job.node_id)
        if not job.artifact_id:
            raise HTTPException(status_code=404, detail="job has no artifact")
        return node_proxy.preview(node.endpoint, job.artifact_id)

    @app.get("/jobs")
    def list_jobs() -> dict[str, object]:
        return {"jobs": [item.model_dump(mode="json") for item in store.list_jobs()]}

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, object]:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job.model_dump(mode="json")

    @app.get("/jobs/{job_id}/result")
    def get_job_result(job_id: str) -> Response:
        job = _require_job(store, job_id)
        node = _require_node(store, job.node_id)
        if not job.artifact_id:
            raise HTTPException(status_code=404, detail="job has no artifact")
        upstream = node_proxy.get_result(node.endpoint, job.artifact_id)
        return Response(
            content=upstream.content,
            media_type=upstream.headers.get("content-type", "application/vnd.apache.parquet"),
            headers={"content-disposition": f'attachment; filename="{job.artifact_id}.parquet"'},
        )

    @app.get("/receipts/{receipt_id}")
    def get_receipt(receipt_id: str) -> dict[str, object]:
        job = store.get_job_by_receipt(receipt_id)
        if job is None:
            raise HTTPException(status_code=404, detail="receipt not found")
        node = _require_node(store, job.node_id)
        return node_proxy.get_receipt(node.endpoint, receipt_id)

    @app.get("/nodes/{node_id}/receipts/chain")
    def node_receipt_chain(node_id: str) -> dict[str, object]:
        node = _require_node(store, node_id)
        return node_proxy.verify_chain(node.endpoint)

    @app.get("/nodes/{node_id}/receipts/{receipt_id}")
    def node_receipt(node_id: str, receipt_id: str) -> dict[str, object]:
        node = _require_node(store, node_id)
        return node_proxy.get_receipt(node.endpoint, receipt_id)

    return app


def _run_on_node(
    store: PlaneStore,
    node_proxy: NodeProxy,
    node_id: str,
    action: str,
    principal: str,
    sql_hash: str,
    invoke,
) -> PlaneQueryResponse:
    job = store.create_job(node_id=node_id, action=action, principal=principal, sql_hash=sql_hash)
    node = store.get_node(node_id)
    if node is None:
        job = store.update_job(job.job_id, status="failed", error="unknown node")
        raise HTTPException(
            status_code=404,
            detail={"message": "unknown node", "job": job.model_dump(mode="json")},
        )
    job = store.update_job(job.job_id, status="running")
    store.touch_node(node.node_id)
    try:
        result: QueryResponse = invoke(node.endpoint)
    except HTTPException as exc:
        store.update_job(job.job_id, status="failed", error=str(exc.detail))
        raise
    except Exception as exc:  # noqa: BLE001 — surface transport failures as job failures
        job = store.update_job(job.job_id, status="failed", error=str(exc))
        raise HTTPException(status_code=502, detail={"message": str(exc), "job": job.model_dump(mode="json")}) from exc

    pointers = _pointers(node.endpoint, result.artifact.artifact_id if result.artifact else None, result.receipt.receipt_id)
    status = "succeeded" if result.receipt.status == "succeeded" else "failed"
    job = store.update_job(
        job.job_id,
        status=status,
        artifact_id=result.artifact.artifact_id if result.artifact else None,
        receipt_id=result.receipt.receipt_id,
        error=result.receipt.error,
        **pointers,
    )
    if status == "failed":
        raise HTTPException(
            status_code=400,
            detail={
                "message": result.receipt.error or f"{action} failed",
                "job": job.model_dump(mode="json"),
                "receipt": result.receipt.model_dump(mode="json"),
            },
        )
    return PlaneQueryResponse(job=job, artifact=result.artifact, receipt=result.receipt, preview=result.preview)


def _pointers(endpoint: str, artifact_id: str | None, receipt_id: str) -> dict[str, str | None]:
    base = endpoint.rstrip("/")
    return {
        "artifact_pointer": f"{base}/results/{artifact_id}" if artifact_id else None,
        "receipt_pointer": f"{base}/receipts/{receipt_id}",
    }


def _require_job(store: PlaneStore, job_id: str) -> JobRecord:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


def _require_node(store: PlaneStore, node_id: str):
    node = store.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="unknown node")
    return node

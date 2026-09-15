from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb

from mesh_common.hashing import sha256_text
from mesh_common.identity import generate_keypair, load_or_create_keypair
from mesh_common.llm import LlmClient, assist_attribution
from mesh_common.preview import preview_parquet
from mesh_common.receipts import ReceiptStore
from mesh_common.registry import AnalyticRegistry
from mesh_common.schemas import (
    AnalyticSpec,
    ArtifactRef,
    ConnectorInfo,
    QueryPlan,
    QueryResponse,
    Receipt,
    ResultPreview,
)
from mesh_connector_local_files import LocalFilesConnector
from mesh_engine_duckdb import DuckDBEngine, SqlGuardError
from mesh_node.config import NodeConfig


class NodeRuntime:
    def __init__(self, config: NodeConfig) -> None:
        self.config = config
        self.engine = DuckDBEngine()
        self.identity = (
            load_or_create_keypair(config.identity_key_path, config.node_id)
            if config.identity_key_path is not None
            else generate_keypair(config.node_id)
        )
        self.receipts = ReceiptStore(config.receipt_db)
        self.llm = LlmClient(config.models)
        self.registry = (
            AnalyticRegistry.load(config.analytics_dir) if config.analytics_dir is not None else AnalyticRegistry.empty()
        )
        self.connectors: dict[str, LocalFilesConnector] = {}
        for item in config.connectors:
            if item.type != "local_files":
                raise ValueError(f"unsupported connector type for M1: {item.type}")
            self.connectors[item.id] = LocalFilesConnector(
                root=item.root,
                connector_id=item.id,
                labels=item.labels,
            )
        self._artifacts: dict[str, ArtifactRef] = {}

    def list_connectors(self) -> list[ConnectorInfo]:
        infos: list[ConnectorInfo] = []
        for connector in self.connectors.values():
            infos.append(
                ConnectorInfo(
                    id=connector.id,
                    version=connector.version,
                    sensitivity_labels=connector.sensitivity_labels,
                    tables=connector.discover_schema(),
                )
            )
        return infos

    def list_analytics(self) -> list[AnalyticSpec]:
        return self.registry.list()

    def get_artifact(self, artifact_id: str) -> ArtifactRef | None:
        cached = self._artifacts.get(artifact_id)
        if cached is not None:
            return cached
        meta = Path(self.config.artifact_dir) / f"{artifact_id}.json"
        if not meta.exists():
            return None
        artifact = ArtifactRef.model_validate_json(meta.read_text())
        self._artifacts[artifact_id] = artifact
        return artifact

    def preview_artifact(self, artifact_id: str) -> ResultPreview | None:
        artifact = self.get_artifact(artifact_id)
        if artifact is None or not Path(artifact.path).is_file():
            return None
        return preview_parquet(artifact.path)

    def run_query(self, sql: str, principal: str, row_limit: int | None) -> QueryResponse:
        return self._execute(
            sql=sql,
            principal=principal,
            row_limit=row_limit,
            action="run_query",
            extra_params={"sql": sql},
            hash_payload=sql.strip(),
        )

    def run_analytic(
        self,
        analytic_id: str,
        principal: str,
        row_limit: int | None,
        version: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> QueryResponse:
        spec = self.registry.get(analytic_id, version)
        missing = [connector_id for connector_id in spec.allowed_connectors if connector_id not in self.connectors]
        if missing:
            return self._failed_response(
                sql=spec.sql,
                principal=principal,
                row_limit=row_limit,
                action="run_analytic",
                extra_params=_analytic_params(spec, params),
                hash_payload=_analytic_hash_payload(spec),
                error=f"analytic requires missing connectors: {', '.join(missing)}",
            )
        if spec.engine != self.engine.id:
            return self._failed_response(
                sql=spec.sql,
                principal=principal,
                row_limit=row_limit,
                action="run_analytic",
                extra_params=_analytic_params(spec, params),
                hash_payload=_analytic_hash_payload(spec),
                error=f"unsupported engine: {spec.engine}",
            )
        return self._execute(
            sql=spec.sql,
            principal=principal,
            row_limit=row_limit,
            action="run_analytic",
            extra_params=_analytic_params(spec, params),
            hash_payload=_analytic_hash_payload(spec),
        )

    def explain_stub(self, artifact_id: str | None = None) -> dict[str, object]:
        """M3 assist hook. Does not call a live model; never required for analytics."""
        if not self.llm.is_configured() or self.config.models.main is None:
            fields = assist_attribution(None)
            return {
                "used": False,
                "message": "No model configured. Analytics still work; receipt model fields stay empty.",
                **fields,
                "artifact_id": artifact_id,
            }
        fields = assist_attribution(self.config.models.main)
        return {
            "used": True,
            "message": "Assist is stubbed in M3; no model call was made. Attribution is recorded only for this hook.",
            **fields,
            "artifact_id": artifact_id,
        }

    def models_status(self, probe: bool = False) -> dict[str, object]:
        cfg = self.config.models
        body: dict[str, object] = {
            "configured": cfg.is_configured(),
            "main": cfg.main.model_dump(mode="json") if cfg.main else None,
            "auxiliary": cfg.auxiliary.model_dump(mode="json") if cfg.auxiliary else None,
            "fallback": [item.model_dump(mode="json") for item in cfg.fallback],
            "policy": cfg.policy.model_dump(mode="json"),
            "probe": None,
        }
        if probe and cfg.main is not None:
            probed = self.llm.probe("main")
            body["probe"] = probed.model_dump(mode="json") if probed is not None else None
        return body

    def _execute(
        self,
        sql: str,
        principal: str,
        row_limit: int | None,
        action: str,
        extra_params: dict[str, Any],
        hash_payload: str,
    ) -> QueryResponse:
        limits = self.config.limits
        applied_limit = min(row_limit or limits.default_row_limit, limits.max_row_limit)
        tables = [table for connector in self.connectors.values() for table in connector.discover_schema()]
        connector_versions = {connector.id: connector.version for connector in self.connectors.values()}

        artifact: ArtifactRef | None = None
        preview: ResultPreview | None = None
        error: str | None = None
        status: str = "succeeded"
        try:
            artifact = self.engine.execute(
                QueryPlan(
                    sql=sql,
                    row_limit=applied_limit,
                    timeout_seconds=limits.query_timeout_seconds,
                    artifact_dir=self.config.artifact_dir,
                    tables=tables,
                )
            )
            self._artifacts[artifact.artifact_id] = artifact
            Path(artifact.path).with_suffix(".json").write_text(artifact.model_dump_json())
            preview = preview_parquet(artifact.path)
        except (SqlGuardError, ValueError, FileNotFoundError, OSError, RuntimeError, duckdb.Error) as exc:
            status = "failed"
            error = str(exc)

        params = {**extra_params, "row_limit": applied_limit}
        receipt = self.receipts.append(
            Receipt(
                receipt_id=str(uuid4()),
                ts=datetime.now(timezone.utc),
                principal=principal,
                node_id=self.config.node_id,
                action=action,
                analytic_or_sql_hash=sha256_text(hash_payload),
                connector_versions=connector_versions,
                engine_version=self.engine.version,
                params=params,
                artifact_hash=artifact.sha256 if artifact else None,
                artifact_id=artifact.artifact_id if artifact else None,
                status=status,  # type: ignore[arg-type]
                prev_hash="",
                receipt_hash="",
                error=error,
            )
        )
        return QueryResponse(artifact=artifact, receipt=receipt, preview=preview)

    def _failed_response(
        self,
        sql: str,
        principal: str,
        row_limit: int | None,
        action: str,
        extra_params: dict[str, Any],
        hash_payload: str,
        error: str,
    ) -> QueryResponse:
        limits = self.config.limits
        applied_limit = min(row_limit or limits.default_row_limit, limits.max_row_limit)
        connector_versions = {connector.id: connector.version for connector in self.connectors.values()}
        receipt = self.receipts.append(
            Receipt(
                receipt_id=str(uuid4()),
                ts=datetime.now(timezone.utc),
                principal=principal,
                node_id=self.config.node_id,
                action=action,
                analytic_or_sql_hash=sha256_text(hash_payload),
                connector_versions=connector_versions,
                engine_version=self.engine.version,
                params={**extra_params, "row_limit": applied_limit, "sql": sql},
                status="failed",
                prev_hash="",
                receipt_hash="",
                error=error,
            )
        )
        return QueryResponse(artifact=None, receipt=receipt, preview=None)


def _analytic_params(spec: AnalyticSpec, params: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "analytic_id": spec.analytic_id,
        "version": spec.version,
        "sql": spec.sql,
        "params": params or {},
    }


def _analytic_hash_payload(spec: AnalyticSpec) -> str:
    return f"{spec.analytic_id}@{spec.version}\n{spec.sql.strip()}"

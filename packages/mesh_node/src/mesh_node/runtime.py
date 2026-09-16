from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb
import httpx
import pyarrow as pa

from mesh_common.artifacts import ArtifactStore, ArtifactTooLarge
from mesh_common.hashing import sha256_bytes, sha256_text
from mesh_common.identity import generate_keypair, load_or_create_keypair
from mesh_common.llm import LlmClient, describe_llm_error, extract_sql
from mesh_common.policy import PolicyDenied, PolicyEngine, load_policy
from mesh_common.preview import preview_parquet
from mesh_common.receipts import ReceiptStore
from mesh_common.registry import AnalyticRegistry
from mesh_common.schemas import (
    AnalyticSpec,
    ArtifactRef,
    AssistExplainResponse,
    AssistNl2SqlResponse,
    ConnectorInfo,
    ModelAttempt,
    QueryPlan,
    QueryResponse,
    Receipt,
    ResultPreview,
    TableSchema,
    UploadResponse,
)
from mesh_common.uploads import UploadRejected, sanitize_upload_filename, unique_destination
from mesh_connector_local_files import LocalFilesConnector
from mesh_engine_duckdb import DuckDBEngine, SqlGuardError
from mesh_engine_duckdb.sql_guard import validate_sql
from mesh_node.config import ConnectorConfig, NodeConfig

_NL2SQL_SYSTEM = (
    "You write DuckDB SQL for the given catalog. Reply with ONLY a single SELECT or WITH "
    "statement. No markdown, no commentary."
)
_EXPLAIN_SYSTEM = (
    "You explain a small analytics result table in a few sentences. Do not invent rows. "
    "You are given a capped preview only, never a full source table."
)


class NodeRuntime:
    def __init__(self, config: NodeConfig) -> None:
        self.config = config
        self.engines = _load_engines()
        self.engine = self.engines["duckdb"]
        self.identity = (
            load_or_create_keypair(config.identity_key_path, config.node_id)
            if config.identity_key_path is not None
            else generate_keypair(config.node_id)
        )
        self.receipts = ReceiptStore(config.receipt_db)
        self.artifacts = ArtifactStore(config.artifact_dir, config.artifacts)
        self.llm = LlmClient(config.models)
        self.policy: PolicyEngine = load_policy(config.policy_path)
        self.registry = (
            AnalyticRegistry.load(config.analytics_dir) if config.analytics_dir is not None else AnalyticRegistry.empty()
        )
        self.connectors: dict[str, Any] = {}
        for item in config.connectors:
            self.connectors[item.id] = _build_connector(item)
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

    def upload_file(
        self,
        *,
        filename: str | None,
        content: bytes,
        principal: str,
        connector_id: str | None = None,
    ) -> UploadResponse:
        connector = self._local_files_connector(connector_id)
        raw_name = filename or ""
        extra = {"filename": raw_name, "connector_id": connector.id}
        self._require(
            principal=principal,
            action="upload",
            connector_ids=[connector.id],
            hash_payload=raw_name,
            extra_params=extra,
        )
        try:
            stored_as = sanitize_upload_filename(filename)
            dest_dir = connector.uploads_dir
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = unique_destination(dest_dir, stored_as)
            try:
                dest.resolve().relative_to(dest_dir.resolve())
            except ValueError as exc:
                raise UploadRejected("upload destination escaped the uploads directory") from exc
            max_bytes = self.config.uploads.max_bytes
            if len(content) > max_bytes:
                raise UploadRejected(
                    f"file exceeds max upload size ({max_bytes} bytes)"
                )
            dest.write_bytes(content)
            try:
                schema = connector.schema_for_file(dest)
            except Exception as exc:  # noqa: BLE001 — invalid payload is a user error
                dest.unlink(missing_ok=True)
                raise UploadRejected(f"file is not a readable table: {exc}") from exc
        except UploadRejected as exc:
            receipt = self._upload_receipt(
                principal=principal,
                hash_value=sha256_text(raw_name),
                extra_params={**extra, "error": str(exc)},
                status="failed",
                error=str(exc),
            )
            raise UploadRejected(str(exc), receipt=receipt) from exc

        digest = sha256_bytes(content)
        tables = [schema]
        receipt = self._upload_receipt(
            principal=principal,
            hash_value=digest,
            extra_params={
                "filename": stored_as,
                "original_filename": raw_name,
                "bytes": len(content),
                "sha256": digest,
                "connector_id": connector.id,
                "tables": [table.name for table in tables],
                "path": str(dest),
            },
            status="succeeded",
        )
        return UploadResponse(
            filename=stored_as,
            stored_as=dest.name,
            bytes=len(content),
            sha256=digest,
            connector_id=connector.id,
            tables=tables,
            receipt=receipt,
        )

    def _upload_receipt(
        self,
        *,
        principal: str,
        hash_value: str,
        extra_params: dict[str, Any],
        status: str,
        error: str | None = None,
    ) -> Receipt:
        return self.receipts.append(
            Receipt(
                receipt_id=str(uuid4()),
                ts=datetime.now(timezone.utc),
                principal=principal,
                node_id=self.config.node_id,
                action="upload",
                analytic_or_sql_hash=hash_value,
                connector_versions={connector.id: connector.version for connector in self.connectors.values()},
                engine_version=self.engine.version,
                params=extra_params,
                status=status,  # type: ignore[arg-type]
                prev_hash="",
                receipt_hash="",
                error=error,
            )
        )

    def _local_files_connector(self, connector_id: str | None):
        if connector_id:
            connector = self.connectors.get(connector_id)
            if connector is None:
                raise UploadRejected(f"unknown connector: {connector_id}")
            if not isinstance(connector, LocalFilesConnector):
                raise UploadRejected(f"connector {connector_id} does not accept file uploads")
            return connector
        for connector in self.connectors.values():
            if isinstance(connector, LocalFilesConnector):
                return connector
        raise UploadRejected("no local_files connector is configured")

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

    def run_query(
        self,
        sql: str,
        principal: str,
        row_limit: int | None,
        assist_model_provider: str | None = None,
        assist_model_id: str | None = None,
    ) -> QueryResponse:
        decision = self._require(
            principal=principal,
            action="run_query",
            connector_ids=list(self.connectors),
            hash_payload=sql.strip(),
            extra_params={"sql": sql},
        )
        provider, model_id = self._assist_attribution(
            principal, assist_model_provider, assist_model_id, decision.model_mode
        )
        return self._execute(
            sql=sql,
            principal=principal,
            row_limit=row_limit,
            action="run_query",
            extra_params={"sql": sql},
            hash_payload=sql.strip(),
            policy_row_limit=decision.max_row_limit,
            policy_timeout=decision.query_timeout_seconds,
            model_provider=provider,
            model_id=model_id,
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
        self._require(
            principal=principal,
            action="run_analytic",
            connector_ids=spec.allowed_connectors or list(self.connectors),
            analytic_id=spec.analytic_id,
            hash_payload=_analytic_hash_payload(spec),
            extra_params=_analytic_params(spec, params),
        )
        extra = _analytic_params(spec, params)
        missing = [connector_id for connector_id in spec.allowed_connectors if connector_id not in self.connectors]
        if missing:
            return self._failed_response(
                sql=spec.sql,
                principal=principal,
                row_limit=row_limit,
                action="run_analytic",
                extra_params=extra,
                hash_payload=_analytic_hash_payload(spec),
                error=f"analytic requires missing connectors: {', '.join(missing)}",
            )
        engine = self.engines.get(spec.engine)
        if engine is None:
            return self._failed_response(
                sql=spec.sql,
                principal=principal,
                row_limit=row_limit,
                action="run_analytic",
                extra_params=extra,
                hash_payload=_analytic_hash_payload(spec),
                error=f"unsupported engine: {spec.engine}",
            )
        return self._execute(
            sql=spec.sql,
            principal=principal,
            row_limit=row_limit,
            action="run_analytic",
            extra_params=extra,
            hash_payload=_analytic_hash_payload(spec),
            engine=engine,
        )

    def propose_sql(self, question: str, principal: str) -> dict[str, object]:
        decision = self._require(
            principal=principal,
            action="assist_nl2sql",
            connector_ids=list(self.connectors),
            hash_payload=question.strip(),
            extra_params={"question": question},
            allow_missing_model=True,
        )
        empty = AssistNl2SqlResponse(
            used=False,
            confirmed=False,
            question=question,
            sql=None,
            message="No model configured. Analytics still work; propose SQL only after a model is configured.",
        )
        if not self.llm.is_configured():
            return empty.model_dump(mode="json")

        allow_frontier = self.llm.config.allows_frontier(decision.model_mode)
        slots = self.llm.candidate_slots("main", allow_frontier=allow_frontier)
        if not slots:
            self._deny(
                principal=principal,
                action="assist_nl2sql",
                hash_payload=question.strip(),
                extra_params={"question": question},
                reason="assist requires a local model when policy is local_only",
            )

        catalog = self._schema_catalog()
        messages = [
            {"role": "system", "content": _NL2SQL_SYSTEM},
            {"role": "user", "content": f"Catalog:\n{catalog}\n\nQuestion: {question}"},
        ]
        last_error = "model call failed"
        attempts: list[ModelAttempt] = []
        for slot_name, slot in slots:
            self._require(
                principal=principal,
                action="assist_nl2sql",
                connector_ids=list(self.connectors),
                hash_payload=question.strip(),
                extra_params={"question": question},
                model_provider=slot.provider,
            )
            try:
                raw = self.llm.complete(slot, messages, timeout=60.0)
                sql = validate_sql(extract_sql(raw))
            except (SqlGuardError, ValueError, OSError, RuntimeError, httpx.HTTPError) as exc:
                last_error = describe_llm_error(exc, slot)
                attempts.append(
                    ModelAttempt(
                        slot=slot_name,
                        provider=slot.provider,
                        model=slot.model,
                        status="failed",
                        error=last_error,
                    )
                )
                continue
            attempts.append(
                ModelAttempt(
                    slot=slot_name,
                    provider=slot.provider,
                    model=slot.model,
                    status="succeeded",
                )
            )
            fallback_used = slot_name.startswith("fallback")
            receipt = self._assist_receipt(
                principal=principal,
                action="assist_nl2sql",
                hash_payload=question.strip(),
                extra_params={"question": question, "sql": sql},
                model_provider=slot.provider,
                model_id=slot.model,
                model_slot=slot_name,
                model_fallback_used=fallback_used,
                model_attempts=attempts,
                status="succeeded",
            )
            return AssistNl2SqlResponse(
                used=True,
                confirmed=False,
                question=question,
                sql=sql,
                message="Proposed SQL only. Confirm explicitly before running; this endpoint never executes SQL.",
                model_provider=slot.provider,
                model_id=slot.model,
                model_slot=slot_name,
                model_fallback_used=fallback_used,
                receipt=receipt,
            ).model_dump(mode="json")

        receipt = self._assist_receipt(
            principal=principal,
            action="assist_nl2sql",
            hash_payload=question.strip(),
            extra_params={"question": question},
            status="failed",
            error=last_error,
            model_attempts=attempts,
        )
        return AssistNl2SqlResponse(
            used=False,
            confirmed=False,
            question=question,
            sql=None,
            message=last_error,
            receipt=receipt,
        ).model_dump(mode="json")

    def explain_result(self, artifact_id: str | None, principal: str) -> dict[str, object]:
        decision = self._require(
            principal=principal,
            action="assist_explain",
            hash_payload=artifact_id or "",
            extra_params={"artifact_id": artifact_id},
            allow_missing_model=True,
        )
        if not self.llm.is_configured():
            return AssistExplainResponse(
                used=False,
                artifact_id=artifact_id,
                message="No model configured. Analytics still work; receipt model fields stay empty.",
            ).model_dump(mode="json")

        allow_frontier = self.llm.config.allows_frontier(decision.model_mode)
        slots = self.llm.candidate_slots("auxiliary", allow_frontier=allow_frontier)
        if not slots:
            self._deny(
                principal=principal,
                action="assist_explain",
                hash_payload=artifact_id or "",
                extra_params={"artifact_id": artifact_id},
                reason="explain assist requires a local model when policy is local_only",
            )

        preview = self.preview_artifact(artifact_id) if artifact_id else None
        preview_payload = preview.model_dump(mode="json") if preview else None
        messages = [
            {"role": "system", "content": _EXPLAIN_SYSTEM},
            {
                "role": "user",
                "content": f"Artifact {artifact_id}. Capped preview JSON:\n{preview_payload}",
            },
        ]
        last_error = "model call failed"
        attempts: list[ModelAttempt] = []
        for slot_name, slot in slots:
            self._require(
                principal=principal,
                action="assist_explain",
                hash_payload=artifact_id or "",
                extra_params={"artifact_id": artifact_id},
                model_provider=slot.provider,
            )
            try:
                text = self.llm.complete(slot, messages, timeout=60.0)
            except (ValueError, OSError, RuntimeError, httpx.HTTPError) as exc:
                last_error = describe_llm_error(exc, slot)
                attempts.append(
                    ModelAttempt(
                        slot=slot_name,
                        provider=slot.provider,
                        model=slot.model,
                        status="failed",
                        error=last_error,
                    )
                )
                continue
            attempts.append(
                ModelAttempt(
                    slot=slot_name,
                    provider=slot.provider,
                    model=slot.model,
                    status="succeeded",
                )
            )
            fallback_used = slot_name.startswith("fallback")
            receipt = self._assist_receipt(
                principal=principal,
                action="assist_explain",
                hash_payload=artifact_id or "",
                extra_params={"artifact_id": artifact_id},
                model_provider=slot.provider,
                model_id=slot.model,
                model_slot=slot_name,
                model_fallback_used=fallback_used,
                model_attempts=attempts,
                status="succeeded",
            )
            return AssistExplainResponse(
                used=True,
                artifact_id=artifact_id,
                explanation=text,
                message="Explain assist used a capped preview only.",
                model_provider=slot.provider,
                model_id=slot.model,
                model_slot=slot_name,
                model_fallback_used=fallback_used,
                receipt=receipt,
            ).model_dump(mode="json")

        receipt = self._assist_receipt(
            principal=principal,
            action="assist_explain",
            hash_payload=artifact_id or "",
            extra_params={"artifact_id": artifact_id},
            status="failed",
            error=last_error,
            model_attempts=attempts,
        )
        return AssistExplainResponse(
            used=False,
            artifact_id=artifact_id,
            message=last_error,
            receipt=receipt,
        ).model_dump(mode="json")

    def explain_stub(self, artifact_id: str | None = None) -> dict[str, object]:
        return self.explain_result(artifact_id, "local")

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

    def _schema_catalog(self) -> str:
        lines: list[str] = []
        for info in self.list_connectors():
            for table in info.tables:
                cols = ", ".join(f"{col.name}:{col.type}" for col in table.columns)
                lines.append(f"{table.name} ({info.id}) [{cols}]")
        return "\n".join(lines) if lines else "(no tables)"

    def _require(
        self,
        *,
        principal: str,
        action: str,
        hash_payload: str,
        extra_params: dict[str, Any],
        connector_ids: list[str] | None = None,
        analytic_id: str | None = None,
        model_provider: str | None = None,
        allow_missing_model: bool = False,
    ):
        del allow_missing_model
        decision = self.policy.authorize(
            principal=principal,
            action=action,
            node_id=self.config.node_id,
            connector_ids=connector_ids,
            analytic_id=analytic_id,
            model_provider=model_provider,
            llm_default_mode=self.llm.config.policy.default_mode,
        )
        if not decision.allowed:
            self._deny(
                principal=principal,
                action=action,
                hash_payload=hash_payload,
                extra_params=extra_params,
                reason=decision.reason or "denied by policy",
                model_provider=model_provider,
            )
        return decision

    def _deny(
        self,
        *,
        principal: str,
        action: str,
        hash_payload: str,
        extra_params: dict[str, Any],
        reason: str,
        model_provider: str | None = None,
    ) -> None:
        receipt = self._assist_receipt(
            principal=principal,
            action=action,
            hash_payload=hash_payload,
            extra_params=extra_params,
            status="failed",
            error=reason,
            model_provider=model_provider,
        )
        raise PolicyDenied(reason, receipt=receipt)

    def _assist_attribution(
        self,
        principal: str,
        provider: str | None,
        model_id: str | None,
        model_mode: str,
    ) -> tuple[str | None, str | None]:
        if not provider and not model_id:
            return None, None
        decision = self.policy.authorize(
            principal=principal,
            action="assist_nl2sql",
            node_id=self.config.node_id,
            model_provider=provider,
            llm_default_mode=self.llm.config.policy.default_mode,
        )
        if not decision.allowed:
            return None, None
        if provider == "frontier" and model_mode == "local_only" and decision.model_mode == "local_only":
            return None, None
        return provider, model_id

    def _materialize_tables(self, tables: list[TableSchema]) -> dict[str, pa.Table]:
        arrow_tables: dict[str, pa.Table] = {}
        for table in tables:
            if table.format in {"csv", "parquet", "json"}:
                continue
            connector = self.connectors.get(table.connector_id)
            if connector is None:
                continue
            batches = list(connector.scan(table.name))
            if batches:
                arrow_tables[table.name] = pa.Table.from_batches(batches)
            else:
                arrow_tables[table.name] = pa.table({col.name: [] for col in table.columns})
        return arrow_tables

    def _execute(
        self,
        sql: str,
        principal: str,
        row_limit: int | None,
        action: str,
        extra_params: dict[str, Any],
        hash_payload: str,
        policy_row_limit: int | None = None,
        policy_timeout: float | None = None,
        model_provider: str | None = None,
        model_id: str | None = None,
        engine: Any | None = None,
    ) -> QueryResponse:
        engine = engine or self.engine
        limits = self.config.limits
        applied_limit = min(row_limit or limits.default_row_limit, limits.max_row_limit)
        if policy_row_limit is not None:
            applied_limit = min(applied_limit, policy_row_limit)
        timeout = limits.query_timeout_seconds
        if policy_timeout is not None:
            timeout = min(timeout, policy_timeout)
        tables = [table for connector in self.connectors.values() for table in connector.discover_schema()]
        connector_versions = {connector.id: connector.version for connector in self.connectors.values()}
        arrow_tables = self._materialize_tables(tables)

        artifact: ArtifactRef | None = None
        preview: ResultPreview | None = None
        error: str | None = None
        status: str = "succeeded"
        try:
            artifact = engine.execute(
                QueryPlan(
                    sql=sql,
                    row_limit=applied_limit,
                    timeout_seconds=timeout,
                    artifact_dir=self.config.artifact_dir,
                    tables=tables,
                ),
                arrow_tables=arrow_tables,
            )
            artifact = self.artifacts.commit(artifact)
            self._artifacts[artifact.artifact_id] = artifact
            preview = preview_parquet(artifact.path)
        except (SqlGuardError, ValueError, FileNotFoundError, OSError, RuntimeError, duckdb.Error, ArtifactTooLarge) as exc:
            status = "failed"
            error = str(exc)
            artifact = None
            preview = None

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
                engine_version=engine.version,
                params=params,
                artifact_hash=artifact.sha256 if artifact else None,
                artifact_id=artifact.artifact_id if artifact else None,
                status=status,  # type: ignore[arg-type]
                prev_hash="",
                receipt_hash="",
                model_provider=model_provider,
                model_id=model_id,
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

    def _assist_receipt(
        self,
        *,
        principal: str,
        action: str,
        hash_payload: str,
        extra_params: dict[str, Any],
        status: str = "succeeded",
        error: str | None = None,
        model_provider: str | None = None,
        model_id: str | None = None,
        model_slot: str | None = None,
        model_fallback_used: bool = False,
        model_attempts: list[ModelAttempt] | None = None,
    ) -> Receipt:
        return self.receipts.append(
            Receipt(
                receipt_id=str(uuid4()),
                ts=datetime.now(timezone.utc),
                principal=principal,
                node_id=self.config.node_id,
                action=action,
                analytic_or_sql_hash=sha256_text(hash_payload),
                connector_versions={connector.id: connector.version for connector in self.connectors.values()},
                engine_version=self.engine.version,
                params=extra_params,
                status=status,  # type: ignore[arg-type]
                prev_hash="",
                receipt_hash="",
                model_provider=model_provider,
                model_id=model_id,
                model_slot=model_slot,
                model_fallback_used=model_fallback_used,
                model_attempts=list(model_attempts or []),
                error=error,
            )
        )


def _load_engines() -> dict[str, Any]:
    engines: dict[str, Any] = {"duckdb": DuckDBEngine()}
    try:
        from mesh_engine_polars import PolarsEngine

        engines["polars"] = PolarsEngine()
    except ImportError:
        pass
    return engines


def _build_connector(item: ConnectorConfig):
    if item.type == "local_files":
        if item.root is None:
            raise ValueError("local_files connector requires root")
        return LocalFilesConnector(
            root=item.root,
            connector_id=item.id,
            labels=item.labels,
            uploads_path=item.uploads_path,
        )
    if item.type == "postgres":
        from mesh_connector_postgres import PostgresConnector

        return PostgresConnector(
            connector_id=item.id,
            dsn=item.dsn,
            dsn_env=item.dsn_env,
            schemas=item.schemas,
            labels=item.labels,
        )
    raise ValueError(f"unsupported connector type: {item.type}")


def _analytic_params(spec: AnalyticSpec, params: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "analytic_id": spec.analytic_id,
        "version": spec.version,
        "engine": spec.engine,
        "sql": spec.sql,
        "params": params or {},
    }


def _analytic_hash_payload(spec: AnalyticSpec) -> str:
    return f"{spec.analytic_id}@{spec.version}\n{spec.sql.strip()}"

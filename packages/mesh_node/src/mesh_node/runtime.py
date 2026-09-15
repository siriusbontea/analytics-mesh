from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import duckdb

from mesh_common.hashing import sha256_text
from mesh_common.identity import generate_keypair, load_or_create_keypair
from mesh_common.receipts import ReceiptStore
from mesh_common.schemas import ArtifactRef, ConnectorInfo, QueryPlan, QueryResponse, Receipt
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

    def run_query(self, sql: str, principal: str, row_limit: int | None) -> QueryResponse:
        limits = self.config.limits
        applied_limit = min(row_limit or limits.default_row_limit, limits.max_row_limit)
        tables = [table for connector in self.connectors.values() for table in connector.discover_schema()]
        connector_versions = {connector.id: connector.version for connector in self.connectors.values()}

        artifact: ArtifactRef | None = None
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
        except (SqlGuardError, ValueError, FileNotFoundError, OSError, RuntimeError, duckdb.Error) as exc:
            status = "failed"
            error = str(exc)

        receipt = self.receipts.append(
            Receipt(
                receipt_id=str(uuid4()),
                ts=datetime.now(timezone.utc),
                principal=principal,
                node_id=self.config.node_id,
                action="run_query",
                analytic_or_sql_hash=sha256_text(sql.strip()),
                connector_versions=connector_versions,
                engine_version=self.engine.version,
                params={"sql": sql, "row_limit": applied_limit},
                artifact_hash=artifact.sha256 if artifact else None,
                artifact_id=artifact.artifact_id if artifact else None,
                status=status,  # type: ignore[arg-type]
                prev_hash="",
                receipt_hash="",
                error=error,
            )
        )
        return QueryResponse(artifact=artifact, receipt=receipt)

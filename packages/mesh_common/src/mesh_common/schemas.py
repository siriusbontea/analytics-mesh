from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class ColumnSchema(BaseModel):
    name: str
    type: str


class TableSchema(BaseModel):
    name: str
    connector_id: str
    columns: list[ColumnSchema] = Field(default_factory=list)
    source_path: str | None = None
    format: Literal["csv", "parquet", "json"] | None = None


class ConnectorInfo(BaseModel):
    id: str
    version: str
    sensitivity_labels: list[str] = Field(default_factory=list)
    tables: list[TableSchema] = Field(default_factory=list)


class ArtifactRef(BaseModel):
    artifact_id: str
    path: str
    format: Literal["parquet", "csv"] = "parquet"
    sha256: str
    row_count: int
    column_names: list[str] = Field(default_factory=list)


class Receipt(BaseModel):
    receipt_id: str
    ts: datetime
    principal: str
    node_id: str
    action: str
    analytic_or_sql_hash: str
    connector_versions: dict[str, str] = Field(default_factory=dict)
    engine_version: str
    params: dict[str, Any] = Field(default_factory=dict)
    artifact_hash: str | None = None
    artifact_id: str | None = None
    status: Literal["succeeded", "failed"]
    prev_hash: str
    receipt_hash: str
    model_provider: str | None = None
    model_id: str | None = None
    error: str | None = None


class ChainVerification(BaseModel):
    valid: bool
    count: int
    head_hash: str
    error: str | None = None


class QueryPlan(BaseModel):
    sql: str
    row_limit: int = 10_000
    timeout_seconds: float = 30.0
    artifact_dir: Path
    tables: list[TableSchema] = Field(default_factory=list)


class QueryRequest(BaseModel):
    sql: str
    row_limit: int | None = None
    principal: str = "local"


class QueryResponse(BaseModel):
    artifact: ArtifactRef | None = None
    receipt: Receipt


class NodeRegistrationRequest(BaseModel):
    node_id: str
    endpoint: str
    public_key: str
    labels: list[str] = Field(default_factory=list)
    token: str
    signed_at: str
    signature: str


class NodeRecord(BaseModel):
    node_id: str
    endpoint: str
    public_key: str
    labels: list[str] = Field(default_factory=list)
    registered_at: datetime
    last_seen: datetime | None = None


class JobRecord(BaseModel):
    job_id: str
    node_id: str
    action: str
    status: Literal["queued", "running", "succeeded", "failed"]
    principal: str
    created_at: datetime
    updated_at: datetime
    artifact_id: str | None = None
    artifact_pointer: str | None = None
    receipt_id: str | None = None
    receipt_pointer: str | None = None
    sql_hash: str | None = None
    error: str | None = None


class PlaneQueryRequest(BaseModel):
    node_id: str
    sql: str
    row_limit: int | None = None
    principal: str = "local"


class PlaneQueryResponse(BaseModel):
    job: JobRecord
    artifact: ArtifactRef | None = None
    receipt: Receipt | None = None

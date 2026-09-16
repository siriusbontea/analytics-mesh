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
    format: Literal["csv", "parquet", "json", "postgres"] | None = None


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


class ModelAttempt(BaseModel):
    """One slot tried during an assist fallback chain."""

    slot: str
    provider: str
    model: str
    status: Literal["succeeded", "failed"]
    error: str | None = None


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
    model_slot: str | None = None
    model_fallback_used: bool = False
    model_attempts: list[ModelAttempt] = Field(default_factory=list)
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


class ResultPreview(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False


class AnalyticSpec(BaseModel):
    analytic_id: str
    version: str
    engine: str = "duckdb"
    entry: str
    sql: str
    allowed_connectors: list[str] = Field(default_factory=list)
    description: str = ""
    params_schema: dict[str, Any] = Field(default_factory=dict)
    path: str | None = None


class AnalyticRunRequest(BaseModel):
    analytic_id: str
    version: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    row_limit: int | None = None
    principal: str = "local"


class QueryRequest(BaseModel):
    sql: str
    row_limit: int | None = None
    principal: str = "local"
    assist_model_provider: str | None = None
    assist_model_id: str | None = None


class QueryResponse(BaseModel):
    artifact: ArtifactRef | None = None
    receipt: Receipt
    preview: ResultPreview | None = None


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


class AssistNl2SqlRequest(BaseModel):
    question: str
    principal: str = "local"


class AssistExplainRequest(BaseModel):
    artifact_id: str | None = None
    principal: str = "local"


class AssistNl2SqlResponse(BaseModel):
    used: bool
    confirmed: bool = False
    question: str
    sql: str | None = None
    message: str
    model_provider: str | None = None
    model_id: str | None = None
    model_slot: str | None = None
    model_fallback_used: bool = False
    receipt: Receipt | None = None


class AssistExplainResponse(BaseModel):
    used: bool
    artifact_id: str | None = None
    explanation: str | None = None
    message: str
    model_provider: str | None = None
    model_id: str | None = None
    model_slot: str | None = None
    model_fallback_used: bool = False
    receipt: Receipt | None = None


class PlaneQueryRequest(BaseModel):
    node_id: str
    sql: str
    row_limit: int | None = None
    principal: str = "local"
    assist_model_provider: str | None = None
    assist_model_id: str | None = None


class PlaneAnalyticRunRequest(BaseModel):
    node_id: str
    analytic_id: str
    version: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    row_limit: int | None = None
    principal: str = "local"


class PlaneQueryResponse(BaseModel):
    job: JobRecord
    artifact: ArtifactRef | None = None
    receipt: Receipt | None = None
    preview: ResultPreview | None = None


class UploadResponse(BaseModel):
    filename: str
    stored_as: str
    bytes: int
    sha256: str
    connector_id: str
    tables: list[TableSchema] = Field(default_factory=list)
    receipt: Receipt

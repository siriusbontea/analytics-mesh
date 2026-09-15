"""Shared schemas, receipts, protocols, and LLM config for Analytics Mesh."""

from mesh_common.hashing import sha256_bytes, sha256_file, sha256_text
from mesh_common.identity import NodeKeyPair, generate_keypair, load_or_create_keypair
from mesh_common.llm import (
    LlmClient,
    LlmProviderConfig,
    LlmSlotConfig,
    OpenAICompatibleClient,
    assist_attribution,
    load_llm_config,
    probe_models,
)
from mesh_common.receipts import GENESIS_HASH, ReceiptStore
from mesh_common.registry import AnalyticRegistry, AnalyticSpecError
from mesh_common.schemas import (
    AnalyticRunRequest,
    AnalyticSpec,
    ArtifactRef,
    ChainVerification,
    ColumnSchema,
    ConnectorInfo,
    JobRecord,
    NodeRecord,
    NodeRegistrationRequest,
    PlaneAnalyticRunRequest,
    PlaneQueryRequest,
    PlaneQueryResponse,
    QueryPlan,
    QueryRequest,
    QueryResponse,
    Receipt,
    ResultPreview,
    TableSchema,
)

__version__ = "0.1.0"

__all__ = [
    "AnalyticRegistry",
    "AnalyticRunRequest",
    "AnalyticSpec",
    "AnalyticSpecError",
    "ArtifactRef",
    "ChainVerification",
    "ColumnSchema",
    "ConnectorInfo",
    "GENESIS_HASH",
    "JobRecord",
    "NodeKeyPair",
    "NodeRecord",
    "NodeRegistrationRequest",
    "LlmClient",
    "LlmProviderConfig",
    "LlmSlotConfig",
    "OpenAICompatibleClient",
    "PlaneAnalyticRunRequest",
    "PlaneQueryRequest",
    "PlaneQueryResponse",
    "QueryPlan",
    "QueryRequest",
    "QueryResponse",
    "Receipt",
    "ReceiptStore",
    "ResultPreview",
    "TableSchema",
    "generate_keypair",
    "assist_attribution",
    "load_llm_config",
    "probe_models",
    "load_or_create_keypair",
    "sha256_bytes",
    "sha256_file",
    "sha256_text",
]

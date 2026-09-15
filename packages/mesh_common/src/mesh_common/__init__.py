"""Shared schemas, receipts, protocols, and LLM config for Analytics Mesh."""

from mesh_common.hashing import sha256_bytes, sha256_file, sha256_text
from mesh_common.identity import NodeKeyPair, generate_keypair, load_or_create_keypair
from mesh_common.llm import LlmProviderConfig, LlmSlotConfig, load_llm_config
from mesh_common.receipts import GENESIS_HASH, ReceiptStore
from mesh_common.schemas import (
    ArtifactRef,
    ChainVerification,
    ColumnSchema,
    ConnectorInfo,
    JobRecord,
    NodeRecord,
    NodeRegistrationRequest,
    PlaneQueryRequest,
    PlaneQueryResponse,
    QueryPlan,
    QueryRequest,
    QueryResponse,
    Receipt,
    TableSchema,
)

__version__ = "0.1.0"

__all__ = [
    "ArtifactRef",
    "ChainVerification",
    "ColumnSchema",
    "ConnectorInfo",
    "GENESIS_HASH",
    "JobRecord",
    "NodeKeyPair",
    "NodeRecord",
    "NodeRegistrationRequest",
    "LlmProviderConfig",
    "LlmSlotConfig",
    "PlaneQueryRequest",
    "PlaneQueryResponse",
    "QueryPlan",
    "QueryRequest",
    "QueryResponse",
    "Receipt",
    "ReceiptStore",
    "TableSchema",
    "generate_keypair",
    "load_llm_config",
    "load_or_create_keypair",
    "sha256_bytes",
    "sha256_file",
    "sha256_text",
]

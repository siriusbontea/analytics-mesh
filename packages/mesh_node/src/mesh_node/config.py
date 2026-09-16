from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from mesh_common.artifacts import ArtifactStoreConfig
from mesh_common.llm import LlmProviderConfig, load_llm_config
from mesh_common.secrets import resolve_pair_token


class ConnectorConfig(BaseModel):
    id: str = "local_files"
    type: str = "local_files"
    root: Path | None = None
    labels: list[str] = Field(default_factory=list)
    dsn: str | None = None
    dsn_env: str | None = None
    schemas: list[str] = Field(default_factory=lambda: ["public"])


class LimitsConfig(BaseModel):
    default_row_limit: int = 10_000
    max_row_limit: int = 100_000
    query_timeout_seconds: float = 30.0


class PlaneClientConfig(BaseModel):
    url: str
    token: str | None = None
    pair_token_env: str | None = None
    register_on_start: bool = True
    public_endpoint: str | None = None

    def resolved_token(self) -> str:
        return resolve_pair_token(self.token, pair_token_env=self.pair_token_env)


class NodeConfig(BaseModel):
    node_id: str = "local-dev"
    artifact_dir: Path = Path("var/artifacts")
    receipt_db: Path = Path("var/receipts.sqlite")
    identity_key_path: Path | None = None
    labels: list[str] = Field(default_factory=list)
    connectors: list[ConnectorConfig] = Field(default_factory=list)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    models: LlmProviderConfig = Field(default_factory=LlmProviderConfig)
    models_path: Path | None = None
    analytics_dir: Path | None = None
    policy_path: Path | None = None
    artifacts: ArtifactStoreConfig = Field(default_factory=ArtifactStoreConfig)
    listen_host: str = "127.0.0.1"
    listen_port: int = 8080
    plane: PlaneClientConfig | None = None

    def resolved_listen_host(self) -> str:
        return os.environ.get("MESH_LISTEN_HOST") or self.listen_host

    def resolved_listen_port(self) -> int:
        raw = os.environ.get("MESH_LISTEN_PORT")
        return int(raw) if raw else self.listen_port

    def resolve_paths(self, base: Path) -> NodeConfig:
        def resolve(path: Path) -> Path:
            return path if path.is_absolute() else (base / path).resolve()

        updates: dict[str, object] = {
            "artifact_dir": resolve(self.artifact_dir),
            "receipt_db": resolve(self.receipt_db),
            "connectors": [
                item.model_copy(update={"root": resolve(item.root)}) if item.root is not None else item
                for item in self.connectors
            ],
        }
        if self.identity_key_path is not None:
            updates["identity_key_path"] = resolve(self.identity_key_path)
        if self.analytics_dir is not None:
            updates["analytics_dir"] = resolve(self.analytics_dir)
        if self.models_path is not None:
            updates["models_path"] = resolve(self.models_path)
        if self.policy_path is not None:
            updates["policy_path"] = resolve(self.policy_path)
        return self.model_copy(update=updates)


def load_config(path: Path | str) -> NodeConfig:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text()) or {}
    models_path = raw.get("models_path")
    if models_path and "models" not in raw:
        models_file = Path(models_path)
        if not models_file.is_absolute():
            models_file = Path.cwd() / models_file
        raw["models"] = load_llm_config(models_file).model_dump(mode="json")
    cfg = NodeConfig.model_validate(raw)
    return cfg.resolve_paths(Path.cwd())

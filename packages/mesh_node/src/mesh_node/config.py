from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from mesh_common.llm import LlmProviderConfig


class ConnectorConfig(BaseModel):
    id: str = "local_files"
    type: str = "local_files"
    root: Path
    labels: list[str] = Field(default_factory=list)


class LimitsConfig(BaseModel):
    default_row_limit: int = 10_000
    max_row_limit: int = 100_000
    query_timeout_seconds: float = 30.0


class NodeConfig(BaseModel):
    node_id: str = "local-dev"
    artifact_dir: Path = Path("var/artifacts")
    receipt_db: Path = Path("var/receipts.sqlite")
    connectors: list[ConnectorConfig] = Field(default_factory=list)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    models: LlmProviderConfig = Field(default_factory=LlmProviderConfig)
    listen_host: str = "127.0.0.1"
    listen_port: int = 8080

    def resolve_paths(self, base: Path) -> NodeConfig:
        def resolve(path: Path) -> Path:
            return path if path.is_absolute() else (base / path).resolve()

        return self.model_copy(
            update={
                "artifact_dir": resolve(self.artifact_dir),
                "receipt_db": resolve(self.receipt_db),
                "connectors": [
                    item.model_copy(update={"root": resolve(item.root)}) for item in self.connectors
                ],
            }
        )


def load_config(path: Path | str) -> NodeConfig:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text()) or {}
    cfg = NodeConfig.model_validate(raw)
    return cfg.resolve_paths(Path.cwd())

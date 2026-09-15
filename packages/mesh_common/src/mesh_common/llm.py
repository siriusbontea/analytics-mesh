from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class LlmSlotConfig(BaseModel):
    """One OpenAI-compatible backend (local or frontier)."""

    provider: Literal["local", "frontier"]
    base_url: str
    model: str
    api_key_env: str | None = None


class LlmPolicyConfig(BaseModel):
    default_mode: Literal["local_only", "allow_frontier"] = "local_only"
    allow_frontier_analytics: list[str] = Field(default_factory=list)


class LlmProviderConfig(BaseModel):
    """Config shape for later NL→SQL / explain assist. Unused by M1 analytics."""

    main: LlmSlotConfig | None = None
    auxiliary: LlmSlotConfig | None = None
    fallback: list[LlmSlotConfig] = Field(default_factory=list)
    policy: LlmPolicyConfig = Field(default_factory=LlmPolicyConfig)

    def is_configured(self) -> bool:
        return self.main is not None


class LlmClient:
    """Stub client. Analytics must not require this to be configured."""

    def __init__(self, config: LlmProviderConfig | None = None) -> None:
        self.config = config or LlmProviderConfig()

    def is_configured(self) -> bool:
        return self.config.is_configured()


def load_llm_config(path: Path | str) -> LlmProviderConfig:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return LlmProviderConfig.model_validate(raw)

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import httpx
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
    """OpenAI-compatible provider slots. Analytics work with this empty."""

    main: LlmSlotConfig | None = None
    auxiliary: LlmSlotConfig | None = None
    fallback: list[LlmSlotConfig] = Field(default_factory=list)
    policy: LlmPolicyConfig = Field(default_factory=LlmPolicyConfig)

    def is_configured(self) -> bool:
        return self.main is not None

    def allows_frontier(self, principal_mode: str | None = None) -> bool:
        """Frontier slots are eligible if the models file or the principal opts in."""
        return self.policy.default_mode == "allow_frontier" or principal_mode == "allow_frontier"


class ModelProbeResult(BaseModel):
    ok: bool
    provider: str
    model: str
    base_url: str
    models: list[str] = Field(default_factory=list)
    error: str | None = None


def slot_headers(slot: LlmSlotConfig) -> dict[str, str]:
    if not slot.api_key_env:
        return {}
    key = os.environ.get(slot.api_key_env)
    if not key:
        raise RuntimeError(
            f"{slot.api_key_env} is not set. Export that environment variable before "
            f"calling {slot.model} at {slot.base_url}."
        )
    return {"Authorization": f"Bearer {key}"}


def probe_models(base_url: str, api_key: str | None = None, timeout: float = 5.0) -> list[str]:
    """GET {base_url}/models (OpenAI-compatible, e.g. http://127.0.0.1:11434/v1)."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    response = httpx.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    return [item["id"] for item in payload.get("data", []) if isinstance(item, dict) and item.get("id")]


def llm_health_fields(config: LlmProviderConfig | None = None) -> dict[str, object]:
    """Compact slot status for /health, /models, and the UI chip.

    Labels are Local (main.provider=local), Grok (frontier main, typically
    xAI via https://api.x.ai/v1), or None. Chip text does not imply a model
    is reachable — only that a slot is configured.
    """
    cfg = config or LlmProviderConfig()
    if not cfg.is_configured() or cfg.main is None:
        return {"llm_configured": False, "llm_kind": "none", "llm_label": "None"}
    main = cfg.main
    if main.provider == "local":
        kind, label = "local", "Local"
    else:
        kind, label = "frontier", "Grok"
    return {
        "llm_configured": True,
        "llm_kind": kind,
        "llm_label": label,
        "llm_model": main.model,
    }


def assist_attribution(slot: LlmSlotConfig | None) -> dict[str, str | None]:
    """Receipt fields for an assist path. Core query/analytic runs pass None."""
    if slot is None:
        return {"model_provider": None, "model_id": None}
    return {"model_provider": slot.provider, "model_id": slot.model}


def describe_llm_error(exc: BaseException, slot: LlmSlotConfig) -> str:
    """Human-readable assist error: endpoint down vs model missing vs other."""
    base = slot.base_url.rstrip("/")
    model = slot.model
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        if slot.provider == "local":
            return (
                f"Local model endpoint is unreachable at {base}. "
                "Start Ollama (`ollama serve`) or LM Studio, then probe "
                f"GET {base}/models (or run scripts/check-models.sh)."
            )
        return f"Could not connect to {slot.provider} model endpoint {base} for model {model}."
    if isinstance(exc, httpx.TimeoutException):
        return (
            f"Timed out talking to {base} for model {model}. "
            "The endpoint may still be loading weights or the generation ran long."
        )
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        try:
            body = exc.response.text
        except Exception:
            body = ""
        if _looks_like_missing_model(body, model):
            return (
                f"Model {model!r} was not found at {base}. "
                f"Pull a local tag (for example `ollama pull {model}`) "
                f"or set model: to an id from GET {base}/models."
            )
        snippet = " ".join(body.split())
        if len(snippet) > 240:
            snippet = snippet[:237] + "..."
        extra = f" Check that base_url ends with /v1 and GET {base}/models succeeds." if status == 404 else ""
        return f"Model endpoint {base} returned HTTP {status} for {model}: {snippet or exc}.{extra}".rstrip(".")
    text = str(exc).strip()
    return text or "model call failed"


def _looks_like_missing_model(body: str, model: str) -> bool:
    lowered = body.lower()
    model_l = model.lower()
    if "model not found" in lowered or "model does not exist" in lowered:
        return True
    if model_l and model_l in lowered and ("not found" in lowered or "does not exist" in lowered):
        return True
    return False


class LlmNotConfigured(RuntimeError):
    """Assist requested but no provider slot is configured."""


class OpenAICompatibleClient:
    """One interface for Ollama, LM Studio, vLLM, xAI Grok, OpenRouter, and other /v1 backends."""

    def __init__(self, slot: LlmSlotConfig, timeout: float = 5.0) -> None:
        self.slot = slot
        self.timeout = timeout

    def list_models(self) -> list[str]:
        api_key = os.environ.get(self.slot.api_key_env) if self.slot.api_key_env else None
        return probe_models(self.slot.base_url, api_key=api_key, timeout=self.timeout)

    def chat(self, messages: list[dict[str, str]], timeout: float | None = None) -> str:
        response = httpx.post(
            f"{self.slot.base_url.rstrip('/')}/chat/completions",
            json={"model": self.slot.model, "messages": messages, "temperature": 0},
            headers=slot_headers(self.slot),
            timeout=timeout or self.timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("model returned empty content")
        return content

    def probe(self) -> ModelProbeResult:
        try:
            models = self.list_models()
            return ModelProbeResult(
                ok=True,
                provider=self.slot.provider,
                model=self.slot.model,
                base_url=self.slot.base_url,
                models=models,
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            return ModelProbeResult(
                ok=False,
                provider=self.slot.provider,
                model=self.slot.model,
                base_url=self.slot.base_url,
                error=str(exc),
            )


class LlmClient:
    """Config + optional probe. Analytics must not require this to be configured."""

    def __init__(self, config: LlmProviderConfig | None = None) -> None:
        self.config = config or LlmProviderConfig()

    def is_configured(self) -> bool:
        return self.config.is_configured()

    def slots(self) -> list[tuple[str, LlmSlotConfig]]:
        items: list[tuple[str, LlmSlotConfig]] = []
        if self.config.main is not None:
            items.append(("main", self.config.main))
        if self.config.auxiliary is not None:
            items.append(("auxiliary", self.config.auxiliary))
        for index, slot in enumerate(self.config.fallback):
            items.append((f"fallback" if index == 0 else f"fallback[{index}]", slot))
        return items

    def probe(self, slot_name: str = "main") -> ModelProbeResult | None:
        for name, slot in self.slots():
            if name == slot_name or (slot_name == "fallback" and name.startswith("fallback")):
                return OpenAICompatibleClient(slot).probe()
        return None

    def complete(self, slot: LlmSlotConfig, messages: list[dict[str, str]], timeout: float = 60.0) -> str:
        return OpenAICompatibleClient(slot, timeout=timeout).chat(messages, timeout=timeout)

    def candidate_slots(
        self, purpose: Literal["main", "auxiliary"], allow_frontier: bool
    ) -> list[tuple[str, LlmSlotConfig]]:
        """Ordered (slot_name, slot) chain: main or auxiliary first, then configured fallbacks."""
        ordered: list[tuple[str, LlmSlotConfig]] = []
        if purpose == "auxiliary" and self.config.auxiliary is not None:
            ordered.append(("auxiliary", self.config.auxiliary))
        elif self.config.main is not None:
            ordered.append(("main", self.config.main))
        for index, slot in enumerate(self.config.fallback):
            name = "fallback" if index == 0 else f"fallback[{index}]"
            ordered.append((name, slot))
        filtered = [(name, slot) for name, slot in ordered if allow_frontier or slot.provider == "local"]
        seen: set[tuple[str, str, str]] = set()
        unique: list[tuple[str, LlmSlotConfig]] = []
        for name, slot in filtered:
            key = (slot.provider, slot.base_url, slot.model)
            if key in seen:
                continue
            seen.add(key)
            unique.append((name, slot))
        return unique


def extract_sql(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def load_llm_config(path: Path | str) -> LlmProviderConfig:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return LlmProviderConfig.model_validate(raw)

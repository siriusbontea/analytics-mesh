from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from mesh_common.llm import (
    LlmClient,
    LlmProviderConfig,
    LlmSlotConfig,
    OpenAICompatibleClient,
    assist_attribution,
    load_llm_config,
    probe_models,
)
from mesh_common.schemas import Receipt


def test_empty_config_is_not_configured():
    cfg = LlmProviderConfig()
    assert cfg.is_configured() is False


def test_models_yaml_shape_loads():
    path = Path("configs/examples/models.yaml")
    cfg = load_llm_config(path)
    assert cfg.main is not None
    assert cfg.main.provider == "local"
    assert cfg.main.base_url.endswith("/v1")
    assert cfg.auxiliary is not None
    assert cfg.fallback
    assert cfg.policy.default_mode == "local_only"
    assert cfg.is_configured() is True


def test_probe_models_hits_openai_compatible_endpoint():
    import threading

    import uvicorn

    fake = FastAPI()

    @fake.get("/v1/models")
    def models() -> dict[str, object]:
        return {"data": [{"id": "qwen2.5-coder:14b"}, {"id": "qwen2.5:7b"}]}

    server = uvicorn.Server(uvicorn.Config(fake, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(50):
            if server.started:
                break
            thread.join(0.05)
        assert server.started
        port = server.servers[0].sockets[0].getsockname()[1]
        ids = probe_models(f"http://127.0.0.1:{port}/v1")
        assert ids == ["qwen2.5-coder:14b", "qwen2.5:7b"]
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_openai_client_probe_failure_is_soft():
    slot = LlmSlotConfig(provider="local", base_url="http://127.0.0.1:9/v1", model="missing")
    result = OpenAICompatibleClient(slot, timeout=0.2).probe()
    assert result.ok is False
    assert result.error
    assert result.models == []


def test_assist_attribution_only_when_slot_used():
    empty = assist_attribution(None)
    assert empty["model_provider"] is None
    assert empty["model_id"] is None
    used = assist_attribution(LlmSlotConfig(provider="local", base_url="http://127.0.0.1:11434/v1", model="qwen2.5:7b"))
    assert used["model_provider"] == "local"
    assert used["model_id"] == "qwen2.5:7b"


def test_receipt_model_fields_default_none():
    receipt = Receipt(
        receipt_id="r1",
        ts="2026-09-15T00:00:00Z",
        principal="local",
        node_id="n",
        action="run_query",
        analytic_or_sql_hash="abc",
        engine_version="0",
        status="succeeded",
        prev_hash="0" * 64,
        receipt_hash="deadbeef",
    )
    assert receipt.model_provider is None
    assert receipt.model_id is None


def test_llm_client_reports_slots():
    cfg = load_llm_config(Path("configs/examples/models.yaml"))
    client = LlmClient(cfg)
    names = [name for name, _slot in client.slots()]
    assert names[0] == "main"
    assert "auxiliary" in names
    assert "fallback" in names

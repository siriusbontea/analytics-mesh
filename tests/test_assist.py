from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from mesh_common.llm import LlmClient, LlmProviderConfig, LlmSlotConfig
from mesh_node.app import create_app
from mesh_node.config import ConnectorConfig, LimitsConfig, NodeConfig
from mesh_node.runtime import NodeRuntime

REPO = Path(__file__).resolve().parents[1]


class _ChatRequest(BaseModel):
    model: str
    messages: list[dict[str, str]] = []


@contextmanager
def _openai_compat_server(
    *,
    sql: str = "SELECT product, SUM(amount) AS total FROM sales GROUP BY product",
    available_models: list[str] | None = None,
    missing_status: int | None = None,
    require_bearer: str | None = None,
) -> Iterator[str]:
    """Serve a tiny OpenAI-compatible /v1 on an ephemeral port."""
    listed = available_models or ["stub-sql"]
    fake = FastAPI()

    def _check_auth(authorization: str | None) -> None:
        if require_bearer is not None and authorization != f"Bearer {require_bearer}":
            raise HTTPException(status_code=401, detail="missing bearer")

    @fake.get("/v1/models")
    def models(authorization: str | None = Header(default=None)) -> dict[str, object]:
        _check_auth(authorization)
        return {"data": [{"id": item} for item in listed]}

    @fake.post("/v1/chat/completions")
    def chat(payload: _ChatRequest, authorization: str | None = Header(default=None)) -> dict[str, object]:
        _check_auth(authorization)
        if missing_status is not None and payload.model not in listed:
            raise HTTPException(status_code=missing_status, detail={"error": {"message": "model not found"}})
        return {
            "id": "chatcmpl-stub",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": sql}, "finish_reason": "stop"}],
        }

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
        yield f"http://127.0.0.1:{port}/v1"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _cfg(tmp_path: Path, data_dir: Path, models: LlmProviderConfig | None = None) -> NodeConfig:
    return NodeConfig(
        node_id="assist-node",
        artifact_dir=tmp_path / "artifacts",
        receipt_db=tmp_path / "receipts.sqlite",
        connectors=[ConnectorConfig(id="local_files", type="local_files", root=data_dir)],
        limits=LimitsConfig(default_row_limit=100, max_row_limit=1000, query_timeout_seconds=10),
        analytics_dir=REPO / "analytics",
        models=models or LlmProviderConfig(),
    )


def test_nl2sql_without_model_is_clear_error(tmp_path: Path, data_dir: Path):
    client = TestClient(create_app(_cfg(tmp_path, data_dir)))
    before = list((tmp_path / "artifacts").glob("*.parquet")) if (tmp_path / "artifacts").exists() else []
    response = client.post("/assist/nl2sql", json={"question": "which product sold the most?", "principal": "local"})
    assert response.status_code == 200
    body = response.json()
    assert body["used"] is False
    assert body["sql"] is None
    assert body.get("confirmed") is False
    assert "model" in body["message"].lower() or "configured" in body["message"].lower()
    after = list((tmp_path / "artifacts").glob("*.parquet")) if (tmp_path / "artifacts").exists() else []
    assert after == before


def test_nl2sql_proposes_sql_and_never_executes(tmp_path: Path, data_dir: Path, monkeypatch):
    models = LlmProviderConfig(
        main=LlmSlotConfig(provider="local", base_url="http://127.0.0.1:9/v1", model="unit-sql")
    )
    monkeypatch.setattr(
        LlmClient,
        "complete",
        lambda self, slot, messages, timeout=60.0: "SELECT product, SUM(amount) AS total FROM sales GROUP BY product",
    )
    client = TestClient(create_app(_cfg(tmp_path, data_dir, models)))
    response = client.post("/assist/nl2sql", json={"question": "totals by product", "principal": "local"})
    assert response.status_code == 200
    body = response.json()
    assert body["used"] is True
    assert body["confirmed"] is False
    assert "FROM sales" in body["sql"]
    assert body["model_provider"] == "local"
    assert body["model_id"] == "unit-sql"
    assert body["receipt"]["action"] == "assist_nl2sql"
    assert body["receipt"]["model_provider"] == "local"
    assert body["receipt"]["model_id"] == "unit-sql"
    assert list((tmp_path / "artifacts").glob("*.parquet")) == []


def test_confirmed_query_records_assist_model_on_receipt(tmp_path: Path, data_dir: Path, monkeypatch):
    models = LlmProviderConfig(
        main=LlmSlotConfig(provider="local", base_url="http://127.0.0.1:9/v1", model="unit-sql")
    )
    monkeypatch.setattr(LlmClient, "complete", lambda self, slot, messages, timeout=60.0: "SELECT * FROM sales")
    client = TestClient(create_app(_cfg(tmp_path, data_dir, models)))
    proposed = client.post("/assist/nl2sql", json={"question": "all sales", "principal": "local"}).json()
    ran = client.post(
        "/query",
        json={
            "sql": proposed["sql"],
            "principal": "local",
            "assist_model_provider": proposed["model_provider"],
            "assist_model_id": proposed["model_id"],
        },
    )
    assert ran.status_code == 200
    receipt = ran.json()["receipt"]
    assert receipt["action"] == "run_query"
    assert receipt["model_provider"] == "local"
    assert receipt["model_id"] == "unit-sql"
    assert ran.json()["artifact"]["row_count"] == 6


def test_local_only_policy_blocks_frontier_nl2sql(tmp_path: Path, data_dir: Path):
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        """
deny_unknown_principals: false
principals:
  local:
    allow_adhoc_sql: true
    allow_assist: true
    connectors: ["*"]
    analytics: ["*"]
    nodes: ["*"]
    model_mode: local_only
"""
    )
    models = LlmProviderConfig(
        main=LlmSlotConfig(provider="frontier", base_url="https://example.invalid/v1", model="frontier-sql")
    )
    cfg = _cfg(tmp_path, data_dir, models)
    cfg = cfg.model_copy(update={"policy_path": policy_path})
    client = TestClient(create_app(cfg))
    response = client.post("/assist/nl2sql", json={"question": "totals", "principal": "local"})
    assert response.status_code == 403


def test_explain_uses_auxiliary_when_configured(tmp_path: Path, data_dir: Path, monkeypatch):
    models = LlmProviderConfig(
        main=LlmSlotConfig(provider="local", base_url="http://127.0.0.1:9/v1", model="unit-sql"),
        auxiliary=LlmSlotConfig(provider="local", base_url="http://127.0.0.1:9/v1", model="unit-aux"),
    )

    def complete(self, slot, messages, timeout=60.0):
        return f"explained-by-{slot.model}"

    monkeypatch.setattr(LlmClient, "complete", complete)
    client = TestClient(create_app(_cfg(tmp_path, data_dir, models)))
    query = client.post("/query", json={"sql": "SELECT * FROM sales", "principal": "local"}).json()
    response = client.post(
        "/assist/explain",
        json={"artifact_id": query["artifact"]["artifact_id"], "principal": "local"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["used"] is True
    assert body["model_id"] == "unit-aux"
    assert "explained-by-unit-aux" in body["explanation"]
    assert body["receipt"]["model_id"] == "unit-aux"


def test_runtime_nl2sql_does_not_call_engine(tmp_path: Path, data_dir: Path, monkeypatch):
    models = LlmProviderConfig(
        main=LlmSlotConfig(provider="local", base_url="http://127.0.0.1:9/v1", model="unit-sql")
    )
    monkeypatch.setattr(LlmClient, "complete", lambda self, slot, messages, timeout=60.0: "SELECT 1 AS n")
    runtime = NodeRuntime(_cfg(tmp_path, data_dir, models))
    called = {"n": 0}
    original = runtime.engine.execute

    def wrapped(*args, **kwargs):
        called["n"] += 1
        return original(*args, **kwargs)

    runtime.engine.execute = wrapped  # type: ignore[method-assign]
    result = runtime.propose_sql("count rows", "local")
    assert result["sql"]
    assert called["n"] == 0


def test_nl2sql_with_openai_compat_stub_proposes_and_never_executes(tmp_path: Path, data_dir: Path):
    with _openai_compat_server(sql="SELECT product FROM sales") as base_url:
        models = LlmProviderConfig(main=LlmSlotConfig(provider="local", base_url=base_url, model="stub-sql"))
        client = TestClient(create_app(_cfg(tmp_path, data_dir, models)))
        before = list((tmp_path / "artifacts").glob("*.parquet")) if (tmp_path / "artifacts").exists() else []
        response = client.post("/assist/nl2sql", json={"question": "list products", "principal": "local"})
        assert response.status_code == 200
        body = response.json()
        assert body["used"] is True
        assert body["confirmed"] is False
        assert "FROM sales" in body["sql"]
        assert body["model_provider"] == "local"
        assert body["model_id"] == "stub-sql"
        assert body["model_slot"] == "main"
        assert body["model_fallback_used"] is False
        assert body["receipt"]["action"] == "assist_nl2sql"
        assert body["receipt"]["model_provider"] == "local"
        assert body["receipt"]["model_id"] == "stub-sql"
        after = list((tmp_path / "artifacts").glob("*.parquet")) if (tmp_path / "artifacts").exists() else []
        assert after == before


def test_nl2sql_unreachable_local_endpoint_is_clear(tmp_path: Path, data_dir: Path):
    models = LlmProviderConfig(
        main=LlmSlotConfig(provider="local", base_url="http://127.0.0.1:9/v1", model="any-local")
    )
    client = TestClient(create_app(_cfg(tmp_path, data_dir, models)))
    body = client.post("/assist/nl2sql", json={"question": "totals", "principal": "local"}).json()
    assert body["used"] is False
    assert body["sql"] is None
    message = body["message"].lower()
    assert "unreachable" in message
    assert "ollama" in message or "lm studio" in message
    assert "/models" in body["message"]
    assert body["receipt"]["status"] == "failed"
    assert body["receipt"]["model_attempts"][0]["status"] == "failed"


def test_nl2sql_missing_model_is_clear(tmp_path: Path, data_dir: Path):
    with _openai_compat_server(available_models=["other-tag"], missing_status=404) as base_url:
        models = LlmProviderConfig(
            main=LlmSlotConfig(provider="local", base_url=base_url, model="missing-tag")
        )
        client = TestClient(create_app(_cfg(tmp_path, data_dir, models)))
        body = client.post("/assist/nl2sql", json={"question": "totals", "principal": "local"}).json()
        assert body["used"] is False
        assert body["sql"] is None
        message = body["message"].lower()
        assert "not found" in message
        assert "missing-tag" in message
        assert "pull" in message or "model:" in message

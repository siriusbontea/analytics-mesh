from __future__ import annotations

from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from mesh_common.llm import LlmClient, LlmProviderConfig, LlmSlotConfig
from mesh_node.app import create_app
from mesh_node.config import ConnectorConfig, LimitsConfig, NodeConfig

REPO = Path(__file__).resolve().parents[1]


def _cfg(tmp_path: Path, data_dir: Path, models: LlmProviderConfig) -> NodeConfig:
    return NodeConfig(
        node_id="fallback-node",
        artifact_dir=tmp_path / "artifacts",
        receipt_db=tmp_path / "receipts.sqlite",
        connectors=[ConnectorConfig(id="local_files", type="local_files", root=data_dir)],
        limits=LimitsConfig(default_row_limit=100, max_row_limit=1000, query_timeout_seconds=10),
        analytics_dir=REPO / "analytics",
        models=models,
    )


def test_candidate_slots_try_main_then_fallbacks_in_config_order():
    cfg = LlmProviderConfig(
        main=LlmSlotConfig(provider="frontier", base_url="https://example.invalid/v1", model="main-model"),
        auxiliary=LlmSlotConfig(provider="local", base_url="http://127.0.0.1:9/v1", model="aux-model"),
        fallback=[
            LlmSlotConfig(provider="local", base_url="http://127.0.0.1:9/v1", model="fb-1"),
            LlmSlotConfig(provider="frontier", base_url="https://example.invalid/v1", model="fb-2"),
        ],
    )
    client = LlmClient(cfg)
    main_chain = client.candidate_slots("main", allow_frontier=True)
    assert [(name, slot.model) for name, slot in main_chain] == [
        ("main", "main-model"),
        ("fallback", "fb-1"),
        ("fallback[1]", "fb-2"),
    ]
    aux_chain = client.candidate_slots("auxiliary", allow_frontier=True)
    assert [(name, slot.model) for name, slot in aux_chain] == [
        ("auxiliary", "aux-model"),
        ("fallback", "fb-1"),
        ("fallback[1]", "fb-2"),
    ]
    local_only = client.candidate_slots("main", allow_frontier=False)
    assert [(name, slot.model) for name, slot in local_only] == [("fallback", "fb-1")]


def test_nl2sql_falls_back_and_receipt_records_served_model(tmp_path: Path, data_dir: Path, monkeypatch):
    models = LlmProviderConfig(
        main=LlmSlotConfig(provider="local", base_url="http://127.0.0.1:9/v1", model="main-down"),
        fallback=[LlmSlotConfig(provider="local", base_url="http://127.0.0.1:9/v1", model="fb-up")],
    )

    def complete(self, slot, messages, timeout=60.0):
        if slot.model == "main-down":
            raise httpx.ConnectError("main unavailable")
        return "SELECT product FROM sales"

    monkeypatch.setattr(LlmClient, "complete", complete)
    client = TestClient(create_app(_cfg(tmp_path, data_dir, models)))
    response = client.post("/assist/nl2sql", json={"question": "list products", "principal": "local"})
    assert response.status_code == 200
    body = response.json()
    assert body["used"] is True
    assert body["model_provider"] == "local"
    assert body["model_id"] == "fb-up"
    assert body["model_slot"] == "fallback"
    assert body["model_fallback_used"] is True
    receipt = body["receipt"]
    assert receipt["model_provider"] == "local"
    assert receipt["model_id"] == "fb-up"
    assert receipt["model_slot"] == "fallback"
    assert receipt["model_fallback_used"] is True
    attempts = receipt["model_attempts"]
    assert [item["model"] for item in attempts] == ["main-down", "fb-up"]
    assert attempts[0]["slot"] == "main"
    assert attempts[0]["status"] == "failed"
    assert attempts[1]["slot"] == "fallback"
    assert attempts[1]["status"] == "succeeded"
    fetched = client.get(f"/receipts/{receipt['receipt_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["model_id"] == "fb-up"
    assert fetched.json()["model_slot"] == "fallback"


def test_nl2sql_main_success_does_not_mark_fallback(tmp_path: Path, data_dir: Path, monkeypatch):
    models = LlmProviderConfig(
        main=LlmSlotConfig(provider="local", base_url="http://127.0.0.1:9/v1", model="main-up"),
        fallback=[LlmSlotConfig(provider="local", base_url="http://127.0.0.1:9/v1", model="fb-unused")],
    )
    monkeypatch.setattr(LlmClient, "complete", lambda self, slot, messages, timeout=60.0: "SELECT 1 AS n")
    client = TestClient(create_app(_cfg(tmp_path, data_dir, models)))
    body = client.post("/assist/nl2sql", json={"question": "count", "principal": "local"}).json()
    assert body["model_id"] == "main-up"
    assert body["model_slot"] == "main"
    assert body["model_fallback_used"] is False
    assert body["receipt"]["model_attempts"] == [
        {"slot": "main", "provider": "local", "model": "main-up", "status": "succeeded", "error": None}
    ]


def test_explain_falls_back_from_auxiliary(tmp_path: Path, data_dir: Path, monkeypatch):
    models = LlmProviderConfig(
        main=LlmSlotConfig(provider="local", base_url="http://127.0.0.1:9/v1", model="main-sql"),
        auxiliary=LlmSlotConfig(provider="local", base_url="http://127.0.0.1:9/v1", model="aux-down"),
        fallback=[LlmSlotConfig(provider="local", base_url="http://127.0.0.1:9/v1", model="fb-explain")],
    )

    def complete(self, slot, messages, timeout=60.0):
        if slot.model == "aux-down":
            raise httpx.ReadTimeout("aux timeout")
        return f"explained-by-{slot.model}"

    monkeypatch.setattr(LlmClient, "complete", complete)
    client = TestClient(create_app(_cfg(tmp_path, data_dir, models)))
    query = client.post("/query", json={"sql": "SELECT * FROM sales", "principal": "local"}).json()
    body = client.post(
        "/assist/explain",
        json={"artifact_id": query["artifact"]["artifact_id"], "principal": "local"},
    ).json()
    assert body["used"] is True
    assert body["model_id"] == "fb-explain"
    assert body["model_slot"] == "fallback"
    assert body["model_fallback_used"] is True
    assert body["receipt"]["model_id"] == "fb-explain"
    assert [item["model"] for item in body["receipt"]["model_attempts"]] == ["aux-down", "fb-explain"]

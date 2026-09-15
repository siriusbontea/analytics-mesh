from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from mesh_common.llm import LlmClient, LlmProviderConfig, LlmSlotConfig
from mesh_node.app import create_app
from mesh_node.config import ConnectorConfig, LimitsConfig, NodeConfig
from mesh_node.runtime import NodeRuntime

REPO = Path(__file__).resolve().parents[1]


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

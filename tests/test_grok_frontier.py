from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi.testclient import TestClient

from mesh_common.llm import LlmClient, LlmPolicyConfig, LlmProviderConfig, LlmSlotConfig, load_llm_config
from mesh_node.app import create_app
from mesh_node.config import ConnectorConfig, LimitsConfig, NodeConfig, load_config
from test_assist import _openai_compat_server

REPO = Path(__file__).resolve().parents[1]


def _cfg(
    tmp_path: Path,
    data_dir: Path,
    models: LlmProviderConfig,
    *,
    policy_path: Path | None = None,
) -> NodeConfig:
    return NodeConfig(
        node_id="grok-node",
        artifact_dir=tmp_path / "artifacts",
        receipt_db=tmp_path / "receipts.sqlite",
        connectors=[ConnectorConfig(id="local_files", type="local_files", root=data_dir)],
        limits=LimitsConfig(default_row_limit=100, max_row_limit=1000, query_timeout_seconds=10),
        analytics_dir=REPO / "analytics",
        models=models,
        policy_path=policy_path,
    )


def _local_only_policy(tmp_path: Path) -> Path:
    path = tmp_path / "policy.yaml"
    path.write_text(
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
    return path


def _frontier_grok(
    base_url: str, *, default_mode: Literal["local_only", "allow_frontier"]
) -> LlmProviderConfig:
    slot = LlmSlotConfig(
        provider="frontier",
        base_url=base_url,
        model="grok-4",
        api_key_env="XAI_API_KEY",
    )
    return LlmProviderConfig(
        main=slot,
        auxiliary=slot,
        policy=LlmPolicyConfig(default_mode=default_mode),
    )


def test_models_yaml_allows_frontier_when_default_mode_is_allow_frontier():
    local = LlmProviderConfig(policy=LlmPolicyConfig(default_mode="local_only"))
    assert local.allows_frontier("local_only") is False
    assert local.allows_frontier("allow_frontier") is True
    grok = LlmProviderConfig(policy=LlmPolicyConfig(default_mode="allow_frontier"))
    assert grok.allows_frontier("local_only") is True
    assert grok.allows_frontier("allow_frontier") is True


def test_nl2sql_allow_frontier_grok_main_is_used(tmp_path: Path, data_dir: Path, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-xai-key")
    with _openai_compat_server(
        sql="SELECT product FROM sales",
        available_models=["grok-4"],
        require_bearer="test-xai-key",
    ) as base_url:
        models = _frontier_grok(base_url, default_mode="allow_frontier")
        client = TestClient(create_app(_cfg(tmp_path, data_dir, models, policy_path=_local_only_policy(tmp_path))))
        before = list((tmp_path / "artifacts").glob("*.parquet")) if (tmp_path / "artifacts").exists() else []
        response = client.post("/assist/nl2sql", json={"question": "list products", "principal": "local"})
        assert response.status_code == 200
        body = response.json()
        assert body["used"] is True
        assert body["confirmed"] is False
        assert "FROM sales" in body["sql"]
        assert body["model_provider"] == "frontier"
        assert body["model_id"] == "grok-4"
        assert body["model_slot"] == "main"
        assert body["model_fallback_used"] is False
        after = list((tmp_path / "artifacts").glob("*.parquet")) if (tmp_path / "artifacts").exists() else []
        assert after == before


def test_nl2sql_local_only_strips_frontier_grok(tmp_path: Path, data_dir: Path):
    with _openai_compat_server(sql="SELECT 1 AS leaked", available_models=["grok-4"]) as base_url:
        models = _frontier_grok(base_url, default_mode="local_only")
        client = TestClient(create_app(_cfg(tmp_path, data_dir, models, policy_path=_local_only_policy(tmp_path))))
        response = client.post("/assist/nl2sql", json={"question": "list products", "principal": "local"})
        assert response.status_code == 403
        detail = response.json()["detail"]
        reason = str(detail.get("message") or detail).lower()
        assert "local_only" in reason or "local model" in reason or "frontier" in reason
        assert "leaked" not in str(detail).lower()


def test_nl2sql_local_then_frontier_prefers_local(tmp_path: Path, data_dir: Path, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-xai-key")
    with (
        _openai_compat_server(sql="SELECT product FROM sales", available_models=["local-sql"]) as local_url,
        _openai_compat_server(sql="SELECT 'frontier' AS leaked", available_models=["grok-4"]) as grok_url,
    ):
        models = LlmProviderConfig(
            main=LlmSlotConfig(provider="local", base_url=local_url, model="local-sql"),
            auxiliary=LlmSlotConfig(provider="local", base_url=local_url, model="local-sql"),
            fallback=[
                LlmSlotConfig(
                    provider="frontier",
                    base_url=grok_url,
                    model="grok-4",
                    api_key_env="XAI_API_KEY",
                )
            ],
            policy=LlmPolicyConfig(default_mode="allow_frontier"),
        )
        client = TestClient(create_app(_cfg(tmp_path, data_dir, models, policy_path=_local_only_policy(tmp_path))))
        response = client.post("/assist/nl2sql", json={"question": "list products", "principal": "local"})
        assert response.status_code == 200
        body = response.json()
        assert body["used"] is True
        assert body["model_provider"] == "local"
        assert body["model_id"] == "local-sql"
        assert body["model_slot"] == "main"
        assert body["model_fallback_used"] is False
        assert "leaked" not in body["sql"]


def test_nl2sql_local_then_frontier_falls_back_to_grok(tmp_path: Path, data_dir: Path, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-xai-key")
    with _openai_compat_server(
        sql="SELECT product FROM sales",
        available_models=["grok-4"],
        require_bearer="test-xai-key",
    ) as grok_url:
        models = LlmProviderConfig(
            main=LlmSlotConfig(provider="local", base_url="http://127.0.0.1:9/v1", model="missing-local"),
            fallback=[
                LlmSlotConfig(
                    provider="frontier",
                    base_url=grok_url,
                    model="grok-4",
                    api_key_env="XAI_API_KEY",
                )
            ],
            policy=LlmPolicyConfig(default_mode="allow_frontier"),
        )
        client = TestClient(create_app(_cfg(tmp_path, data_dir, models, policy_path=_local_only_policy(tmp_path))))
        response = client.post("/assist/nl2sql", json={"question": "list products", "principal": "local"})
        assert response.status_code == 200
        body = response.json()
        assert body["used"] is True
        assert body["model_provider"] == "frontier"
        assert body["model_id"] == "grok-4"
        assert body["model_slot"] == "fallback"
        assert body["model_fallback_used"] is True
        attempts = body["receipt"]["model_attempts"]
        assert [item["model"] for item in attempts] == ["missing-local", "grok-4"]
        assert attempts[0]["status"] == "failed"
        assert attempts[1]["status"] == "succeeded"


def test_nl2sql_missing_xai_key_is_clear(tmp_path: Path, data_dir: Path, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    with _openai_compat_server(sql="SELECT 1", available_models=["grok-4"], require_bearer="unused") as base_url:
        models = _frontier_grok(base_url, default_mode="allow_frontier")
        client = TestClient(create_app(_cfg(tmp_path, data_dir, models, policy_path=_local_only_policy(tmp_path))))
        response = client.post("/assist/nl2sql", json={"question": "list products", "principal": "local"})
        assert response.status_code == 200
        body = response.json()
        assert body["used"] is False
        assert "XAI_API_KEY" in body["message"]


def test_nl2sql_allow_assist_false_still_denied(tmp_path: Path, data_dir: Path, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-xai-key")
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        """
deny_unknown_principals: false
principals:
  viewer:
    allow_adhoc_sql: true
    allow_assist: false
    connectors: ["*"]
    analytics: ["*"]
    nodes: ["*"]
    model_mode: local_only
"""
    )
    with _openai_compat_server(sql="SELECT product FROM sales", available_models=["grok-4"]) as base_url:
        models = _frontier_grok(base_url, default_mode="allow_frontier")
        client = TestClient(create_app(_cfg(tmp_path, data_dir, models, policy_path=policy_path)))
        denied = client.post("/assist/nl2sql", json={"question": "list products", "principal": "viewer"})
        assert denied.status_code == 403
        ran = client.post(
            "/query",
            json={
                "sql": "SELECT product FROM sales",
                "principal": "viewer",
                "assist_model_provider": "frontier",
                "assist_model_id": "grok-4",
            },
        )
        assert ran.status_code == 200
        assert ran.json()["receipt"]["model_provider"] is None
        assert ran.json()["receipt"]["model_id"] is None


def test_explain_allow_frontier_uses_grok_auxiliary(tmp_path: Path, data_dir: Path, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-xai-key")
    with _openai_compat_server(
        sql="Grok explained the preview.",
        available_models=["grok-4"],
        require_bearer="test-xai-key",
    ) as base_url:
        models = _frontier_grok(base_url, default_mode="allow_frontier")
        client = TestClient(create_app(_cfg(tmp_path, data_dir, models, policy_path=_local_only_policy(tmp_path))))
        query = client.post("/query", json={"sql": "SELECT * FROM sales", "principal": "local"}).json()
        response = client.post(
            "/assist/explain",
            json={"artifact_id": query["artifact"]["artifact_id"], "principal": "local"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["used"] is True
        assert body["model_provider"] == "frontier"
        assert body["model_id"] == "grok-4"
        assert "Grok explained" in body["explanation"]


def test_candidate_slots_local_then_grok_order():
    cfg = LlmProviderConfig(
        main=LlmSlotConfig(provider="local", base_url="http://127.0.0.1:11434/v1", model="qwen2.5-coder:14b"),
        fallback=[
            LlmSlotConfig(
                provider="frontier",
                base_url="https://api.x.ai/v1",
                model="grok-4",
                api_key_env="XAI_API_KEY",
            )
        ],
        policy=LlmPolicyConfig(default_mode="allow_frontier"),
    )
    client = LlmClient(cfg)
    allowed = [(name, slot.provider, slot.model) for name, slot in client.candidate_slots("main", allow_frontier=True)]
    assert allowed == [("main", "local", "qwen2.5-coder:14b"), ("fallback", "frontier", "grok-4")]
    stripped = client.candidate_slots("main", allow_frontier=False)
    assert [(name, slot.provider) for name, slot in stripped] == [("main", "local")]


def test_example_grok_configs_load_and_stay_optional():
    grok_models = load_llm_config(REPO / "configs/examples/models-with-grok.yaml")
    assert grok_models.main is not None
    assert grok_models.main.provider == "frontier"
    assert grok_models.main.base_url == "https://api.x.ai/v1"
    assert grok_models.main.api_key_env == "XAI_API_KEY"
    assert grok_models.main.model.startswith("grok-")
    assert grok_models.auxiliary is not None
    assert grok_models.auxiliary.provider == "frontier"
    assert grok_models.policy.default_mode == "allow_frontier"

    grok_node = load_config(REPO / "configs/examples/node-with-grok.yaml")
    assert grok_node.models_path is not None
    assert grok_node.models_path.name == "models-with-grok.yaml"
    assert grok_node.models.policy.default_mode == "allow_frontier"
    assert grok_node.models.main is not None
    assert grok_node.models.main.provider == "frontier"

    local_then = load_llm_config(REPO / "configs/examples/models-local-then-grok.yaml")
    assert local_then.main is not None
    assert local_then.main.provider == "local"
    assert local_then.auxiliary is not None
    assert local_then.auxiliary.provider == "local"
    assert local_then.fallback
    assert local_then.fallback[0].provider == "frontier"
    assert local_then.fallback[0].base_url == "https://api.x.ai/v1"
    assert local_then.fallback[0].api_key_env == "XAI_API_KEY"
    assert local_then.policy.default_mode == "allow_frontier"

    local_then_node = load_config(REPO / "configs/examples/node-with-local-then-grok.yaml")
    assert local_then_node.models_path is not None
    assert local_then_node.models_path.name == "models-local-then-grok.yaml"
    assert local_then_node.models.policy.default_mode == "allow_frontier"

    default_node = load_config(REPO / "configs/examples/node.yaml")
    assert default_node.models.is_configured() is False
    local_only = load_config(REPO / "configs/examples/node-with-models.yaml")
    assert local_only.models.policy.default_mode == "local_only"
    assert local_only.models.main is not None
    assert local_only.models.main.provider == "local"

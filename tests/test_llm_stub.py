from __future__ import annotations

from pathlib import Path

from mesh_common.llm import LlmProviderConfig, load_llm_config


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

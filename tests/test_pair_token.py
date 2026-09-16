from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mesh_common.identity import canonical_registration_payload, generate_keypair
from mesh_common.secrets import DEFAULT_PAIR_TOKEN_ENV, resolve_pair_token
from mesh_node.config import PlaneClientConfig, load_config as load_node_config
from mesh_plane.app import create_app as create_plane_app
from mesh_plane.config import PlaneConfig, load_config as load_plane_config

REPO = Path(__file__).resolve().parents[1]


def _registration(keys, endpoint: str, token: str) -> dict:
    signed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    payload = canonical_registration_payload(
        node_id=keys.node_id,
        endpoint=endpoint,
        public_key=keys.public_key_hex,
        signed_at=signed_at,
    )
    return {
        "node_id": keys.node_id,
        "endpoint": endpoint,
        "public_key": keys.public_key_hex,
        "labels": [],
        "token": token,
        "signed_at": signed_at,
        "signature": keys.sign(payload),
    }


def test_resolve_pair_token_uses_yaml_when_env_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(DEFAULT_PAIR_TOKEN_ENV, raising=False)
    assert resolve_pair_token("demo-pair-token") == "demo-pair-token"


def test_resolve_pair_token_mesh_env_overrides_yaml(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(DEFAULT_PAIR_TOKEN_ENV, "from-env")
    assert resolve_pair_token("demo-pair-token") == "from-env"


def test_resolve_pair_token_named_env_is_required(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CUSTOM_PAIR", raising=False)
    monkeypatch.setenv(DEFAULT_PAIR_TOKEN_ENV, "should-not-win")
    with pytest.raises(ValueError, match="CUSTOM_PAIR"):
        resolve_pair_token("demo-pair-token", pair_token_env="CUSTOM_PAIR")


def test_resolve_pair_token_named_env_overrides_yaml(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CUSTOM_PAIR", "from-custom")
    assert resolve_pair_token("demo-pair-token", pair_token_env="CUSTOM_PAIR") == "from-custom"


def test_resolve_pair_token_cli_override_wins(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(DEFAULT_PAIR_TOKEN_ENV, "from-env")
    assert resolve_pair_token("demo-pair-token", override="from-cli") == "from-cli"


def test_plane_register_accepts_env_token_not_yaml_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(DEFAULT_PAIR_TOKEN_ENV, "secret-from-env")
    cfg = PlaneConfig(
        plane_id="env-plane",
        registration_token="demo-pair-token",
        store_path=tmp_path / "plane.sqlite",
    )
    client = TestClient(create_plane_app(cfg))
    keys = generate_keypair("node-env")
    rejected = client.post(
        "/nodes/register",
        json=_registration(keys, "http://127.0.0.1:8081", "demo-pair-token"),
    )
    accepted = client.post(
        "/nodes/register",
        json=_registration(keys, "http://127.0.0.1:8081", "secret-from-env"),
    )
    assert rejected.status_code == 403
    assert accepted.status_code == 200


def test_plane_pair_token_env_hook_reads_named_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MESH_BOX_PAIR", "box-secret")
    cfg = PlaneConfig(
        plane_id="hook-plane",
        registration_token="demo-pair-token",
        pair_token_env="MESH_BOX_PAIR",
        store_path=tmp_path / "plane.sqlite",
    )
    assert cfg.resolved_registration_token() == "box-secret"
    client = TestClient(create_plane_app(cfg))
    keys = generate_keypair("node-hook")
    response = client.post(
        "/nodes/register",
        json=_registration(keys, "http://127.0.0.1:8082", "box-secret"),
    )
    assert response.status_code == 200


def test_node_plane_client_resolved_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(DEFAULT_PAIR_TOKEN_ENV, "node-env-token")
    plane = PlaneClientConfig(url="http://127.0.0.1:8090", token="demo-pair-token")
    assert plane.resolved_token() == "node-env-token"


def test_example_plane_keeps_demo_token_and_localhost():
    plane = load_plane_config(REPO / "configs/examples/plane.yaml")
    assert plane.registration_token == "demo-pair-token"
    assert plane.pair_token_env is None
    assert plane.listen_host == "127.0.0.1"


def test_example_nodes_keep_demo_token_and_localhost():
    for name in ("node-a.yaml", "node-b.yaml"):
        node = load_node_config(REPO / "configs/examples" / name)
        assert node.listen_host == "127.0.0.1"
        assert node.plane is not None
        assert node.plane.token == "demo-pair-token"
        assert node.plane.pair_token_env is None
        assert node.plane.public_endpoint and "127.0.0.1" in node.plane.public_endpoint

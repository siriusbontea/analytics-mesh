from __future__ import annotations

from pathlib import Path

from mesh_common.policy import load_policy
from mesh_node.config import load_config
from mesh_plane.config import load_config as load_plane_config

REPO = Path(__file__).resolve().parents[1]


def test_example_node_configs_point_at_separate_data():
    node_a = load_config(REPO / "configs/examples/node-a.yaml")
    node_b = load_config(REPO / "configs/examples/node-b.yaml")
    assert node_a.node_id == "node-a"
    assert node_b.node_id == "node-b"
    assert node_a.listen_port != node_b.listen_port
    assert node_a.connectors[0].root != node_b.connectors[0].root
    assert (REPO / "data/samples/node-b/sales.csv").is_file()
    assert "babylon-sprocket" in (REPO / "data/samples/node-b/sales.csv").read_text()
    assert node_a.identity_key_path != node_b.identity_key_path
    assert node_a.plane is not None and node_b.plane is not None
    assert node_a.analytics_dir == node_b.analytics_dir
    assert (REPO / "analytics/examples/top_products.yaml").is_file()
    assert node_a.policy_path == node_b.policy_path
    assert node_a.policy_path is not None
    assert node_a.policy_path.name == "policy.yaml"


def test_example_policy_and_postgres_config_load():
    policy = load_policy(REPO / "configs/examples/policy.yaml")
    assert policy.authorize(principal="local", action="run_query", node_id="local-dev").allowed is True
    node = load_config(REPO / "configs/examples/node-postgres.yaml")
    types = [item.type for item in node.connectors]
    assert "postgres" in types
    pg = next(item for item in node.connectors if item.type == "postgres")
    assert pg.dsn_env == "MESH_POSTGRES_DSN"
    assert node.artifacts.max_files == 200


def test_example_plane_config_loads():
    plane = load_plane_config(REPO / "configs/examples/plane.yaml")
    assert plane.plane_id == "home-plane"
    assert plane.registration_token == "demo-pair-token"
    assert plane.pair_token_env is None
    assert plane.listen_host == "127.0.0.1"
    assert plane.listen_port == 8090
    text = (REPO / "configs/examples/plane.yaml").read_text()
    assert "localhost-only" in text or "localhost only" in text
    assert "MESH_PAIR_TOKEN" in text
    assert "0.0.0.0" in text


def test_real_data_example_is_not_secret_bearing():
    path = REPO / "configs/examples/node-real-data.yaml.example"
    node = load_config(path)
    assert node.listen_host == "127.0.0.1"
    assert node.connectors[0].type == "local_files"
    assert node.connectors[0].root == Path("/var/lib/analytics-mesh/data")
    assert "personal" in node.connectors[0].labels
    assert node.plane is None
    text = path.read_text()
    assert "demo-pair-token" not in text
    assert "MESH_PAIR_TOKEN" in text
    assert "0.0.0.0" in text


def test_systemd_units_match_shipped_entrypoints():
    units = {
        "mesh-node.service": "mesh-node",
        "mesh-plane.service": "mesh-plane",
        "mesh-mcp.service": "mesh-mcp",
    }
    for name, script in units.items():
        text = (REPO / "deploy/systemd" / name).read_text()
        assert f"ExecStart=" in text
        assert script in text
        assert "User=mesh" in text
        assert "WorkingDirectory=/opt/analytics-mesh" in text
        assert "EnvironmentFile=-/etc/analytics-mesh/mesh.env" in text
        assert "127.0.0.1" in text
    env = (REPO / "deploy/systemd/mesh.env.example").read_text()
    assert "MESH_PAIR_TOKEN=" in env
    assert "XAI_API_KEY=" in env
    assert "0.0.0.0" in env


def test_env_examples_document_xai_api_key():
    assert "XAI_API_KEY=" in (REPO / ".env.example").read_text()
    assert "XAI_API_KEY=" in (REPO / "deploy/systemd/mesh.env.example").read_text()


def test_default_example_node_is_llm_free():
    node = load_config(REPO / "configs/examples/node.yaml")
    assert node.models_path is None
    assert node.models.main is None
    assert node.models.is_configured() is False
    assert node.uploads.max_bytes == 104857600
    text = (REPO / "configs/examples/node.yaml").read_text()
    assert "models_path:" in text
    assert text.split("models_path:")[0].rstrip().endswith("#") or "# models_path:" in text


def test_node_with_models_points_at_example_models():
    node = load_config(REPO / "configs/examples/node-with-models.yaml")
    assert node.models_path is not None
    assert node.models_path.name == "models.yaml"
    assert node.models.is_configured() is True
    assert node.models.main is not None
    assert node.models.main.provider == "local"
    assert node.models.main.base_url.endswith("/v1")
    assert node.models.policy.default_mode == "local_only"

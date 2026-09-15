from __future__ import annotations

from pathlib import Path

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


def test_example_plane_config_loads():
    plane = load_plane_config(REPO / "configs/examples/plane.yaml")
    assert plane.plane_id == "home-plane"
    assert plane.registration_token
    assert plane.listen_port == 8090

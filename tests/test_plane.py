from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi.testclient import TestClient

from mesh_common.identity import (
    canonical_registration_payload,
    generate_keypair,
    load_or_create_keypair,
)
from mesh_common.receipts import ReceiptStore
from mesh_node.app import create_app as create_node_app
from mesh_node.config import ConnectorConfig, LimitsConfig, NodeConfig
from mesh_plane.app import create_app as create_plane_app
from mesh_plane.config import PlaneConfig


def _registration(keys, endpoint: str, token: str, labels: list[str] | None = None) -> dict:
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
        "labels": labels or [],
        "token": token,
        "signed_at": signed_at,
        "signature": keys.sign(payload),
    }


def _plane_config(tmp_path: Path, token: str = "demo-pair-token") -> PlaneConfig:
    return PlaneConfig(
        plane_id="test-plane",
        registration_token=token,
        store_path=tmp_path / "plane.sqlite",
        listen_host="127.0.0.1",
        listen_port=8090,
    )


def test_register_two_nodes_and_list(tmp_path: Path):
    client = TestClient(create_plane_app(_plane_config(tmp_path)))
    node_a = generate_keypair("node-a")
    node_b = generate_keypair("node-b")

    first = client.post("/nodes/register", json=_registration(node_a, "http://127.0.0.1:8081", "demo-pair-token"))
    second = client.post("/nodes/register", json=_registration(node_b, "http://127.0.0.1:8082", "demo-pair-token"))
    assert first.status_code == 200
    assert second.status_code == 200

    listed = client.get("/nodes")
    assert listed.status_code == 200
    nodes = listed.json()["nodes"]
    assert {item["node_id"] for item in nodes} == {"node-a", "node-b"}
    assert {item["endpoint"] for item in nodes} == {"http://127.0.0.1:8081", "http://127.0.0.1:8082"}
    assert all(item["public_key"] for item in nodes)


def test_register_rejects_bad_token(tmp_path: Path):
    client = TestClient(create_plane_app(_plane_config(tmp_path)))
    keys = generate_keypair("node-b")
    response = client.post("/nodes/register", json=_registration(keys, "http://127.0.0.1:8082", "wrong-token"))
    assert response.status_code == 403


def test_register_rejects_bad_signature(tmp_path: Path):
    client = TestClient(create_plane_app(_plane_config(tmp_path)))
    keys = generate_keypair("node-b")
    body = _registration(keys, "http://127.0.0.1:8082", "demo-pair-token")
    body["signature"] = "00" * 64
    response = client.post("/nodes/register", json=body)
    assert response.status_code == 403


def test_query_routes_to_node_b_artifact_stays_on_b(tmp_path: Path, sales_csv_text: str):
    unique_product = "babylon-sprocket"
    node_a_data = tmp_path / "data-a"
    node_b_data = tmp_path / "data-b"
    node_a_data.mkdir()
    node_b_data.mkdir()
    (node_a_data / "sales.csv").write_text(sales_csv_text)
    (node_b_data / "sales.csv").write_text(
        "order_id,product,region,amount,sold_on\n"
        f"1,{unique_product},west,99.0,2026-02-01\n"
        "2,epsilon-widget,east,11.0,2026-02-02\n"
    )

    node_a_cfg = NodeConfig(
        node_id="node-a",
        artifact_dir=tmp_path / "artifacts-a",
        receipt_db=tmp_path / "receipts-a.sqlite",
        identity_key_path=tmp_path / "node-a.ed25519",
        connectors=[ConnectorConfig(id="local_files", type="local_files", root=node_a_data)],
        limits=LimitsConfig(default_row_limit=100, max_row_limit=1000, query_timeout_seconds=10),
        listen_host="127.0.0.1",
        listen_port=0,
    )
    node_b_cfg = NodeConfig(
        node_id="node-b",
        artifact_dir=tmp_path / "artifacts-b",
        receipt_db=tmp_path / "receipts-b.sqlite",
        identity_key_path=tmp_path / "node-b.ed25519",
        connectors=[ConnectorConfig(id="local_files", type="local_files", root=node_b_data)],
        limits=LimitsConfig(default_row_limit=100, max_row_limit=1000, query_timeout_seconds=10),
        listen_host="127.0.0.1",
        listen_port=0,
    )

    server_a = uvicorn.Server(uvicorn.Config(create_node_app(node_a_cfg), host="127.0.0.1", port=0, log_level="error"))
    server_b = uvicorn.Server(uvicorn.Config(create_node_app(node_b_cfg), host="127.0.0.1", port=0, log_level="error"))
    threads = [threading.Thread(target=server_a.run, daemon=True), threading.Thread(target=server_b.run, daemon=True)]
    for thread in threads:
        thread.start()
    try:
        for server in (server_a, server_b):
            for _ in range(50):
                if server.started:
                    break
                threads[0].join(0.05)
            assert server.started

        endpoint_a = f"http://127.0.0.1:{server_a.servers[0].sockets[0].getsockname()[1]}"
        endpoint_b = f"http://127.0.0.1:{server_b.servers[0].sockets[0].getsockname()[1]}"

        plane_cfg = _plane_config(tmp_path)
        plane = TestClient(create_plane_app(plane_cfg))
        keys_a = load_or_create_keypair(node_a_cfg.identity_key_path, "node-a")
        keys_b = load_or_create_keypair(node_b_cfg.identity_key_path, "node-b")
        assert plane.post("/nodes/register", json=_registration(keys_a, endpoint_a, "demo-pair-token")).status_code == 200
        assert plane.post("/nodes/register", json=_registration(keys_b, endpoint_b, "demo-pair-token")).status_code == 200

        sql = "SELECT product, SUM(amount) AS total FROM sales GROUP BY product ORDER BY total DESC"
        response = plane.post("/query", json={"node_id": "node-b", "sql": sql, "principal": "tester"})
        assert response.status_code == 200
        body = response.json()
        job = body["job"]
        artifact = body["artifact"]
        receipt = body["receipt"]

        assert job["status"] == "succeeded"
        assert job["node_id"] == "node-b"
        assert job["action"] == "run_query"
        assert job["artifact_id"] == artifact["artifact_id"]
        assert job["receipt_id"] == receipt["receipt_id"]
        assert job["artifact_pointer"].startswith(endpoint_b)
        assert job["receipt_pointer"].startswith(endpoint_b)
        assert unique_product not in json.dumps(job)

        assert receipt["node_id"] == "node-b"
        assert receipt["status"] == "succeeded"
        artifact_path = Path(node_b_cfg.artifact_dir) / f"{artifact['artifact_id']}.parquet"
        assert artifact_path.is_file()
        assert ReceiptStore(node_b_cfg.receipt_db).get(receipt["receipt_id"]) is not None
        assert not (Path(node_a_cfg.artifact_dir) / f"{artifact['artifact_id']}.parquet").exists()

        fetched = plane.get(f"/jobs/{job['job_id']}")
        assert fetched.status_code == 200
        assert fetched.json()["status"] == "succeeded"

        plane_bytes = Path(plane_cfg.store_path).read_bytes()
        assert unique_product.encode() not in plane_bytes
        assert b"order_id,product,region,amount" not in plane_bytes

        with sqlite3.connect(plane_cfg.store_path) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job["job_id"],)).fetchone()
        assert row is not None
        serialized = " ".join(str(col) for col in row)
        assert unique_product not in serialized
        assert "order_id,product" not in serialized
    finally:
        server_a.should_exit = True
        server_b.should_exit = True
        for thread in threads:
            thread.join(timeout=5)


def test_plane_job_unknown_node_fails(tmp_path: Path):
    client = TestClient(create_plane_app(_plane_config(tmp_path)))
    response = client.post("/query", json={"node_id": "missing", "sql": "SELECT 1"})
    assert response.status_code == 404
    job = client.get("/jobs").json()["jobs"]
    assert job[0]["status"] == "failed"
    assert job[0]["node_id"] == "missing"


def test_plane_health(tmp_path: Path):
    client = TestClient(create_plane_app(_plane_config(tmp_path)))
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["plane_id"] == "test-plane"
    assert body["node_count"] == 0

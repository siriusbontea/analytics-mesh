from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
from fastapi.testclient import TestClient

from mesh_common.hashing import sha256_file
from mesh_common.receipts import ReceiptStore
from mesh_node.app import create_app
from mesh_node.config import ConnectorConfig, LimitsConfig, NodeConfig


def _config(tmp_path: Path, data_dir: Path) -> NodeConfig:
    return NodeConfig(
        node_id="test-node",
        artifact_dir=tmp_path / "artifacts",
        receipt_db=tmp_path / "receipts.sqlite",
        connectors=[ConnectorConfig(id="local_files", type="local_files", root=data_dir, labels=["personal"])],
        limits=LimitsConfig(default_row_limit=100, max_row_limit=1000, query_timeout_seconds=10),
    )


def test_health(tmp_path: Path, data_dir: Path):
    client = TestClient(create_app(_config(tmp_path, data_dir)))
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["node_id"] == "test-node"
    assert "llm_configured" in body
    assert body["llm_configured"] is False


def test_list_connectors(tmp_path: Path, data_dir: Path):
    client = TestClient(create_app(_config(tmp_path, data_dir)))
    response = client.get("/connectors")
    assert response.status_code == 200
    connectors = response.json()["connectors"]
    assert connectors[0]["id"] == "local_files"
    names = {t["name"] for t in connectors[0]["tables"]}
    assert "sales" in names


def test_run_query_returns_artifact_and_receipt(tmp_path: Path, data_dir: Path):
    client = TestClient(create_app(_config(tmp_path, data_dir)))
    response = client.post(
        "/query",
        json={"sql": "SELECT product, SUM(amount) AS total FROM sales GROUP BY product", "principal": "tester"},
    )
    assert response.status_code == 200
    body = response.json()
    artifact = body["artifact"]
    receipt = body["receipt"]
    assert artifact["format"] == "parquet"
    assert artifact["row_count"] == 3
    assert receipt["status"] == "succeeded"
    assert receipt["principal"] == "tester"
    assert receipt["node_id"] == "test-node"
    assert receipt["receipt_hash"]
    assert receipt["prev_hash"]
    assert receipt["artifact_hash"] == artifact["sha256"]
    assert receipt["model_provider"] is None
    assert receipt["model_id"] is None


def test_get_result_bytes_match_hash(tmp_path: Path, data_dir: Path):
    client = TestClient(create_app(_config(tmp_path, data_dir)))
    query = client.post("/query", json={"sql": "SELECT * FROM sales"}).json()
    artifact_id = query["artifact"]["artifact_id"]
    response = client.get(f"/results/{artifact_id}")
    assert response.status_code == 200
    assert "parquet" in response.headers["content-type"] or response.headers["content-type"] in {
        "application/octet-stream",
        "application/vnd.apache.parquet",
    }
    downloaded = tmp_path / "out.parquet"
    downloaded.write_bytes(response.content)
    assert sha256_file(downloaded) == query["artifact"]["sha256"]
    assert pq.read_table(downloaded).num_rows == 6


def test_get_receipt_matches(tmp_path: Path, data_dir: Path):
    client = TestClient(create_app(_config(tmp_path, data_dir)))
    query = client.post("/query", json={"sql": "SELECT * FROM sales LIMIT 1"}).json()
    receipt_id = query["receipt"]["receipt_id"]
    response = client.get(f"/receipts/{receipt_id}")
    assert response.status_code == 200
    assert response.json()["receipt_hash"] == query["receipt"]["receipt_hash"]


def test_receipt_chain_verifies_after_two_queries(tmp_path: Path, data_dir: Path):
    cfg = _config(tmp_path, data_dir)
    client = TestClient(create_app(cfg))
    first = client.post("/query", json={"sql": "SELECT * FROM sales"}).json()
    second = client.post("/query", json={"sql": "SELECT product FROM sales"}).json()
    assert second["receipt"]["prev_hash"] == first["receipt"]["receipt_hash"]

    store = ReceiptStore(cfg.receipt_db)
    verification = store.verify_chain()
    assert verification.valid is True
    assert verification.count == 2

    chain = client.get("/receipts/chain")
    assert chain.status_code == 200
    assert chain.json()["valid"] is True
    assert chain.json()["count"] == 2


def test_works_without_llm_config(tmp_path: Path, data_dir: Path):
    cfg = _config(tmp_path, data_dir)
    assert cfg.models.is_configured() is False
    client = TestClient(create_app(cfg))
    response = client.post("/query", json={"sql": "SELECT COUNT(*) AS n FROM sales"})
    assert response.status_code == 200
    assert response.json()["artifact"]["row_count"] == 1


def test_bad_sql_writes_failed_receipt(tmp_path: Path, data_dir: Path):
    cfg = _config(tmp_path, data_dir)
    client = TestClient(create_app(cfg))
    response = client.post("/query", json={"sql": "DELETE FROM sales"})
    assert response.status_code == 400
    receipt = response.json()["detail"]["receipt"]
    assert receipt["status"] == "failed"
    assert ReceiptStore(cfg.receipt_db).get(receipt["receipt_id"]).status == "failed"

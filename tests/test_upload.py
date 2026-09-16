from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from mesh_common.hashing import sha256_bytes
from mesh_common.identity import canonical_registration_payload, load_or_create_keypair
from mesh_common.receipts import ReceiptStore
from mesh_common.uploads import (
    DEFAULT_UPLOAD_MAX_BYTES,
    UploadRejected,
    resolve_uploads_dir,
    sanitize_upload_filename,
)
from mesh_node.app import create_app
from mesh_node.config import ConnectorConfig, LimitsConfig, NodeConfig, UploadConfig
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


TINY_CSV = "sku,qty\napple,3\nbanana,5\n"


def _node_config(tmp_path: Path, data_dir: Path, **kwargs) -> NodeConfig:
    return NodeConfig(
        node_id="test-node",
        artifact_dir=tmp_path / "artifacts",
        receipt_db=tmp_path / "receipts.sqlite",
        connectors=[ConnectorConfig(id="local_files", type="local_files", root=data_dir, labels=["personal"])],
        limits=LimitsConfig(default_row_limit=100, max_row_limit=1000, query_timeout_seconds=10),
        **kwargs,
    )


def test_sanitize_upload_filename_accepts_plain_basename():
    assert sanitize_upload_filename("Sales Report.csv") == "Sales_Report.csv"
    assert sanitize_upload_filename("regions.jsonl") == "regions.jsonl"
    assert sanitize_upload_filename("stock.parquet") == "stock.parquet"


def test_sanitize_upload_filename_rejects_traversal_and_absolute():
    with pytest.raises(UploadRejected, match="traversal"):
        sanitize_upload_filename("../etc/passwd.csv")
    with pytest.raises(UploadRejected, match="absolute"):
        sanitize_upload_filename("/tmp/evil.csv")
    with pytest.raises(UploadRejected, match="absolute"):
        sanitize_upload_filename("C:/Windows/evil.csv")
    with pytest.raises(UploadRejected, match="separators"):
        sanitize_upload_filename("nested/dir/file.csv")
    with pytest.raises(UploadRejected, match="unsupported"):
        sanitize_upload_filename("notes.txt")
    with pytest.raises(UploadRejected, match="unsupported"):
        sanitize_upload_filename("payload.exe")


def test_resolve_uploads_dir_defaults_under_root(tmp_path: Path):
    root = tmp_path / "data"
    root.mkdir()
    dest = resolve_uploads_dir(root)
    assert dest == (root / "uploads").resolve()
    dest.relative_to(root.resolve())


def test_resolve_uploads_dir_rejects_escape(tmp_path: Path):
    root = tmp_path / "data"
    root.mkdir()
    with pytest.raises(UploadRejected, match="under the local_files root"):
        resolve_uploads_dir(root, tmp_path / "elsewhere")


def test_upload_csv_to_node_lists_new_table(tmp_path: Path, data_dir: Path):
    cfg = _node_config(tmp_path, data_dir)
    client = TestClient(create_app(cfg))
    response = client.post(
        "/upload",
        files={"file": ("extra.csv", TINY_CSV.encode(), "text/csv")},
        data={"principal": "tester"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["filename"] == "extra.csv"
    assert body["stored_as"] == "extra.csv"
    assert body["bytes"] == len(TINY_CSV.encode())
    assert body["sha256"] == sha256_bytes(TINY_CSV.encode())
    assert body["connector_id"] == "local_files"
    names = {table["name"] for table in body["tables"]}
    assert "extra" in names
    receipt = body["receipt"]
    assert receipt["action"] == "upload"
    assert receipt["status"] == "succeeded"
    assert receipt["principal"] == "tester"
    assert receipt["node_id"] == "test-node"
    assert receipt["analytic_or_sql_hash"] == body["sha256"]
    assert receipt["params"]["filename"] == "extra.csv"
    stored = data_dir / "uploads" / "extra.csv"
    assert stored.is_file()
    assert stored.read_text() == TINY_CSV
    assert ReceiptStore(cfg.receipt_db).get(receipt["receipt_id"]) is not None

    listed = client.get("/connectors")
    assert listed.status_code == 200
    table_names = {table["name"] for table in listed.json()["connectors"][0]["tables"]}
    assert "sales" in table_names
    assert "extra" in table_names


def test_upload_jsonl_is_allowed(tmp_path: Path, data_dir: Path):
    client = TestClient(create_app(_node_config(tmp_path, data_dir)))
    payload = b'{"item":"a"}\n{"item":"b"}\n'
    response = client.post(
        "/upload",
        files={"file": ("events.jsonl", payload, "application/jsonl")},
        data={"principal": "tester"},
    )
    assert response.status_code == 200, response.text
    names = {table["name"] for table in response.json()["tables"]}
    assert "events" in names


def test_upload_uses_configured_uploads_path(tmp_path: Path, data_dir: Path):
    incoming = data_dir / "incoming"
    cfg = NodeConfig(
        node_id="test-node",
        artifact_dir=tmp_path / "artifacts",
        receipt_db=tmp_path / "receipts.sqlite",
        connectors=[
            ConnectorConfig(
                id="local_files",
                type="local_files",
                root=data_dir,
                uploads_path=incoming,
            )
        ],
    )
    client = TestClient(create_app(cfg))
    response = client.post(
        "/upload",
        files={"file": ("custom.csv", TINY_CSV.encode(), "text/csv")},
        data={"principal": "tester"},
    )
    assert response.status_code == 200, response.text
    assert (incoming / "custom.csv").is_file()
    assert not (data_dir / "uploads" / "custom.csv").exists()


def test_upload_rejects_bad_extension(tmp_path: Path, data_dir: Path):
    cfg = _node_config(tmp_path, data_dir)
    client = TestClient(create_app(cfg))
    response = client.post(
        "/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"principal": "tester"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "unsupported" in str(detail).lower()
    receipt = detail["receipt"] if isinstance(detail, dict) else None
    assert receipt is not None
    assert receipt["action"] == "upload"
    assert receipt["status"] == "failed"
    assert not (data_dir / "uploads" / "notes.txt").exists()


def test_upload_rejects_traversal_filename(tmp_path: Path, data_dir: Path):
    client = TestClient(create_app(_node_config(tmp_path, data_dir)))
    response = client.post(
        "/upload",
        files={"file": ("../escape.csv", TINY_CSV.encode(), "text/csv")},
        data={"principal": "tester"},
    )
    assert response.status_code == 400
    assert "traversal" in response.text.lower() or "not allowed" in response.text.lower()
    assert not (data_dir / "escape.csv").exists()
    assert not list(data_dir.rglob("escape.csv"))


def test_upload_rejects_oversize(tmp_path: Path, data_dir: Path):
    cfg = _node_config(tmp_path, data_dir, uploads=UploadConfig(max_bytes=32))
    client = TestClient(create_app(cfg))
    response = client.post(
        "/upload",
        files={"file": ("big.csv", (TINY_CSV * 20).encode(), "text/csv")},
        data={"principal": "tester"},
    )
    assert response.status_code == 400
    assert "size" in response.text.lower() or "exceeds" in response.text.lower()
    assert DEFAULT_UPLOAD_MAX_BYTES == 100 * 1024 * 1024


def test_plane_proxies_upload_and_does_not_store_source(tmp_path: Path, sales_csv_text: str):
    unique = "plane-upload-kiwi-42"
    data = tmp_path / "data"
    data.mkdir()
    (data / "sales.csv").write_text(sales_csv_text)
    node_cfg = NodeConfig(
        node_id="node-b",
        artifact_dir=tmp_path / "artifacts-b",
        receipt_db=tmp_path / "receipts-b.sqlite",
        identity_key_path=tmp_path / "node-b.ed25519",
        connectors=[ConnectorConfig(id="local_files", type="local_files", root=data)],
        limits=LimitsConfig(default_row_limit=100, max_row_limit=1000, query_timeout_seconds=10),
    )
    server = uvicorn.Server(uvicorn.Config(create_app(node_cfg), host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(50):
            if server.started:
                break
            thread.join(0.05)
        assert server.started
        endpoint = f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
        plane_cfg = _plane_config(tmp_path)
        plane = TestClient(create_plane_app(plane_cfg))
        keys = load_or_create_keypair(node_cfg.identity_key_path, "node-b")
        assert plane.post("/nodes/register", json=_registration(keys, endpoint, "demo-pair-token")).status_code == 200

        csv_body = f"item,qty\n{unique},1\n"
        uploaded = plane.post(
            "/nodes/node-b/upload",
            files={"file": ("kiwi.csv", csv_body.encode(), "text/csv")},
            data={"principal": "tester"},
        )
        assert uploaded.status_code == 200, uploaded.text
        body = uploaded.json()
        assert body["receipt"]["node_id"] == "node-b"
        assert body["receipt"]["action"] == "upload"
        assert "kiwi" in {table["name"] for table in body["tables"]}
        assert (data / "uploads" / "kiwi.csv").read_text() == csv_body

        listed = plane.get("/nodes/node-b/connectors")
        assert listed.status_code == 200
        names = {table["name"] for table in listed.json()["connectors"][0]["tables"]}
        assert "kiwi" in names
        assert unique.encode() not in Path(plane_cfg.store_path).read_bytes()
        assert b"item,qty" not in Path(plane_cfg.store_path).read_bytes()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_plane_upload_unknown_node(tmp_path: Path):
    plane = TestClient(create_plane_app(_plane_config(tmp_path)))
    response = plane.post(
        "/nodes/missing/upload",
        files={"file": ("extra.csv", TINY_CSV.encode(), "text/csv")},
        data={"principal": "tester"},
    )
    assert response.status_code == 404

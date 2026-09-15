from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from mesh_common.artifacts import ArtifactStore, ArtifactStoreConfig, ArtifactTooLarge
from mesh_common.receipts import ReceiptStore
from mesh_common.schemas import ArtifactRef
from mesh_node.app import create_app
from mesh_node.config import ConnectorConfig, LimitsConfig, NodeConfig


def _ref(path: Path, artifact_id: str, size_note: str = "x") -> ArtifactRef:
    path.write_bytes(size_note.encode())
    return ArtifactRef(
        artifact_id=artifact_id,
        path=str(path.resolve()),
        format="parquet",
        sha256="ab" * 32,
        row_count=1,
        column_names=["n"],
    )


def test_rejects_file_over_max_bytes(tmp_path: Path):
    store = ArtifactStore(tmp_path / "art", ArtifactStoreConfig(max_bytes_per_file=8, max_total_bytes=1000, max_files=10))
    path = store.root / "big.parquet"
    path.write_bytes(b"0123456789")
    try:
        store.commit(_ref(path, "big", "0123456789"))
        raise AssertionError("expected ArtifactTooLarge")
    except ArtifactTooLarge as exc:
        assert "max_bytes_per_file" in str(exc)
    assert not path.exists()


def test_prunes_oldest_when_over_file_cap(tmp_path: Path):
    store = ArtifactStore(
        tmp_path / "art",
        ArtifactStoreConfig(max_bytes_per_file=1000, max_total_bytes=10_000, max_files=2, retention_days=30),
    )
    first = store.commit(_ref(store.root / "a.parquet", "a", "one"))
    second = store.commit(_ref(store.root / "b.parquet", "b", "two"))
    assert Path(first.path).is_file()
    assert Path(second.path).is_file()
    third = store.commit(_ref(store.root / "c.parquet", "c", "three"))
    assert Path(third.path).is_file()
    remaining = {p.stem for p in store.root.glob("*.parquet")}
    assert remaining == {"b", "c"} or remaining == {"c"} or "c" in remaining
    assert "a" not in remaining
    assert not (store.root / "a.json").exists()


def test_prunes_by_retention_days(tmp_path: Path):
    store = ArtifactStore(
        tmp_path / "art",
        ArtifactStoreConfig(max_bytes_per_file=1000, max_total_bytes=10_000, max_files=50, retention_days=1),
    )
    old = store.commit(_ref(store.root / "old.parquet", "old", "old"))
    old_mtime = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
    Path(old.path).touch()
    Path(old.path).with_suffix(".json").touch()
    import os

    os.utime(old.path, (old_mtime, old_mtime))
    os.utime(Path(old.path).with_suffix(".json"), (old_mtime, old_mtime))
    store.commit(_ref(store.root / "new.parquet", "new", "new"))
    store.enforce()
    assert not Path(old.path).exists()
    assert (store.root / "new.parquet").is_file()


def test_query_enforces_size_cap_and_keeps_receipt_chain(tmp_path: Path, data_dir: Path):
    cfg = NodeConfig(
        node_id="art-node",
        artifact_dir=tmp_path / "artifacts",
        receipt_db=tmp_path / "receipts.sqlite",
        connectors=[ConnectorConfig(id="local_files", type="local_files", root=data_dir)],
        limits=LimitsConfig(default_row_limit=100, max_row_limit=1000, query_timeout_seconds=10),
        artifacts=ArtifactStoreConfig(max_bytes_per_file=1, max_total_bytes=100, max_files=10, retention_days=7),
    )
    client = TestClient(create_app(cfg))
    response = client.post("/query", json={"sql": "SELECT * FROM sales", "principal": "local"})
    assert response.status_code == 400
    receipt = response.json()["detail"]["receipt"]
    assert receipt["status"] == "failed"
    assert "artifact" in (receipt["error"] or "").lower() or "size" in (receipt["error"] or "").lower()
    chain = ReceiptStore(cfg.receipt_db).verify_chain()
    assert chain.valid is True
    assert chain.count == 1

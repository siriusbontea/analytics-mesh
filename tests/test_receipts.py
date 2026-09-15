from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from mesh_common.receipts import GENESIS_HASH, ReceiptStore
from mesh_common.schemas import Receipt


def _draft(**overrides) -> Receipt:
    base = dict(
        receipt_id="r1",
        ts=datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc),
        principal="local",
        node_id="local-dev",
        action="run_query",
        analytic_or_sql_hash="abc",
        connector_versions={"local_files": "0.1.0"},
        engine_version="0.1.0",
        params={"sql": "SELECT 1"},
        artifact_hash="def",
        artifact_id="art-1",
        status="succeeded",
        prev_hash="",
        receipt_hash="",
    )
    base.update(overrides)
    return Receipt.model_validate(base)


def test_first_receipt_chains_from_genesis(tmp_path):
    store = ReceiptStore(tmp_path / "receipts.sqlite")
    saved = store.append(_draft())

    assert saved.prev_hash == GENESIS_HASH
    assert saved.receipt_hash
    assert saved.receipt_hash != GENESIS_HASH
    assert store.head_hash() == saved.receipt_hash
    assert store.verify_chain().valid is True


def test_second_receipt_links_to_first(tmp_path):
    store = ReceiptStore(tmp_path / "receipts.sqlite")
    first = store.append(_draft(receipt_id="r1"))
    second = store.append(_draft(receipt_id="r2", artifact_id="art-2"))

    assert second.prev_hash == first.receipt_hash
    assert second.receipt_hash != first.receipt_hash
    verification = store.verify_chain()
    assert verification.valid is True
    assert verification.count == 2
    assert verification.head_hash == second.receipt_hash


def test_tampered_receipt_fails_verification(tmp_path):
    store = ReceiptStore(tmp_path / "receipts.sqlite")
    store.append(_draft(receipt_id="r1"))
    store.append(_draft(receipt_id="r2"))
    with sqlite3.connect(tmp_path / "receipts.sqlite") as conn:
        conn.execute("UPDATE receipts SET status = ? WHERE receipt_id = ?", ("failed", "r2"))
        conn.commit()

    verification = store.verify_chain()
    assert verification.valid is False
    assert verification.error


def test_get_missing_receipt_returns_none(tmp_path):
    store = ReceiptStore(tmp_path / "receipts.sqlite")
    assert store.get("missing") is None

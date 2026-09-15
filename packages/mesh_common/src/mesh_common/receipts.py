from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from mesh_common.hashing import sha256_text
from mesh_common.schemas import ChainVerification, Receipt

GENESIS_HASH = "0" * 64

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS receipts (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id TEXT NOT NULL UNIQUE,
    ts TEXT NOT NULL,
    principal TEXT NOT NULL,
    node_id TEXT NOT NULL,
    action TEXT NOT NULL,
    analytic_or_sql_hash TEXT NOT NULL,
    connector_versions TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    params TEXT NOT NULL,
    artifact_hash TEXT,
    artifact_id TEXT,
    status TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    model_provider TEXT,
    model_id TEXT,
    error TEXT
)
"""


def _canonical_ts(value: datetime | str) -> str:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonical_receipt_payload(receipt: Receipt) -> str:
    data = receipt.model_dump(mode="json", exclude={"receipt_hash"})
    data["ts"] = _canonical_ts(receipt.ts)
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_receipt_hash(receipt: Receipt) -> str:
    return sha256_text(canonical_receipt_payload(receipt))


class ReceiptStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_CREATE_SQL)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def head_hash(self) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT receipt_hash FROM receipts ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        return row["receipt_hash"] if row else GENESIS_HASH

    def append(self, draft: Receipt) -> Receipt:
        filled = draft.model_copy(update={"prev_hash": self.head_hash(), "receipt_hash": ""})
        complete = filled.model_copy(update={"receipt_hash": compute_receipt_hash(filled)})
        payload = complete.model_dump(mode="json")
        payload["ts"] = _canonical_ts(complete.ts)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO receipts (
                    receipt_id, ts, principal, node_id, action, analytic_or_sql_hash,
                    connector_versions, engine_version, params, artifact_hash, artifact_id,
                    status, prev_hash, receipt_hash, model_provider, model_id, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    complete.receipt_id,
                    payload["ts"],
                    complete.principal,
                    complete.node_id,
                    complete.action,
                    complete.analytic_or_sql_hash,
                    json.dumps(complete.connector_versions, sort_keys=True),
                    complete.engine_version,
                    json.dumps(complete.params, sort_keys=True),
                    complete.artifact_hash,
                    complete.artifact_id,
                    complete.status,
                    complete.prev_hash,
                    complete.receipt_hash,
                    complete.model_provider,
                    complete.model_id,
                    complete.error,
                ),
            )
            conn.commit()
        return complete

    def get(self, receipt_id: str) -> Receipt | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM receipts WHERE receipt_id = ?", (receipt_id,)).fetchone()
        return self._row_to_receipt(row) if row else None

    def list_all(self) -> list[Receipt]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM receipts ORDER BY seq ASC").fetchall()
        return [self._row_to_receipt(row) for row in rows]

    def verify_chain(self) -> ChainVerification:
        receipts = self.list_all()
        prev = GENESIS_HASH
        for receipt in receipts:
            if receipt.prev_hash != prev:
                return ChainVerification(
                    valid=False,
                    count=len(receipts),
                    head_hash=receipts[-1].receipt_hash if receipts else GENESIS_HASH,
                    error=f"prev_hash mismatch at {receipt.receipt_id}",
                )
            expected = compute_receipt_hash(receipt.model_copy(update={"receipt_hash": ""}))
            if expected != receipt.receipt_hash:
                return ChainVerification(
                    valid=False,
                    count=len(receipts),
                    head_hash=receipts[-1].receipt_hash,
                    error=f"receipt_hash mismatch at {receipt.receipt_id}",
                )
            prev = receipt.receipt_hash
        return ChainVerification(
            valid=True,
            count=len(receipts),
            head_hash=prev,
        )

    @staticmethod
    def _row_to_receipt(row: sqlite3.Row) -> Receipt:
        return Receipt.model_validate(
            {
                "receipt_id": row["receipt_id"],
                "ts": row["ts"],
                "principal": row["principal"],
                "node_id": row["node_id"],
                "action": row["action"],
                "analytic_or_sql_hash": row["analytic_or_sql_hash"],
                "connector_versions": json.loads(row["connector_versions"]),
                "engine_version": row["engine_version"],
                "params": json.loads(row["params"]),
                "artifact_hash": row["artifact_hash"],
                "artifact_id": row["artifact_id"],
                "status": row["status"],
                "prev_hash": row["prev_hash"],
                "receipt_hash": row["receipt_hash"],
                "model_provider": row["model_provider"],
                "model_id": row["model_id"],
                "error": row["error"],
            }
        )

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from mesh_common.schemas import JobRecord, NodeRecord

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS nodes (
    node_id TEXT PRIMARY KEY,
    endpoint TEXT NOT NULL,
    public_key TEXT NOT NULL,
    labels TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    principal TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    artifact_id TEXT,
    artifact_pointer TEXT,
    receipt_id TEXT,
    receipt_pointer TEXT,
    sql_hash TEXT,
    error TEXT
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class PlaneStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_CREATE_SQL)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_node(self, record: NodeRecord) -> NodeRecord:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO nodes (node_id, endpoint, public_key, labels, registered_at, last_seen)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    endpoint = excluded.endpoint,
                    public_key = excluded.public_key,
                    labels = excluded.labels,
                    last_seen = excluded.last_seen
                """,
                (
                    record.node_id,
                    record.endpoint,
                    record.public_key,
                    json.dumps(record.labels),
                    _iso(record.registered_at),
                    _iso(record.last_seen) if record.last_seen else None,
                ),
            )
            conn.commit()
        stored = self.get_node(record.node_id)
        assert stored is not None
        return stored

    def get_node(self, node_id: str) -> NodeRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
        return self._row_to_node(row) if row else None

    def list_nodes(self) -> list[NodeRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM nodes ORDER BY node_id").fetchall()
        return [self._row_to_node(row) for row in rows]

    def touch_node(self, node_id: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE nodes SET last_seen = ? WHERE node_id = ?", (_iso(_now()), node_id))
            conn.commit()

    def create_job(
        self,
        node_id: str,
        action: str,
        principal: str,
        sql_hash: str | None = None,
    ) -> JobRecord:
        now = _now()
        record = JobRecord(
            job_id=str(uuid4()),
            node_id=node_id,
            action=action,
            status="queued",
            principal=principal,
            created_at=now,
            updated_at=now,
            sql_hash=sql_hash,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, node_id, action, status, principal, created_at, updated_at,
                    artifact_id, artifact_pointer, receipt_id, receipt_pointer, sql_hash, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.job_id,
                    record.node_id,
                    record.action,
                    record.status,
                    record.principal,
                    _iso(record.created_at),
                    _iso(record.updated_at),
                    record.artifact_id,
                    record.artifact_pointer,
                    record.receipt_id,
                    record.receipt_pointer,
                    record.sql_hash,
                    record.error,
                ),
            )
            conn.commit()
        return record

    def update_job(self, job_id: str, **fields: object) -> JobRecord:
        allowed = {
            "status",
            "artifact_id",
            "artifact_pointer",
            "receipt_id",
            "receipt_pointer",
            "sql_hash",
            "error",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        updates["updated_at"] = _iso(_now())
        assignments = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [job_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE jobs SET {assignments} WHERE job_id = ?", values)
            conn.commit()
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def get_job_by_receipt(self, receipt_id: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE receipt_id = ?", (receipt_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self) -> list[JobRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at").fetchall()
        return [self._row_to_job(row) for row in rows]

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> NodeRecord:
        return NodeRecord.model_validate(
            {
                "node_id": row["node_id"],
                "endpoint": row["endpoint"],
                "public_key": row["public_key"],
                "labels": json.loads(row["labels"]),
                "registered_at": row["registered_at"],
                "last_seen": row["last_seen"],
            }
        )

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> JobRecord:
        return JobRecord.model_validate(dict(row))

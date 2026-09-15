# Analytics Mesh — Implementation Plan

**Date:** 2026-09-15
**Spec:** `docs/design-spec.md`
**Stack bias:** Python for M1 speed (DuckDB, httpx, FastAPI); keep engine/connector interfaces narrow.

## 1. Stack choices (M1)

| Concern | Choice |
| --- | --- |
| Language | Python 3.12+ |
| Node API | FastAPI + pydantic |
| Engine | DuckDB |
| Artifacts | Parquet |
| Receipts | SQLite + hash chain (sha256) |
| LLM client | OpenAI-compatible config stub (unused by analytics) |
| Package mgmt | uv + pyproject workspace |

## 2. M1 tasks

1. `mesh_common`: ArtifactRef, Receipt, Connector/Engine protocols, LlmProviderConfig
2. `local_files` connector (CSV/Parquet/JSON dir)
3. DuckDB engine: load connector files as in-memory tables; run SQL with limits
4. Node service: `health`, `list_connectors`, `run_query`, `get_result`, `get_receipt`
5. CLI: `mesh serve`, `mesh query`, `mesh receipt`
6. Tests: sample dataset → query → artifact + verifiable receipt chain
7. Docs: one-page README to run on one machine in ~5 minutes

**Exit:** On one machine, query local CSV/Parquet without a control plane.

## 2b. M2 tasks (implemented)

1. Node Ed25519 identity (`identity_key_path`) and `/health.public_key`
2. `mesh_plane`: node registry, job records (`queued` → `running` → `succeeded`/`failed`), proxy `run_query` / result / receipt metadata
3. Client talks to the plane; plane does not store source tables — only job metadata and pointers
4. Two-node demo: `scripts/two-node-demo.sh` or `node-a` / `node-b` / `plane` example configs on localhost
5. CLI: `mesh plane`, `mesh pair`, `mesh nodes`, `mesh jobs`, `mesh query --node`, receipt fetch via plane (verified on the owning node)

**Exit:** From a client, run SQL on Node B via the plane; artifact and receipt live on B.

## 3. LLM config (later)

Analytics works with **zero** LLM configured. `configs/examples/models.yaml` documents the shape (main / auxiliary / fallback, `local_only` by default). Assist features degrade if no model is up. Do not commit secrets.

## 4. Not in M2

Web UI / analytic registry (M3), Postgres, NL→SQL, policy engine (M4), MCP (M5), federated learning, enterprise decision UI.

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

## 3. M3 tasks (implemented)

1. Analytic registry: YAML + SQL under `analytics/`, semver, `list` + `run` by id
2. Node/plane web UI at `/ui` (node pick via plane, analytic or SQL, table, artifact, receipt)
3. OpenAI-compatible client + `configs/examples/models.yaml` (main / auxiliary / fallback); optional `GET /models?probe=true`
4. Receipt `model_provider` / `model_id` only when an assist path is used (M3 assist is a stub)

**Exit:** Registry load and run-by-id tests pass; UI/API smoke; analytics work with zero LLM.

## 4. M4 tasks (implemented)

1. YAML policy allowlists (`PolicyEngine` + `configs/examples/policy.yaml`): principals, connectors, analytics, nodes, row/time caps, `local_only` vs `allow_frontier`. Enforced on `run_query` / `run_analytic` / assist.
2. Artifact store caps (`artifacts:` on the node): per-file and total size, retention days, max files. Receipt hash chain is unchanged and not pruned.
3. Read-only Postgres connector plugin + example config + docker-compose service. Tests: SQL/config unit tests; optional `@pytest.mark.integration`.
4. NL→SQL assist (`POST /assist/nl2sql`, `mesh assist --question`): propose only; `--confirm-run` / UI confirm required to execute. Explain assist uses auxiliary (local preferred). Receipts record `model_provider` / `model_id` when assist is used.

**Exit:** Policy denials 403; NL→SQL never auto-runs; `uv run pytest` green.

## 5. Not in M4

MCP + Polars (M5), federated learning, Hermes learning loop, messaging gateways, full OPA deployment.

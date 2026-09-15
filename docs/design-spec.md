# Analytics Mesh — Design Spec (v1)

**Date:** 2026-09-15
**Status:** Approved 2026-09-15
**Decision locked:** Query-first local analytics; job dispatch as transport spine; agents and federated learning deferred.

## 1. Problem

Data useful for analysis sits on different machines. Centralizing it is slow, risky, or forbidden. The daily need is federated *query*: run analysis where the data already lives and bring back a result plus proof of what ran.

## 2. Goals

- Be useful for data analytics on day one (SQL / dataframe / registered analytic → table or file artifact).
- Keep data on the owning node by default; move results and receipts, not source tables.
- Stay small-scale (a handful of machines on LAN or Tailscale), highly configurable and modular.
- Make every run attributable: who, which node, which connector/analytic version, when, outcome.

## 3. Non-goals (v1)

- Federated learning.
- Cell-level ABAC theater or classified/air-gap packaging.
- Cross-node distributed joins as a first-class feature.
- Kitchen-sink enterprise UI or decision-case-management suites.
- Agents with open-ended filesystem or DB credentials.
- Replacing warehouses.
- Shipping or fine-tuning a custom foundation model (we consume local + frontier APIs).

## 4. Design principles

1. Data ownership stays with the node.
2. Dispatch is plumbing; analytics is the product.
3. Plugins over monolith: connectors, engines, policy, audit, UI swap independently.
4. Registered work over ad-hoc power: prefer versioned analytics; allow SQL in a sandbox.
5. Receipts are first-class artifacts, not log afterthoughts.
6. Boring engines win: DuckDB / Polars / Arrow before custom runtimes.

## 5. Architecture

- **Node:** executes queries/analytics; holds connectors + local engines + local receipt log.
- **Control plane (M2+):** pairing, node directory, allowlists, job routing, result fetch metadata. Does not become a data lake.
- **Clients:** CLI now; web and MCP later, calling the same job API.

## 6. M1 modules

### Node runtime

HTTPS+JSON (FastAPI). Logical endpoints: `health`, `list_connectors`, `run_query`, `get_result`, `get_receipt`.

### Connector plugin API

Each connector implements `id`, `version`, `sensitivity_labels`, `discover_schema()`, and `scan(...)` → Arrow batches. Engines pull; connectors do not run SQL.

M1 connector: local Parquet/CSV/JSON directory.

### Engine plugin API

`id`, `version`, `execute(plan) → ArtifactRef`. M1 engine: DuckDB SQL over registered connector tables.

### Receipts

Append-only SQLite + SHA-256 hash chain on the node: `receipt_id`, `ts`, `principal`, `node_id`, `action`, `analytic_or_sql_hash`, `connector_versions`, `engine_version`, `params`, `artifact_hash`, `status`, `prev_hash`.

### Model provider layer (stub only in M1)

One OpenAI-compatible client interface (`base_url` + `model`). Main vs auxiliary slots and a fallback list. Analytics must work with zero LLM configured.

## 7. Milestone plan

| Milestone | Outcome |
| --- | --- |
| M1 | Single-node: CSV/Parquet connector + DuckDB SQL + receipt + CLI |
| M2 | Second node; control plane lists nodes and routes `run_*` |
| M3 | Analytic registry + simple web UI + model provider config |
| M4 | Policy allowlists + artifact store; Postgres connector; optional NL→SQL |
| M5 | MCP adapter (analytics toolset only); optional Polars engine |

## 8. Success criteria (v1)

- Run sandboxed SQL on a node without copying source datasets to the client.
- Result artifact opens locally; receipt verifies on the node (hash chain intact).
- Adding a connector or analytic is a plugin/config change, not a core fork.

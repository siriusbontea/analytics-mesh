# Analytics Mesh

Query-first local analytics. Point a node at a directory of CSV, Parquet, or JSON files, run sandboxed DuckDB SQL, and get a Parquet artifact plus a hash-chained receipt. No LLM is required.

M1 is a **single node** on one machine. M2 adds a thin **control plane** that registers nodes and routes `run_query` to a target node. The plane stores job metadata and pointers only — not source tables. M3 adds a **versioned analytic registry**, a **minimal web UI**, and optional **OpenAI-compatible model config**. M4 adds **YAML policy allowlists**, **artifact retention/size caps**, a **read-only Postgres connector**, and optional **NL→SQL assist** that never auto-executes. M5 completes v1: an **analytics-only MCP adapter**, an optional **Polars engine**, and a **main → fallback** assist chain recorded on receipts. M6 polishes that same **single-file `/ui`**: dark/light theme, connectors and plane jobs, receipt verify/copy, an editable principal, and a light SVG bar chart on suitable previews. M7 adds an in-page **Help drawer** and accessible **tooltips** so you can learn the tool without leaving `/ui`. M8 fixes **`mesh receipt --verify-chain` against a direct node**, adds **GitHub Actions CI**, and ships **`scripts/deep-smoke.sh`**. M9 adds **Playwright browser tests** for `/ui` (Help drawer + a successful `top_products` run) in a separate CI job. Analytics still work with **zero** LLM configured.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Run on one machine (~5 minutes)

From the repo root:

```bash
uv sync
uv run mesh serve --config configs/examples/node.yaml
```

In another terminal, still from the repo root:

```bash
uv run mesh health
uv run mesh connectors
uv run mesh analytics list
uv run mesh analytics run top_products
uv run mesh query --sql "SELECT product, SUM(amount) AS total FROM sales GROUP BY product ORDER BY total DESC"
```

Open the node web UI at [http://127.0.0.1:8080/ui](http://127.0.0.1:8080/ui): pick an analytic or paste SQL, view the result table and a light bar chart when the preview has a label + numeric pair, download the Parquet artifact, and inspect the receipt. Use **Help** (or `#help`) for in-page docs and hover/focus tips on the controls.

The query command prints JSON with `artifact` (Parquet path + sha256) and `receipt` (id, prev_hash, receipt_hash). Fetch the receipt again with:

```bash
uv run mesh receipt <receipt_id>
uv run mesh receipt <receipt_id> --verify-chain
```

Download the artifact:

```bash
uv run mesh query --sql-file analytics/examples/top_products.sql --out /tmp/top_products.parquet
```

Sample data is `data/samples/sales.csv`, exposed as table `sales`.

## Two-node demo (M2)

The plane is a scheduler, not a data lake. Node A and Node B each keep their own files, artifacts, and receipt chain. The client talks to the plane; the plane forwards SQL to the chosen node and records a job (`queued` → `running` → `succeeded`/`failed`) with pointers back to that node.

LAN/localhost is enough. Pairing uses a shared registration token (`demo-pair-token` in the example configs) plus each node's Ed25519 keypair. Replace the token for anything beyond a laptop demo; the register API is the hook for stronger pairing later. Tailscale is optional: if nodes are on a tailnet, put those addresses in `plane.public_endpoint` instead of `127.0.0.1`.

### One-shot script

From the repo root (starts plane + two nodes, registers them, runs a query on Node B):

```bash
chmod +x scripts/two-node-demo.sh
./scripts/two-node-demo.sh
```

Ctrl-C stops the three processes.

### Three terminals

```bash
# terminal 1 — control plane
uv run mesh plane --config configs/examples/plane.yaml

# terminal 2 — Node A (data/samples/sales.csv)
uv run mesh serve --config configs/examples/node-a.yaml

# terminal 3 — Node B (data/samples/node-b/sales.csv, includes babylon-sprocket)
uv run mesh serve --config configs/examples/node-b.yaml
```

Nodes register with the plane on startup. If you started a node before the plane, pair it:

```bash
uv run mesh pair --config configs/examples/node-a.yaml --url http://127.0.0.1:8090 --token demo-pair-token
uv run mesh pair --config configs/examples/node-b.yaml --url http://127.0.0.1:8090 --token demo-pair-token
```

Then, from any terminal:

```bash
uv run mesh nodes --url http://127.0.0.1:8090
uv run mesh analytics list --url http://127.0.0.1:8090 --node node-b
uv run mesh analytics run top_products --url http://127.0.0.1:8090 --node node-b
uv run mesh query --url http://127.0.0.1:8090 --node node-b \
  --sql "SELECT product, SUM(amount) AS total FROM sales GROUP BY product ORDER BY total DESC"
uv run mesh jobs --url http://127.0.0.1:8090
uv run mesh receipt <receipt_id> --url http://127.0.0.1:8090 --verify-chain
```

The plane UI at [http://127.0.0.1:8090/ui](http://127.0.0.1:8090/ui) lets you pick a registered node, then run an analytic or SQL the same way. Direct-to-node UI remains on each node (`http://127.0.0.1:8082/ui` for Node B).

The query JSON includes a `job` record (`artifact_pointer`, `receipt_pointer`) and the node's artifact/receipt metadata. The Parquet file and hash-chained receipt stay under `var/node-b/`. The plane SQLite at `var/plane/plane.sqlite` has job rows only — no source CSV.

Direct-to-node M1 commands still work (`--url http://127.0.0.1:8082` without `--node`).

## Tests

```bash
uv sync --group dev
uv run pytest
```

Pull requests and pushes to `main` run that same gate in GitHub Actions (Python 3.12 + `uv`). After `mesh serve`, or hermetically with `--start`, a deeper post-serve check is:

```bash
./scripts/deep-smoke.sh          # assumes http://127.0.0.1:8080
./scripts/deep-smoke.sh --start  # temp node on an ephemeral port
```

`pytest` (unit/API) and `pytest-ui` (Playwright) are required CI gates. `deep-smoke` is an optional workflow job (`continue-on-error`) that starts its own temp node.

### Browser UI tests (M9)

These drive Chromium against a temp node on an ephemeral port (same idea as `./scripts/deep-smoke.sh --start`). They are marked `@pytest.mark.ui` and live under `tests/ui/`, so a plain `uv run pytest` stays the fast unit/API suite.

```bash
uv sync --group dev
uv run playwright install chromium   # once per machine; CI also uses --with-deps
uv run pytest -m ui --browser chromium
```

`uv run pytest tests/ui` is equivalent. Headed debugging: add `--headed`.

## Layout

```
packages/mesh_common/     schemas, hash-chained receipts, analytic registry, OpenAI-compatible LLM client, web UI
packages/mesh_node/       FastAPI node: health, connectors, analytics, query, results, receipts, models, /ui
packages/mesh_plane/      thin control plane: node registry, jobs, proxy run_query / run_analytic, /ui
packages/mesh_client/     CLI: serve / plane / pair / nodes / jobs / query / analytics / assist / mcp / receipt
packages/mesh_mcp/        analytics-only MCP adapter (stdio or HTTP)
plugins/connectors/local_files/
plugins/connectors/postgres/
plugins/engines/duckdb_engine/
plugins/engines/polars_engine/   optional; DuckDB stays default
analytics/                versioned YAML + SQL analytics (scanned from node `analytics_dir`)
configs/examples/         node.yaml, policy.yaml, models.yaml, node-postgres.yaml, plane.yaml
deploy/systemd/           mesh-node / mesh-plane / mesh-mcp unit files
docker-compose.yml        optional Postgres for the read-only connector
scripts/two-node-demo.sh  localhost two-node walkthrough
scripts/deep-smoke.sh     post-serve / hermetic checks (health, analytic, receipt chain, policy, assist, Help UI)
.github/workflows/ci.yml  pytest + Playwright UI on PR and main; optional deep-smoke
tests/                    unit/API; tests/ui/ is Playwright (`pytest -m ui`)
```

## API

### Node

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` or `/ui` | Browser UI (this node) |
| GET | `/health` | Node status (includes `public_key`, `llm_configured`) |
| GET | `/connectors` | Connector ids, versions, discovered tables |
| GET | `/analytics` | Registered analytics (id, semver, engine, SQL) |
| POST | `/analytics/run` | Run by `analytic_id` (optional `version`) |
| POST | `/query` | Sandboxed SQL + row/time limits (policy-gated) |
| GET | `/results/{artifact_id}` | Parquet download |
| GET | `/results/{artifact_id}/preview` | JSON table preview |
| GET | `/models` | Provider slots; `?probe=true` hits `/v1/models` if configured |
| POST | `/assist/nl2sql` | Propose SQL from a question (never executes) |
| POST | `/assist/explain` | Optional explain of a capped preview (auxiliary model) |
| GET | `/receipts/{receipt_id}` | Receipt record |
| GET | `/receipts/chain` | Hash-chain verification |

### Plane

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` or `/ui` | Browser UI (pick a registered node) |
| GET | `/health` | Plane status + registered node count |
| POST | `/nodes/register` | Pair a node (token + Ed25519 signature) |
| GET | `/nodes` | Node directory |
| GET | `/nodes/{node_id}/analytics` | Proxy `list_analytics` |
| GET | `/nodes/{node_id}/connectors` | Proxy `list_connectors` |
| POST | `/nodes/{node_id}/assist/nl2sql` | Proxy NL→SQL propose (never executes) |
| POST | `/nodes/{node_id}/assist/explain` | Proxy explain assist |
| POST | `/query` | Create a job and proxy `run_query` to `node_id` |
| POST | `/analytics/run` | Create a job and proxy `run_analytic` to `node_id` |
| GET | `/jobs` | Job records (metadata + pointers) |
| GET | `/jobs/{job_id}` | One job |
| GET | `/jobs/{job_id}/result` | Stream the artifact from the owning node (not stored on the plane) |
| GET | `/receipts/{receipt_id}` | Fetch the receipt from the owning node |
| GET | `/nodes/{node_id}/receipts/{receipt_id}` | Same, when you already know the node |
| GET | `/nodes/{node_id}/receipts/chain` | Verify the hash chain on that node |

Ad-hoc SQL must be a single `SELECT` or `WITH`. File-read functions, DML, and multi-statement batches are rejected. Results are capped by `limits` in the node config.

Receipts are stored in SQLite on the **owning node** and chained with SHA-256: each receipt hashes its payload plus `prev_hash` (the first receipt links to a genesis hash of 64 zeros). The plane may store receipt ids and URLs; the node remains the source of truth for verification.

## M3 — analytic registry, web UI, models

### Registry layout

Set `analytics_dir` on the node (example configs use `analytics`). The node loads every `*.yaml` / `*.yml` under that tree:

```yaml
analytic_id: top_products
version: 1.0.0
engine: duckdb
entry: top_products.sql
allowed_connectors:
  - local_files
description: Rank products by total sales amount
```

`entry` is a SQL file next to the YAML. Semver is required; `mesh analytics run <id>` uses the latest version unless `--version` is set. Shipped examples: `top_products`, `sales_by_region`.

```bash
uv run mesh analytics list
uv run mesh analytics run top_products
uv run mesh analytics run top_products --url http://127.0.0.1:8090 --node node-b
```

### Web UI

The same static page is served from **both** the node and the plane:

| Process | URL | Behavior |
| --- | --- | --- |
| Node (`mesh serve`) | http://127.0.0.1:8080/ui | Talks to that node only |
| Plane (`mesh plane`) | http://127.0.0.1:8090/ui | Pick a registered node, then run |

Pick an analytic or paste SQL, view the result table, download the artifact, and read the receipt. There is no decision-case workflow. Use **Propose SQL** then **Confirm and run proposed SQL** for NL→SQL; the propose step never executes. M6 keeps this a single static file (no frontend build): Run / Result / Receipt sit as equal panels, with connectors, plane jobs, theme, and receipt helpers described below. M7 adds the **Help** drawer (`#help` / `#help=receipts`) and hover/focus tooltips on the major controls.

### Models (optional)

`configs/examples/models.yaml` is the Hermes-inspired slot shape: `main`, `auxiliary`, `fallback`, plus `policy.default_mode: local_only`. One OpenAI-compatible client talks to local (Ollama / LM Studio / vLLM) and frontier (`base_url` + `model`). Point a node at it with `models_path: configs/examples/models.yaml`, or copy the slots under `models:`.

Analytics never require this file. `GET /models?probe=true` optionally calls `{base_url}/models`. Do not put API keys in YAML; use `api_key_env`.

## M4 — policy, artifacts, Postgres, NL→SQL

### Policy file

Example nodes point at `configs/examples/policy.yaml`. If `policy_path` is omitted, the node allows every principal (M1–M3 behavior). The YAML engine implements `PolicyEngine.authorize()` so OPA/Cedar can replace it later without changing `run_query` / `run_analytic` / assist call sites.

```yaml
deny_unknown_principals: true
principals:
  local:
    allow_adhoc_sql: true
    allow_assist: true
    connectors: ["*"]      # or explicit connector ids
    analytics: ["*"]       # or explicit analytic ids
    nodes: ["*"]           # or explicit node ids
    max_row_limit: 10000
    query_timeout_seconds: 30
    model_mode: local_only # or allow_frontier
```

`model_mode: local_only` blocks frontier NL→SQL / explain. `allow_frontier` may send schema + question + a capped preview only — never full source tables. Denied `run_*` / assist calls return HTTP 403 and append a failed receipt.

### Artifact store

Caps live under `artifacts:` on the node (defaults: 100 MiB per file, 1 GiB total, 7-day retention, 200 files). Oversize results fail the query; older parquet + sidecar JSON pairs are pruned. **Receipts stay on the node SQLite hash chain** and are never deleted by this store.

### Postgres connector (read-only)

Plugin: `plugins/connectors/postgres`. Sessions set `default_transaction_read_only`. Example:

```yaml
- id: postgres
  type: postgres
  dsn_env: MESH_POSTGRES_DSN
  schemas: [public]
```

```bash
docker compose up -d postgres
export MESH_POSTGRES_DSN=postgresql://mesh:mesh@127.0.0.1:5432/mesh
uv run mesh serve --config configs/examples/node-postgres.yaml
```

Unit tests cover SQL generation and connection config. Live discover/scan is `@pytest.mark.integration` (uses `MESH_POSTGRES_DSN`, or testcontainers if installed; otherwise skipped).

### NL→SQL confirm flow

```bash
uv run mesh assist --question "Which product sold the most?"
# prints proposed SQL only
uv run mesh assist --question "Which product sold the most?" --confirm-run
```

`--confirm-run` is required to execute. The web UI has the same two-step **Propose SQL** / **Confirm and run proposed SQL** buttons. `/assist/nl2sql` never calls the engine. When a confirmed run uses a proposal, the query receipt records `model_provider` / `model_id`. Explain assist prefers the auxiliary (local) slot and a capped preview.

If no model is configured, assist returns a clear error and analytics still work.

When assist is used, the node tries **main** (NL→SQL) or **auxiliary** (explain), then the configured `fallback` list in order. Capacity / timeout / auth failures skip to the next slot. The receipt records who actually served:

| Field | Meaning |
| --- | --- |
| `model_provider` / `model_id` | Slot that produced the answer |
| `model_slot` | `main`, `auxiliary`, `fallback`, or `fallback[n]` |
| `model_fallback_used` | `true` when a fallback slot served |
| `model_attempts` | Each tried slot: `slot`, `provider`, `model`, `status`, `error` |

`local_only` still strips frontier slots from the chain before the first call.

## M5 — MCP, Polars, fallback receipts, v1 complete

M1–M5 together are v1: query where the data lives, return an artifact plus a verifiable receipt, keep source tables on the owning node.

| Milestone | What it added |
| --- | --- |
| M1 | Single-node CSV/Parquet + DuckDB SQL + receipts + CLI |
| M2 | Thin plane, pairing, job routing to a second node |
| M3 | Analytic registry, web UI, OpenAI-compatible model slots |
| M4 | YAML policy, artifact caps, Postgres connector, NL→SQL confirm |
| M5 | MCP analytics toolset, optional Polars engine, fallback receipts |
| M6 | Browser UI polish: theme, connectors/jobs, receipt helpers, SVG chart |
| M7 | In-UI Help drawer and accessible tooltips |
| M8 | Direct-node `--verify-chain`, GitHub Actions CI, `scripts/deep-smoke.sh` |
| M9 | Playwright browser tests for `/ui` (Help + Run analytic) |

### MCP adapter (analytics toolset only)

The adapter is a client of the node (or plane), not a second execution path. Tools call the same policy-gated HTTP APIs as `mesh analytics` / `mesh receipt`. There is **no** `run_query`, raw SQL, shell, or connector-credential tool.

| Tool | Upstream API |
| --- | --- |
| `list_analytics` | `GET /analytics` or `GET /nodes/{id}/analytics` |
| `run_analytic` | `POST /analytics/run` |
| `get_receipt` | `GET /receipts/{id}` (or plane node-scoped path) |
| `list_connectors` | `GET /connectors` (optional) |
| `list_nodes` | `GET /nodes` on the plane (optional) |

Start a node (or plane), then the adapter:

```bash
# stdio — point Cursor / Claude Desktop / other MCP clients at this command
uv run mesh mcp --url http://127.0.0.1:8080 --principal local

# HTTP JSON — GET /tools, POST /tools/{name}
uv run mesh mcp --transport http --host 127.0.0.1 --port 8765

# Official MCP Streamable HTTP (path /mcp) for MCP-native clients
uv run mesh mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

`python -m mesh_mcp` and the `mesh-mcp` script honor `MESH_URL`, `MESH_PRINCIPAL`, `MESH_NODE`, `MESH_MCP_TRANSPORT`, `MESH_MCP_HOST`, `MESH_MCP_PORT`.

Cursor / Claude Desktop example (`~/.cursor/mcp.json` or Claude's MCP config):

```json
{
  "mcpServers": {
    "analytics-mesh": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/analytics-mesh", "mesh", "mcp"],
      "env": {
        "MESH_URL": "http://127.0.0.1:8080",
        "MESH_PRINCIPAL": "local"
      }
    }
  }
}
```

Via the plane, set `MESH_URL` to the plane and `MESH_NODE` (or `--node`) to the target node id. Ad-hoc SQL stays on the CLI/web confirm path; MCP will not invent a SQL tool unless you add one that goes through the same `/query` policy (not shipped).

HTTP smoke:

```bash
curl -s http://127.0.0.1:8765/tools
curl -s -X POST http://127.0.0.1:8765/tools/list_analytics
curl -s -X POST http://127.0.0.1:8765/tools/run_analytic \
  -H 'content-type: application/json' \
  -d '{"arguments":{"analytic_id":"top_products"}}'
```

### Optional Polars engine

DuckDB remains the default for `mesh query` and analytics with `engine: duckdb`. Register a Polars analytic with `engine: polars` (example: `top_products_polars`, same SQL as `top_products`). The node loads `plugins/engines/polars_engine` when the package is installed; if Polars is omitted, DuckDB-only nodes still run.

```bash
uv run mesh analytics run top_products_polars
```

### Auth and services

- Default listen address is `127.0.0.1`. Put nodes on LAN or Tailscale; do not publish MCP or node HTTP on a public NIC.
- Pairing still uses the registration token + node Ed25519 key. Replace `demo-pair-token` outside a laptop demo.
- Policy principals (`--principal` / `MESH_PRINCIPAL`) are the authorization identity. MCP does not add a second auth layer; it forwards the principal to the node. Unknown principals are denied when `deny_unknown_principals` is set.
- Connector secrets stay on the node (`dsn_env`, keychain). They are never tools, YAML API keys, or MCP arguments.
- Artifact size/retention caps are unchanged from M4 (`artifacts:` on the node).
- Service-friendly entrypoints: `mesh serve` / `mesh plane` / `mesh mcp`, `python -m mesh_node` / `mesh_plane` / `mesh_mcp`, and scripts `mesh-node`, `mesh-plane`, `mesh-mcp`. Example units: `deploy/systemd/`.

Out of v1 scope (unchanged): federated learning, Hermes learning loop / messaging gateways, full OPA, Axonis decision-graph UI.

## M6 — browser UI polish

The same `packages/mesh_common/src/mesh_common/static/ui.html` is still served at `/` and `/ui` on both node and plane. No React/Vue, no bundler, no chart package.

- **Layout:** Run, Result, and Receipt are equal panels. Primary actions stay sticky. Loading and API errors are written in plain language.
- **Theme:** follows `prefers-color-scheme`, with an Auto / Light / Dark toggle (remembered locally).
- **Connectors:** `GET /connectors` on a node, or `GET /nodes/{id}/connectors` on the plane, so you can see discovered table names before querying.
- **Plane jobs:** `GET /jobs` with status and an `#job=` deep-link that loads preview + receipt when the job succeeded.
- **Receipt:** copy receipt id, **Verify chain** (`GET /receipts/chain` or the node-scoped plane path), plus a collapsed summary instead of only a JSON wall.
- **Principal:** editable field (default `web`) sent on run / assist instead of a hard-coded value.
- **Chart:** when a preview has a string-ish label column and a numeric column (and not too many rows), a small SVG bar chart renders above the table. Other shapes stay table-only.

## M7 — Help drawer and tooltips

Still the same `ui.html`. **Help** in the topbar opens a right-side drawer (Close, Esc, or backdrop). Sections cover getting started, concepts, CLI vs UI, receipts, plane vs node, policy, and the analytics-only MCP tools. `#help` or `#help=<section>` deep-links into a section. Hover or focus a control (or its **?**) for a short tooltip: what it is, and what happens when you use it.

## M8 — verify-chain, CI, deep smoke

`mesh receipt <id> --verify-chain` looks at `/health` to decide which chain URL to call:

| Target | `/health` | Chain path |
| --- | --- | --- |
| Direct node | `node_id` | `GET /receipts/chain` |
| Control plane | `plane_id` | `GET /nodes/{id}/receipts/chain` |

Receipts always include `node_id` (the owning node). Using that field as a plane path against `http://127.0.0.1:8080` 404s. After a successful `mesh analytics run top_products` on a node, `--verify-chain` exits 0 and prints `valid: true`.

## M9 — browser UI tests

`/ui` stays the same single static file. M9 does not add a frontend stack.

Playwright (Python `pytest-playwright`) opens `/ui` on a hermetic temp node:

1. **Help** is visible; the drawer shows **Getting started** (and Concepts); Close and Esc dismiss it.
2. Select `top_products`, click **Run**, wait for the preview table (gadget / widget / sprocket) and a receipt id (or enabled **Copy receipt id**).

Install Chromium once, then `uv run pytest -m ui`. GitHub Actions runs that as the required `pytest-ui` job (browsers installed with `--with-deps`). Default `uv run pytest` does not collect these tests.

## Docs

- [Design spec](docs/design-spec.md)
- [Implementation plan](docs/implementation-plan.md)

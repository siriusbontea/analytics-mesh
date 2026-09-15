# Analytics Mesh

Query-first local analytics. Point a node at a directory of CSV, Parquet, or JSON files, run sandboxed DuckDB SQL, and get a Parquet artifact plus a hash-chained receipt. No LLM is required.

M1 is a **single node** on one machine. M2 adds a thin **control plane** that registers nodes and routes `run_query` to a target node. The plane stores job metadata and pointers only — not source tables.

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
uv run mesh query --sql "SELECT product, SUM(amount) AS total FROM sales GROUP BY product ORDER BY total DESC"
```

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
uv run mesh query --url http://127.0.0.1:8090 --node node-b \
  --sql "SELECT product, SUM(amount) AS total FROM sales GROUP BY product ORDER BY total DESC"
uv run mesh jobs --url http://127.0.0.1:8090
uv run mesh receipt <receipt_id> --url http://127.0.0.1:8090 --verify-chain
```

The query JSON includes a `job` record (`artifact_pointer`, `receipt_pointer`) and the node's artifact/receipt metadata. The Parquet file and hash-chained receipt stay under `var/node-b/`. The plane SQLite at `var/plane/plane.sqlite` has job rows only — no source CSV.

Direct-to-node M1 commands still work (`--url http://127.0.0.1:8082` without `--node`).

## Tests

```bash
uv sync --group dev
uv run pytest
```

## Layout

```
packages/mesh_common/     schemas, hash-chained receipts, node identity, connector/engine protocols, LLM config stub
packages/mesh_node/       FastAPI node: health, connectors, query, results, receipts, plane pairing
packages/mesh_plane/      thin control plane: node registry, jobs, proxy run_query / receipt metadata
packages/mesh_client/     CLI: serve / plane / pair / nodes / jobs / query / receipt
plugins/connectors/local_files/
plugins/engines/duckdb_engine/
analytics/examples/       optional SQL you can pass with --sql-file
configs/examples/         node.yaml, node-a.yaml, node-b.yaml, plane.yaml
scripts/two-node-demo.sh  localhost two-node walkthrough
tests/
```

## API

### Node

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Node status (includes `public_key`, `llm_configured`) |
| GET | `/connectors` | Connector ids, versions, discovered tables |
| POST | `/query` | Sandboxed SQL + row/time limits |
| GET | `/results/{artifact_id}` | Parquet download |
| GET | `/receipts/{receipt_id}` | Receipt record |
| GET | `/receipts/chain` | Hash-chain verification |

### Plane

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Plane status + registered node count |
| POST | `/nodes/register` | Pair a node (token + Ed25519 signature) |
| GET | `/nodes` | Node directory |
| POST | `/query` | Create a job and proxy `run_query` to `node_id` |
| GET | `/jobs` | Job records (metadata + pointers) |
| GET | `/jobs/{job_id}` | One job |
| GET | `/jobs/{job_id}/result` | Stream the artifact from the owning node (not stored on the plane) |
| GET | `/receipts/{receipt_id}` | Fetch the receipt from the owning node |
| GET | `/nodes/{node_id}/receipts/{receipt_id}` | Same, when you already know the node |
| GET | `/nodes/{node_id}/receipts/chain` | Verify the hash chain on that node |

Ad-hoc SQL must be a single `SELECT` or `WITH`. File-read functions, DML, and multi-statement batches are rejected. Results are capped by `limits` in the node config.

Receipts are stored in SQLite on the **owning node** and chained with SHA-256: each receipt hashes its payload plus `prev_hash` (the first receipt links to a genesis hash of 64 zeros). The plane may store receipt ids and URLs; the node remains the source of truth for verification.

## Models (optional, unused in M1/M2)

`configs/examples/models.yaml` is the config shape for later OpenAI-compatible local and frontier providers. Analytics works with **zero** LLM configured. Do not put API keys in YAML; if you add a provider later, point `api_key_env` at an environment variable.

## Docs

- [Design spec](docs/design-spec.md)
- [Implementation plan](docs/implementation-plan.md)

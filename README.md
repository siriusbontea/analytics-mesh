# Analytics Mesh

Query-first local analytics. Point a node at a directory of CSV, Parquet, or JSON files, run sandboxed DuckDB SQL, and get a Parquet artifact plus a hash-chained receipt. No LLM is required.

M1 is a **single node** on one machine. There is no control plane, web UI, Postgres connector, or MCP adapter yet.

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

## Tests

```bash
uv sync --group dev
uv run pytest
```

## Layout

```
packages/mesh_common/     schemas, hash-chained receipts, connector/engine protocols, LLM config stub
packages/mesh_node/       FastAPI node: health, connectors, query, results, receipts
packages/mesh_client/     CLI: serve / query / receipt
plugins/connectors/local_files/
plugins/engines/duckdb_engine/
analytics/examples/       optional SQL you can pass with --sql-file
configs/examples/         node.yaml and unused models.yaml shape
tests/
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Node status (includes `llm_configured`) |
| GET | `/connectors` | Connector ids, versions, discovered tables |
| POST | `/query` | Sandboxed SQL + row/time limits |
| GET | `/results/{artifact_id}` | Parquet download |
| GET | `/receipts/{receipt_id}` | Receipt record |
| GET | `/receipts/chain` | Hash-chain verification |

Ad-hoc SQL must be a single `SELECT` or `WITH`. File-read functions, DML, and multi-statement batches are rejected. Results are capped by `limits` in the node config.

Receipts are stored in SQLite and chained with SHA-256: each receipt hashes its payload plus `prev_hash` (the first receipt links to a genesis hash of 64 zeros).

## Models (optional, unused in M1)

`configs/examples/models.yaml` is the config shape for later OpenAI-compatible local and frontier providers. Analytics works with **zero** LLM configured. Do not put API keys in YAML; if you add a provider later, point `api_key_env` at an environment variable.

## Docs

- [Design spec](docs/design-spec.md)
- [Implementation plan](docs/implementation-plan.md)

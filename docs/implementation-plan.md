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

## 5. M5 tasks (implemented)

1. MCP adapter (`packages/mesh_mcp`, `mesh mcp`): tools `list_analytics`, `run_analytic`, `get_receipt` plus optional `list_connectors` / `list_nodes`. Tools call the same policy-gated HTTP APIs as CLI/web. stdio for desktop clients; HTTP JSON at `/tools`.
2. Assist fallback chain: try main (or auxiliary) then configured fallbacks in order. Receipts record `model_provider`, `model_id`, `model_slot`, `model_fallback_used`, and `model_attempts`.
3. Optional Polars engine plugin (`plugins/engines/polars_engine`, analytic `top_products_polars`). DuckDB remains the default for ad-hoc SQL.
4. Hardening: systemd units in `deploy/systemd/`, `python -m mesh_node` / `mesh-node` / `mesh-plane` / `mesh-mcp` entrypoints, auth notes in the README. Artifact size caps stay as in M4.

**Exit:** MCP tools policy-gated; Polars example green; fallback receipts recorded; `uv run pytest` green.

## 6. M6 tasks (implemented)

1. Polish the shared static `/ui` (node + plane): Run / Result / Receipt as equal panels, sticky primary actions, `prefers-color-scheme` + theme toggle, clearer mobile / loading / error states.
2. Connectors panel (`GET /connectors` or plane `GET /nodes/{id}/connectors`) and, on the plane, recent jobs (`GET /jobs`) with deep-link to result.
3. Receipt UX: copy id, verify chain, collapsed summary + raw JSON.
4. Editable principal (default `web`) on run / assist.
5. Light SVG bar chart for previews with a label column + numeric column (`pick_bar_chart` heuristic). No chart libraries.
6. Tests: `/ui` still served; chart heuristic unit tests; existing pytest suite green. README M6 note.

**Exit:** Smoke-testable UI on node and plane; `uv run pytest` green.

## 7. M7 tasks (implemented)

1. In-app Help drawer on the shared static `/ui`: topbar Help, right-side dialog, Close / Esc / backdrop dismiss, section nav + search, `#help` / `#help=<section>` deep links.
2. Sections: Getting started, Concepts, CLI vs UI, Receipts, Plane vs node, Policy, MCP — copy aligned with shipped behavior (data on nodes, plane pointers only, propose-then-confirm, hash-chained receipts, YAML allowlists, analytics-only MCP).
3. Accessible hover+focus tooltips (`role="tooltip"` + `aria-describedby`) on every major control (theme, principal, node, run kind, analytic, SQL, propose/confirm, explain, run, connectors/jobs refresh, job links, copy/verify receipt, download, chart).
4. Tests: Help/tip HTML hooks in `tests/test_ui_help.py`; existing `/ui` serve tests still pass. README M7 note.

**Exit:** Help usable without leaving `/ui`; `uv run pytest` green.

## 8. M8 tasks (implemented)

1. CLI `mesh receipt <id> --verify-chain`: detect node vs plane from `/health` (`node_id` vs `plane_id`) and call `GET /receipts/chain` on a direct node, `GET /nodes/{id}/receipts/chain` on the plane. Regression: analytic run then `--verify-chain` exits 0 against a live node (old code 404'd on `/nodes/<node_id>/receipts/chain`).
2. GitHub Actions on `pull_request` and `push` to `main`: Python 3.12, `uv sync --group dev`, `uv run pytest`, uv cache via `astral-sh/setup-uv`.
3. `scripts/deep-smoke.sh` (executable): health, connectors list `sales`, `top_products`, GET receipt, CLI `--verify-chain`, ATTACH → HTTP 4xx, assist/nl2sql without model → `used: false`, `/ui` Help markers. `--start` boots a temp example node on an ephemeral port; optional `PLANE_URL` runs one plane→node analytic. Optional CI job (`continue-on-error`); pytest remains the required gate.
4. README + this plan: M8 notes.

**Exit:** `uv run pytest` green; serve example node → `mesh analytics run top_products` → `mesh receipt <id> --verify-chain` exits 0.

## 9. M9 tasks (implemented)

1. Playwright browser tests for the shared static `/ui` (Python `pytest-playwright`, Chromium). Tests live in `tests/ui/` and are marked `@pytest.mark.ui`. Default `uv run pytest` does not collect them; run explicitly with `uv run pytest -m ui` (or `uv run pytest tests/ui`).
2. Hermetic live node fixture: ephemeral port, temp artifact/receipt dirs, example `policy.yaml` + `data/samples` + `analytics/` — same shape as `scripts/deep-smoke.sh --start`. Tear down after the session.
3. Coverage: Help control → open drawer → “Getting started” (and Concepts) → Close and Esc dismiss; select `top_products` → Run → product rows (gadget/widget/sprocket) + receipt id / Copy receipt id enabled. Optional: focused Run control exposes `#tip-run`.
4. CI: required `pytest-ui` job installs Playwright Chromium (`--with-deps`) and runs `uv run pytest -m ui --browser chromium`. Existing pytest job stays the unit/API gate.
5. README + this plan: M9 notes. `ui.html` stays a single static file (no React).

**Exit:** `uv run pytest` green (~120+); `uv run pytest -m ui` green after `playwright install chromium`.

## 10. M10 tasks (implemented)

1. Example wiring: `configs/examples/node-with-models.yaml` sets `models_path` to `configs/examples/models.yaml`. Default `node.yaml` stays LLM-free (`models_path` commented). `models.yaml` comments document `ollama pull`, `GET {base_url}/models` / `scripts/check-models.sh`, placeholder model ids, and `policy.default_mode: local_only` so frontier fallback does not fire unless allowed.
2. Runtime UX: assist receipts already record `model_provider` / `model_id` / fallback fields when used. Errors distinguish an unreachable local endpoint (Ollama / LM Studio down) from a missing model tag (`ollama pull` / set `model:`).
3. Tests: OpenAI-compatible HTTP stub proves `/assist/nl2sql` returns proposed SQL + `used: true` and never executes; without models still `used: false`. Unit tests for example configs, error copy, and `scripts/check-models.sh`.
4. Docs: README “Optional local LLM for Propose SQL”; Help drawer one-liner; this M10 note.

**Exit:** `uv run pytest` green including stub assist tests; documented path to run against real Ollama; UI marker tests unchanged.

## 11. M11 tasks (implemented)

1. Pairing token: example YAML may keep `demo-pair-token` for localhost demos; document loudly that it must be replaced beyond localhost. Env override `MESH_PAIR_TOKEN` plus optional `pair_token_env` on plane / `plane.pair_token_env` on nodes (same hook as `dsn_env` / `api_key_env`). CLI `--token` still wins. No PKI/SSO.
2. Listen posture: default remains `127.0.0.1`. Document Tailscale/LAN `listen_host` + `plane.public_endpoint` / `plane.url`. Do not enable `0.0.0.0` by default. Comment blocks on example plane/node-a/node-b configs.
3. systemd: `deploy/systemd/mesh-node.service`, `mesh-plane.service`, `mesh-mcp.service` match shipped entrypoints (`mesh-node` / `mesh-plane` / `mesh-mcp`), `User=`/`Group=` placeholders, `WorkingDirectory`, optional `EnvironmentFile` for pair token / models (`mesh.env.example`).
4. Real data dirs: document changing `connectors.local_files.root`; sensitivity labels are advisory. `configs/examples/node-real-data.yaml.example` shows a non-sample root path and is not secret-bearing.
5. Tests: `tests/test_pair_token.py` for env/named-env/CLI override and plane register; example configs still load with demo token + localhost. pytest + UI + deep-smoke stay green with the demo token.
6. Docs: README “Production-ish on a Linux box” + this M11 note.

**Exit:** `uv run pytest` green; deep-smoke still works with demo token on localhost.

## 12. Not in M11 / v1

Federated learning, Hermes learning loop, messaging gateways, full OPA deployment, Axonis decision graph UI, mTLS/OAuth, classified packaging, or auto-deploy onto operator laptops.

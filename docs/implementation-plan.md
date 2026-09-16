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

## 12. M12 tasks (implemented)

1. Example wiring (user choice): `configs/examples/models-with-grok.yaml` + `node-with-grok.yaml` (frontier Grok as `main` / `auxiliary`, `https://api.x.ai/v1`, `api_key_env: XAI_API_KEY`, `policy.default_mode: allow_frontier`); and `models-local-then-grok.yaml` + `node-with-local-then-grok.yaml` (local Ollama placeholders, Grok in `fallback`, `allow_frontier` so fallback can fire). Default `node.yaml` stays LLM-free; `models.yaml` / `node-with-models.yaml` stay local-only (OpenRouter remains the commented alternate frontier example).
2. Assist gating: `PolicyEngine.authorize(..., llm_default_mode=)` ORs `models.policy.default_mode` with the principal `model_mode` so Grok example files can use frontier slots while `local_only` still strips frontier when neither opts in. `allow_assist: false` still denies. Client stays on OpenAI-compatible `/v1/chat/completions` (no Responses API rewrite). Missing `api_key_env` values fail closed with a clear error.
3. Tests: stub HTTP “Grok” proves `allow_frontier` + frontier main → `used: true`; `local_only` strips frontier / 403; local-then-fallback prefers local then Grok. No real API key in CI.
4. Docs / UX: README “Optional Grok (xAI)” (console key, `export XAI_API_KEY`, Premium chat ≠ API); Help drawer one-liner; `scripts/check-models.sh` sends Bearer from `XAI_API_KEY` when set; `.env.example` and `deploy/systemd/mesh.env.example` empty `XAI_API_KEY=` lines.

**Exit:** Both example paths loadable; `uv run pytest` green including stub frontier tests; Grok not required.

## 13. M13 tasks (implemented)

1. Plane-first product UI: README, Help, `scripts/two-node-demo.sh`, and `mesh demo` emphasize one URL (`http://127.0.0.1:8090/ui`). Direct node `/ui` remains for operators.
2. Node `POST /upload` (multipart) writes into the selected `local_files` connector’s `uploads/` (or configured `uploads_path` under the root). Allowed `.csv` / `.parquet` / `.json` / `.jsonl` (plus existing aliases). Default 100 MiB cap. Reject traversal / absolute paths; sanitize basename. Receipt `action=upload`.
3. Plane `POST /nodes/{id}/upload` proxies to the node; plane stores no source tables.
4. Shared `ui.html`: drop zone + Browse on the connectors panel when a node is selected; refresh connectors; status/toast with new table name(s). Help/tooltip: files upload to the selected node.
5. Tests: node upload + list connectors, plane proxy, reject extension / traversal; Playwright zone visible + small CSV happy path. pytest is the gate.

**Exit:** `uv run pytest` and `uv run pytest -m ui` green; documented manual path (plane + node → drop CSV → table → analytic/SQL).

## 14. M14 tasks (implemented)

1. Ask-first `/ui`: default Run kind is **Ask (NL)**. Question → existing `/assist/nl2sql` (propose only) or a clear registered-analytic match → show proposed SQL or analytic → **Confirm** required. Never auto-execute. **Edit SQL** optional before Confirm.
2. Analytic picker + raw SQL remain under **Advanced** and stay fully usable with zero LLM. Ask with no model and no match shows a configure-models empty state (`node-with-models.yaml`, `node-with-grok.yaml`, `node-with-local-then-grok.yaml`).
3. Clear analytic match (question contains the id as a phrase, e.g. “top products” → `top_products`) offers that analytic as the Confirm target (`/analytics/run`). Helper: `match_registered_analytic`. No new assist endpoint.
4. Thin health/models fields: `llm_kind` / `llm_label` (`none`/`Local`/`Grok`) via `llm_health_fields`. Topbar chip Local / Grok / None. Hermes-style Grok stays `https://api.x.ai/v1` + `XAI_API_KEY` (do not scrape consumer Grok chat).
5. Help **Ask** section + tooltips on Ask / Confirm / proposed SQL. Sandbox copy = policy-blocked SQL (`ATTACH`, writes, disallowed statements), not a moral label. Confirm is for trust.
6. Tests: pytest for match helper + health fields; Playwright Ask default, analytic-match Confirm, empty state, stubbed nl2sql → Confirm. `ui.html` stays a single file.

**Exit:** `uv run pytest` and `uv run pytest -m ui` green; PR against main (not merged). Manual: plane + node-with-grok (or local models) → Ask → see SQL/analytic → Confirm → preview/chart/receipt.

## 15. Not in M14 / v1

Federated learning, Hermes learning loop, messaging gateways, full OPA deployment, Axonis decision graph UI, dragging tables into a visual query canvas, uploading to the plane as a data lake, mTLS/OAuth, classified packaging, auto-deploy onto operator laptops, a full chat agent with tools beyond nl2sql/explain, or auto-run SQL.

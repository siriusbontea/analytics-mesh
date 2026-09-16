# M7 — in-UI Help drawer and accessible tooltips

**Date:** 2026-09-15  
**Status:** Implementation spec for milestone M7  
**Surface:** `packages/mesh_common/src/mesh_common/static/ui.html` (M6 single-file UI)

## Goal

Users opening `/ui` should understand how Analytics Mesh works without leaving the page. Help lives in a right-side drawer; every major control has a hover+focus tooltip. No React/Vite/SPA. Docs stay in the same static file the node and plane already serve.

## Non-negotiable product facts

Copy must match shipped behavior. Do not invent features or soften policy/security language.

- Data stays on nodes. The plane stores job metadata and pointers only — never source tables.
- Analytics work with zero LLM configured.
- NL→SQL is propose-then-confirm. `/assist/nl2sql` never executes SQL.
- Receipts are SHA-256 hash-chained on the owning node.
- YAML policy allowlists gate SQL, analytics, connectors, nodes, row/time caps, and model mode.
- MCP is analytics-only: `list_analytics`, `run_analytic`, `get_receipt` (optional `list_connectors` / `list_nodes`). No `run_query` tool.

## Help drawer

- Topbar **Help** button (`#helpBtn`) opens a right-side dialog (`#helpDrawer`) with a dimmed backdrop (`#helpBackdrop`).
- Dismiss via **Close**, **Escape**, and backdrop click.
- Accessibility: `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, `aria-expanded` on the trigger, focus moves into the drawer, Tab cycles inside, focus returns to Help on close.
- Optional search (`#helpSearch`) filters section titles + body.
- Deep links: `#help` opens Getting started; `#help=<section-id>` opens that section. Existing `#job=` links keep working.

### Sections

| id | Title | Content |
| --- | --- | --- |
| `getting-started` | Getting started | Open UI → pick analytic or SQL → run → preview/chart → download artifact → inspect receipt |
| `concepts` | Concepts | Node, connectors/tables, engines (DuckDB/Polars), registry, artifacts, receipts, principal |
| `cli-vs-ui` | CLI vs UI | Same APIs; UI is thin; short `uv run mesh …` examples |
| `receipts` | Receipts | Hash chain, verify-chain, what is/isn’t recorded (no source tables on the plane) |
| `plane-vs-node` | Plane vs node | Direct node vs plane + node picker; jobs list; `#job=` |
| `policy` | Policy | YAML allowlists, caps, sensitivity labels, propose-then-confirm assist |
| `mcp` | MCP | Analytics-only tools |

## Tooltips

Shared pattern: control (and/or a `?` trigger) uses `aria-describedby` pointing at a `role="tooltip"` popover. Visible on hover and keyboard focus — not `title=` alone.

Required tip ids: `tip-theme`, `tip-principal`, `tip-node`, `tip-kind`, `tip-analytic`, `tip-sql`, `tip-propose`, `tip-confirm`, `tip-explain`, `tip-run`, `tip-connectors-refresh`, `tip-jobs-refresh`, `tip-jobs`, `tip-copy-receipt`, `tip-verify-chain`, `tip-download`, `tip-chart`.

Each tip is 1–2 sentences: what it is, and what happens when used.

## Tests and docs

- HTML-string assertions so Help/tip hooks cannot vanish silently (`tests/test_ui_help.py`).
- README + `docs/implementation-plan.md` record M7 the same way M6 was recorded.

## Out of scope

New APIs, a docs site, a separate SPA, weakening policy/MCP messaging, or changing Run / Result / Receipt / Connectors / Jobs / theme behavior.

#!/usr/bin/env bash
# Two-node Analytics Mesh demo on localhost.
# Product UI is the plane (one URL). Nodes register; you pick a node in /ui.
# Direct node /ui remains for operators. Same path as `uv run mesh demo`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required: https://docs.astral.sh/uv/" >&2
  exit 1
fi

uv sync --group dev

PLANE_URL="${PLANE_URL:-http://127.0.0.1:8090}"
NODE_A_URL="${NODE_A_URL:-http://127.0.0.1:8081}"
NODE_B_URL="${NODE_B_URL:-http://127.0.0.1:8082}"

wait_for() {
  local url=$1
  local i
  for i in $(seq 1 50); do
    if uv run python -c "import httpx,sys; r=httpx.get(sys.argv[1], timeout=1.0); sys.exit(0 if r.status_code < 500 else 1)" "$url" 2>/dev/null; then
      return 0
    fi
    sleep 0.2
  done
  echo "timed out waiting for $url" >&2
  return 1
}

cleanup() {
  local pid
  for pid in "${PIDS[@]:-}"; do
    if [[ -n "${pid}" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
}
PIDS=()
trap cleanup EXIT

echo "starting plane on ${PLANE_URL}"
uv run mesh plane --config configs/examples/plane.yaml &
PIDS+=($!)
wait_for "${PLANE_URL}/health"

echo "starting node-a on ${NODE_A_URL}"
uv run mesh serve --config configs/examples/node-a.yaml &
PIDS+=($!)
echo "starting node-b on ${NODE_B_URL}"
uv run mesh serve --config configs/examples/node-b.yaml &
PIDS+=($!)
wait_for "${NODE_A_URL}/health"
wait_for "${NODE_B_URL}/health"

# Nodes register on start; pair again in case the plane came up first but a node retried.
# Honor MESH_PAIR_TOKEN when set (same override the plane/node use); else demo token.
PAIR_TOKEN="${MESH_PAIR_TOKEN:-demo-pair-token}"
uv run mesh pair --config configs/examples/node-a.yaml --url "$PLANE_URL" --token "$PAIR_TOKEN" --endpoint "$NODE_A_URL" >/dev/null
uv run mesh pair --config configs/examples/node-b.yaml --url "$PLANE_URL" --token "$PAIR_TOKEN" --endpoint "$NODE_B_URL" >/dev/null

echo
echo "registered nodes:"
uv run mesh nodes --url "$PLANE_URL"

echo
echo "registered analytics on Node B:"
uv run mesh analytics list --url "$PLANE_URL" --node node-b

echo
echo "run analytic top_products on Node B via the plane:"
uv run mesh analytics run top_products --url "$PLANE_URL" --node node-b

echo
echo "query Node B via the plane (source data stays on B):"
uv run mesh query --url "$PLANE_URL" --node node-b --sql \
  "SELECT product, SUM(amount) AS total FROM sales GROUP BY product ORDER BY total DESC"

echo
echo "job metadata on the plane (no source tables):"
uv run mesh jobs --url "$PLANE_URL"

echo
echo "============================================================"
echo "  Product UI (one URL):  ${PLANE_URL}/ui"
echo "  Pick a node, drop a CSV/Parquet/JSON, run an analytic or SQL."
echo "  Files upload to the selected node — the plane stores no tables."
echo "  Operator / debug UI:   ${NODE_A_URL}/ui  or  ${NODE_B_URL}/ui"
echo "============================================================"
echo
echo "Demo processes are still running. Ctrl-C to stop."
echo "More commands:"
echo "  uv run mesh nodes --url $PLANE_URL"
echo "  uv run mesh query --url $PLANE_URL --node node-b --sql 'SELECT product FROM sales'"
echo "  uv run mesh analytics run top_products --url $PLANE_URL --node node-b"
echo "  uv run mesh receipt <receipt_id> --url $PLANE_URL --verify-chain"
wait

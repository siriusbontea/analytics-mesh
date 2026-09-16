#!/usr/bin/env bash
# Deep smoke for Analytics Mesh — more than /health.
#
# After `mesh serve` (default http://127.0.0.1:8080):
#   ./scripts/deep-smoke.sh
#
# Hermetic / CI (starts a temp node from example config on an ephemeral port):
#   ./scripts/deep-smoke.sh --start
#
# Env:
#   BASE_URL / MESH_URL   already-running node (default http://127.0.0.1:8080)
#   PLANE_URL             optional; if set, run one plane→node analytic
#   MESH_NODE             node id for the optional plane check (default: first registered)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
  echo "FAIL uv is required: https://docs.astral.sh/uv/" >&2
  exit 1
fi

START=0
if [[ "${1:-}" == "--start" ]]; then
  START=1
fi

BASE_URL="${BASE_URL:-${MESH_URL:-http://127.0.0.1:8080}}"
PIDS=()
TMP_DIR=""

cleanup() {
  local pid
  for pid in "${PIDS[@]:-}"; do
    if [[ -n "${pid}" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  if [[ -n "${TMP_DIR}" && -d "${TMP_DIR}" ]]; then
    rm -rf "${TMP_DIR}"
  fi
}
trap cleanup EXIT

ok() { echo "OK  $*"; }
fail() { echo "FAIL $*"; exit 1; }

wait_for() {
  local url=$1
  local i
  for i in $(seq 1 150); do
    if uv run python -c "import httpx,sys; r=httpx.get(sys.argv[1], timeout=1.0); sys.exit(0 if r.status_code < 500 else 1)" "$url" 2>/dev/null; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

http_json() {
  uv run python - "$@" <<'PY'
import json, sys
import httpx

method, url = sys.argv[1], sys.argv[2]
kwargs = {"timeout": 30.0}
if len(sys.argv) > 3 and sys.argv[3]:
    kwargs["json"] = json.loads(sys.argv[3])
response = httpx.request(method, url, **kwargs)
sys.stdout.write(response.text)
if not response.text.endswith("\n"):
    sys.stdout.write("\n")
raise SystemExit(0 if response.status_code < 400 else response.status_code)
PY
}

http_code() {
  uv run python - "$@" <<'PY'
import json, sys
import httpx

method, url = sys.argv[1], sys.argv[2]
kwargs = {"timeout": 30.0}
if len(sys.argv) > 3 and sys.argv[3]:
    kwargs["json"] = json.loads(sys.argv[3])
response = httpx.request(method, url, **kwargs)
print(response.status_code)
raise SystemExit(0)
PY
}

if [[ "$START" -eq 1 ]]; then
  TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mesh-deep-smoke.XXXXXX")"
  PORT="$(uv run python -c "import socket; s=socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1]); s.close()")"
  cat > "$TMP_DIR/node.yaml" <<YAML
node_id: smoke-node
artifact_dir: ${TMP_DIR}/artifacts
receipt_db: ${TMP_DIR}/receipts.sqlite
identity_key_path: ${TMP_DIR}/identity.pem
listen_host: 127.0.0.1
listen_port: ${PORT}
connectors:
  - id: local_files
    type: local_files
    root: data/samples
    labels: [personal]
analytics_dir: analytics
policy_path: configs/examples/policy.yaml
limits:
  default_row_limit: 10000
  max_row_limit: 100000
  query_timeout_seconds: 30
YAML
  BASE_URL="http://127.0.0.1:${PORT}"
  echo "starting temp node on ${BASE_URL}"
  uv run mesh serve --config "$TMP_DIR/node.yaml" >"$TMP_DIR/serve.log" 2>&1 &
  PIDS+=($!)
  if ! wait_for "${BASE_URL}/health"; then
    if [[ -f "$TMP_DIR/serve.log" ]]; then
      echo "---- serve.log ----" >&2
      cat "$TMP_DIR/serve.log" >&2
    fi
    fail "temp node did not become healthy at ${BASE_URL}/health"
  fi
  ok "started temp node ${BASE_URL}"
else
  if ! wait_for "${BASE_URL}/health"; then
    fail "nothing healthy at ${BASE_URL}/health — run \`mesh serve\` or pass --start"
  fi
fi

health="$(http_json GET "${BASE_URL}/health")" || fail "GET /health"
echo "$health" | uv run python -c "import json,sys; b=json.load(sys.stdin); assert b.get('status')=='ok'" \
  || fail "GET /health status is not ok"
ok "GET /health"

connectors="$(http_json GET "${BASE_URL}/connectors")" || fail "GET /connectors"
echo "$connectors" | uv run python -c "
import json, sys
body = json.load(sys.stdin)
tables = {t.get('name') for c in body.get('connectors', []) for t in c.get('tables', [])}
assert 'sales' in tables, tables
" || fail "GET /connectors does not list table sales"
ok "GET /connectors lists sales"

run_out="$(uv run mesh analytics run top_products --url "$BASE_URL")" \
  || fail "mesh analytics run top_products"
receipt_id="$(printf '%s\n' "$run_out" | uv run python -c "import json,sys; print(json.load(sys.stdin)['receipt']['receipt_id'])")" \
  || fail "parse receipt_id from analytics run"
[[ -n "$receipt_id" ]] || fail "analytics run returned empty receipt_id"
ok "mesh analytics run top_products (receipt ${receipt_id})"

got_receipt="$(http_json GET "${BASE_URL}/receipts/${receipt_id}")" || fail "GET /receipts/${receipt_id}"
echo "$got_receipt" | uv run python -c "
import json, sys
body = json.load(sys.stdin)
assert body.get('receipt_id')
assert body.get('status') == 'succeeded'
" || fail "GET /receipts/{id} body"
ok "GET /receipts/${receipt_id}"

verify_out="$(uv run mesh receipt "$receipt_id" --url "$BASE_URL" --verify-chain)" \
  || fail "mesh receipt --verify-chain"
printf '%s\n' "$verify_out" | uv run python -c "
import json, sys
decoder = json.JSONDecoder()
text = sys.stdin.read().lstrip()
docs = []
idx = 0
while idx < len(text):
    while idx < len(text) and text[idx].isspace():
        idx += 1
    if idx >= len(text):
        break
    doc, idx = decoder.raw_decode(text, idx)
    docs.append(doc)
assert docs, 'no JSON from mesh receipt --verify-chain'
assert docs[-1].get('valid') is True, docs[-1]
" || fail "mesh receipt --verify-chain did not report valid:true"
ok "mesh receipt --verify-chain"

attach_code="$(http_code POST "${BASE_URL}/query" '{"sql":"ATTACH DATABASE foo","principal":"local"}')"
if [[ "$attach_code" =~ ^4 ]]; then
  ok "policy/sandbox rejects ATTACH (HTTP ${attach_code})"
else
  fail "ATTACH expected HTTP 4xx, got ${attach_code}"
fi

assist="$(http_json POST "${BASE_URL}/assist/nl2sql" '{"question":"which product sold the most?","principal":"local"}')" \
  || fail "POST /assist/nl2sql"
echo "$assist" | uv run python -c "
import json, sys
body = json.load(sys.stdin)
assert body.get('used') is False, body
message = (body.get('message') or '').lower()
assert 'model' in message or 'configured' in message, body
" || fail "assist/nl2sql without model should return used:false and a clear message"
ok "POST /assist/nl2sql without model (used:false)"

ui="$(uv run python -c "import httpx,sys; r=httpx.get(sys.argv[1], timeout=10.0); sys.stdout.write(r.text); sys.exit(0 if r.status_code < 400 else 1)" "${BASE_URL}/ui")" \
  || fail "GET /ui"
printf '%s' "$ui" | uv run python -c "
import sys
html = sys.stdin.read()
low = html.lower()
assert 'id=\"helpDrawer\"' in html or \"id='helpDrawer'\" in html, 'missing help drawer'
assert 'getting started' in low, 'missing Getting started'
assert 'id=\"uploadZone\"' in html or \"id='uploadZone'\" in html, 'missing upload zone'
" || fail "GET /ui missing Help drawer / Getting started / upload markers"
ok "GET /ui contains Help drawer / Getting started / upload zone"

if [[ -n "${PLANE_URL:-}" ]]; then
  plane_health="$(http_json GET "${PLANE_URL}/health")" || fail "GET ${PLANE_URL}/health"
  echo "$plane_health" | uv run python -c "import json,sys; b=json.load(sys.stdin); assert b.get('plane_id')" \
    || fail "PLANE_URL /health has no plane_id"
  node_id="${MESH_NODE:-}"
  if [[ -z "$node_id" ]]; then
    node_id="$(http_json GET "${PLANE_URL}/nodes" | uv run python -c "import json,sys; nodes=json.load(sys.stdin).get('nodes') or []; assert nodes, 'no registered nodes'; print(nodes[0]['node_id'])")" \
      || fail "plane has no registered nodes (set MESH_NODE)"
  fi
  plane_run="$(uv run mesh analytics run top_products --url "$PLANE_URL" --node "$node_id")" \
    || fail "plane→node mesh analytics run top_products --node ${node_id}"
  printf '%s\n' "$plane_run" | uv run python -c "import json,sys; b=json.load(sys.stdin); assert b.get('receipt',{}).get('status')=='succeeded'" \
    || fail "plane→node analytic receipt was not succeeded"
  ok "plane→node analytic top_products via ${PLANE_URL} node=${node_id}"
fi

echo "OK  deep-smoke complete (${BASE_URL})"

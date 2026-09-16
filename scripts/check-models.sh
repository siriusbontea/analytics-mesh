#!/usr/bin/env bash
# Probe an OpenAI-compatible GET {base_url}/models (Ollama / LM Studio / vLLM / xAI).
#
# Usage:
#   ./scripts/check-models.sh
#   ./scripts/check-models.sh http://127.0.0.1:11434/v1
#   MESH_MODELS_URL=http://127.0.0.1:1234/v1 ./scripts/check-models.sh
#   ./scripts/check-models.sh https://api.x.ai/v1
#   XAI_API_KEY=... ./scripts/check-models.sh https://api.x.ai/v1
#
# When XAI_API_KEY is set, the request sends Authorization: Bearer $XAI_API_KEY
# (needed for https://api.x.ai/v1). Equivalent curl:
#   curl -sS -H "Authorization: Bearer $XAI_API_KEY" https://api.x.ai/v1/models
#
# Exits 0 and prints the JSON (plus parsed ids) when the endpoint answers.
# Exits non-zero with a short hint when the server is down or HTTP fails.

set -euo pipefail

BASE_URL="${1:-${MESH_MODELS_URL:-http://127.0.0.1:11434/v1}}"
BASE_URL="${BASE_URL%/}"
URL="${BASE_URL}/models"

if ! command -v curl >/dev/null 2>&1; then
  echo "FAIL curl is required to probe ${URL}" >&2
  exit 1
fi

CURL_ARGS=(-sS --fail --connect-timeout 2 --max-time 8)
if [ -n "${XAI_API_KEY:-}" ]; then
  CURL_ARGS+=(-H "Authorization: Bearer ${XAI_API_KEY}")
fi

if ! body=$(curl "${CURL_ARGS[@]}" "${URL}" 2>&1); then
  echo "FAIL cannot reach ${URL}" >&2
  if [[ "${BASE_URL}" == *"://127.0.0.1"* || "${BASE_URL}" == *"://localhost"* ]]; then
    echo "Start Ollama (\`ollama serve\`) or LM Studio's local server, then retry." >&2
    echo "After a pull, set model: in configs/examples/models.yaml to a tag from GET ${URL}." >&2
  else
    echo "For xAI, export XAI_API_KEY and retry, or:" >&2
    echo "  curl -sS -H \"Authorization: Bearer \$XAI_API_KEY\" ${URL}" >&2
  fi
  exit 1
fi

printf '%s\n' "${body}"
if command -v python3 >/dev/null 2>&1; then
  python3 -c '
import json, sys
try:
    payload = json.loads(sys.argv[1])
except Exception:
    raise SystemExit(0)
ids = [item.get("id") for item in payload.get("data", []) if isinstance(item, dict) and item.get("id")]
if ids:
    print("models:", ", ".join(ids))
else:
    print("No model ids in response. Pull a model (ollama pull <tag>) or confirm the API key can list models.")
' "${body}"
fi

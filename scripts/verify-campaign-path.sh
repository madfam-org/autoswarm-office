#!/usr/bin/env bash
# Verify campaign orchestration routes are mounted and auth-gated (Phase 2).
#
# Usage:
#   ./scripts/verify-campaign-path.sh
#   ./scripts/verify-campaign-path.sh --staging
#
# Exit 0 when all applicable checks pass.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BASE_URL="${BASE_URL:-http://localhost:4300}"
MODE="${1:-local}"
FAILURES=()

pass() { echo "OK: $*"; }
fail() { echo "FAIL: $*"; FAILURES+=("$*"); }

echo "== Campaign path verification (mode=$MODE) =="

if [[ "$MODE" == "--staging" ]]; then
  BASE_URL="${STAGING_API_URL:-https://staging-api.selva.town}"
fi

OPENAPI_JSON="$(curl -sS "${BASE_URL}/api/v1/openapi.json" 2>/dev/null || true)"
if [[ -z "$OPENAPI_JSON" ]]; then
  fail "could not fetch ${BASE_URL}/api/v1/openapi.json"
else
  pass "fetched OpenAPI from ${BASE_URL}"
fi

require_openapi_path() {
  local path="$1"
  if [[ -z "$OPENAPI_JSON" ]]; then
    return
  fi
  if python3 -c "
import json, sys
paths = json.loads(sys.argv[1]).get('paths', {})
target = sys.argv[2]
# FastAPI may register with or without trailing slash.
ok = target in paths or (target.rstrip('/') + '/') in paths or target.rstrip('/') in paths
sys.exit(0 if ok else 1)
" "$OPENAPI_JSON" "$path"; then
    pass "OpenAPI lists ${path}"
  elif [[ "$MODE" == "--staging" ]]; then
    fail "${path} missing from staging OpenAPI — nexus-api image may not have synced yet"
  else
    fail "${path} missing from OpenAPI — route not mounted"
  fi
}

expect_get_auth_gate() {
  local path="$1"
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' \
    -X GET "${BASE_URL}${path}" \
    -H 'Authorization: Bearer invalid-token' 2>/dev/null || true)"
  if [[ "$code" == "401" || "$code" == "403" ]]; then
    pass "${path} GET requires auth (${code})"
  elif [[ "$code" == "404" ]]; then
    if [[ "$MODE" == "--staging" ]]; then
      fail "${path} GET returned 404 — route not mounted on staging"
    else
      fail "${path} GET returned 404 — route not mounted"
    fi
  else
    fail "${path} GET expected 401/403 with invalid bearer, got ${code}"
  fi
}

# POST-only campaign routes — OpenAPI is the source of truth (bare POST returns CSRF 403
# even when the path does not exist).
require_openapi_path /api/v1/campaigns/import-tulana-pack
require_openapi_path /api/v1/campaigns/crm-handoff
require_openapi_path /api/v1/campaigns/schedule-social
require_openapi_path /api/v1/campaigns/tulana-feedback
require_openapi_path /api/v1/schedules/
require_openapi_path /api/v1/scheduled-actions/

# GET list endpoints must be auth-gated (Bearer bypasses CSRF).
expect_get_auth_gate /api/v1/scheduled-actions/

if [[ ${#FAILURES[@]} -gt 0 ]]; then
  echo ""
  echo "Campaign path verification failed:"
  for item in "${FAILURES[@]}"; do
    echo "  - $item"
  done
  exit 1
fi

echo ""
echo "Campaign path verification passed."

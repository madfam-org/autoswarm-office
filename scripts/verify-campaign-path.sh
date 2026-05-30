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

expect_auth_gate() {
  local method="$1"
  local path="$2"
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' \
    -X "$method" "${BASE_URL}${path}" \
    -H 'Content-Type: application/json' \
    --data '{}' 2>/dev/null || true)"
  if [[ "$code" == "401" || "$code" == "403" ]]; then
    pass "${path} requires auth (${code})"
  elif [[ "$code" == "404" ]]; then
    if [[ "$MODE" == "--staging" ]]; then
      echo "SKIP: ${path} returned 404 — staging nexus-api may not have deployed this route yet"
    else
      fail "${path} returned 404 — route not mounted"
    fi
  else
    fail "${path} expected 401/403 without auth, got ${code}"
  fi
}

expect_auth_gate POST /api/v1/campaigns/import-tulana-pack
expect_auth_gate POST /api/v1/campaigns/crm-handoff
expect_auth_gate POST /api/v1/campaigns/schedule-social
expect_auth_gate POST /api/v1/campaigns/tulana-feedback
expect_auth_gate GET /api/v1/scheduled-actions
expect_auth_gate POST /api/v1/schedules/

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

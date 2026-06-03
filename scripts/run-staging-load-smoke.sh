#!/usr/bin/env bash
# Run short k6 dispatch smoke against staging (ROI Tier 3 item 5 precursor).
#
# Uses WORKER_API_TOKEN + X-Selva-Tenant-Org when no Janua JWT is set.
#
# Usage:
#   ./scripts/run-staging-load-smoke.sh
#   AUTH_TOKEN=<jwt> ./scripts/run-staging-load-smoke.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${STAGING_API_URL:-https://staging-api.selva.town}"
TOKEN="${AUTH_TOKEN:-${STAGING_LOAD_TEST_TOKEN:-${STAGING_CAMPAIGN_TEST_TOKEN:-}}}"
TENANT_ORG="${STAGING_TENANT_ORG:-madfam}"

if [[ -z "$TOKEN" ]] && command -v kubectl >/dev/null 2>&1; then
  TOKEN="$(kubectl -n selva-staging get secret selva-staging-secrets \
    -o jsonpath='{.data.WORKER_API_TOKEN}' 2>/dev/null | base64 -d || true)"
  if [[ -n "$TOKEN" ]]; then
    echo "Using WORKER_API_TOKEN from selva-staging-secrets (org=${TENANT_ORG})"
  fi
fi

if [[ -z "$TOKEN" ]]; then
  echo "SKIP: set AUTH_TOKEN or ensure kubectl can read WORKER_API_TOKEN"
  exit 0
fi

if ! command -v k6 >/dev/null 2>&1; then
  echo "FAIL: k6 not installed — brew install k6 or use .github/workflows/load-test.yml"
  exit 1
fi

exec k6 run \
  -e "BASE_URL=${BASE_URL}" \
  -e "AUTH_TOKEN=${TOKEN}" \
  -e "TENANT_ORG=${TENANT_ORG}" \
  "${ROOT}/tests/load/staging-dispatch-smoke.js"

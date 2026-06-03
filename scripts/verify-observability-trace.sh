#!/usr/bin/env bash
# Verify observability wiring on staging (Tier 1 gate helper).
#
# When OTEL/SENTRY secrets exist, confirms secret presence + optional dispatch probe.
# Does NOT create credentials — use bootstrap-staging-observability.sh first.
#
# Usage:
#   ./scripts/verify-observability-trace.sh
#   ./scripts/verify-observability-trace.sh --require-trace
#
set -euo pipefail

NS="${STAGING_NAMESPACE:-selva-staging}"
REQUIRE_TRACE=false

for arg in "$@"; do
  case "$arg" in
    --require-trace) REQUIRE_TRACE=true ;;
  esac
done

echo "== Observability trace verification (namespace=${NS}) =="

./scripts/verify-staging-observability.sh --require-secret 2>/dev/null || {
  ./scripts/verify-staging-observability.sh
  exit 0
}

TOKEN=""
if command -v kubectl >/dev/null 2>&1; then
  TOKEN="$(kubectl -n "$NS" get secret selva-staging-secrets \
    -o jsonpath='{.data.WORKER_API_TOKEN}' 2>/dev/null | base64 -d || true)"
fi

if [[ -z "$TOKEN" ]]; then
  echo "SKIP: no worker token for dispatch probe"
  exit 0
fi

BASE_URL="${STAGING_API_URL:-https://staging-api.selva.town}"
CODE="$(curl -s -o /tmp/obs-probe.json -w "%{http_code}" -X POST \
  "${BASE_URL}/api/v1/swarms/dispatch" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Selva-Tenant-Org: madfam" \
  -H "Content-Type: application/json" \
  -d '{"description":"obs-trace-probe","graph_type":"calibration","payload":{"probe":true}}')"

if [[ "$CODE" != "201" && "$CODE" != "200" ]]; then
  echo "WARN: dispatch probe returned ${CODE} (calibration graph may need worker deploy)"
  $REQUIRE_TRACE && exit 1
  exit 0
fi

echo "OK: dispatch probe ${CODE} — check Grafana Tempo for trace within 2 min"
if $REQUIRE_TRACE; then
  echo "FAIL: automated Tempo lookup not implemented — verify manually in Grafana Cloud"
  exit 1
fi

echo "OK   observability secret present; manual trace confirmation pending"

#!/usr/bin/env bash
# Verify Sentry capture wiring via nexus-api sentry-probe (Wave 1 gate).
#
# Requires WORKER_API_TOKEN (or STAGING_WORKER_API_TOKEN) and a deployed
# nexus-api with SENTRY_DSN set from selva-observability-secrets.
#
# Usage:
#   ./scripts/verify-sentry-capture.sh --staging
#   ./scripts/verify-sentry-capture.sh --prod
#   ./scripts/verify-sentry-capture.sh --staging --require-capture
#
set -euo pipefail

REQUIRE=false
BASE_URL="${STAGING_API_URL:-https://staging-api.selva.town}"
TOKEN="${STAGING_WORKER_API_TOKEN:-${WORKER_API_TOKEN:-}}"

for arg in "$@"; do
  case "$arg" in
    --staging) BASE_URL="${STAGING_API_URL:-https://staging-api.selva.town}" ;;
    --prod) BASE_URL="${PROD_API_URL:-https://api.selva.town}" ;;
    --require-capture) REQUIRE=true ;;
  esac
done

echo "== Sentry capture verification (${BASE_URL}) =="

if [[ -z "$TOKEN" ]]; then
  echo "SKIP: set STAGING_WORKER_API_TOKEN or WORKER_API_TOKEN"
  $REQUIRE && exit 1
  exit 0
fi

BODY="$(mktemp -t selva-sentry-probe.XXXXXX)"
trap 'rm -f "$BODY"' EXIT

CODE="$(curl -sS -o "$BODY" -w "%{http_code}" -X POST \
  "${BASE_URL}/api/v1/health/sentry-probe" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json")"

if [[ "$CODE" == "503" ]]; then
  detail="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("detail",""))' "$BODY" 2>/dev/null || true)"
  if [[ "$detail" == "sentry_not_configured" ]]; then
    echo "SKIP: SENTRY_DSN not configured on nexus-api — bootstrap observability secret first"
    $REQUIRE && exit 1
    exit 0
  fi
fi

if [[ "$CODE" != "200" ]]; then
  echo "FAIL: sentry-probe returned HTTP ${CODE}"
  cat "$BODY"
  exit 1
fi

if grep -q '"captured":true' "$BODY" || grep -q '"captured": true' "$BODY"; then
  event_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("event_id",""))' "$BODY")"
  echo "OK: Sentry probe captured event_id=${event_id:-unknown}"
  echo "     Confirm issue 'selva sentry-probe' in Sentry nexus-api project within 60s"
  exit 0
fi

echo "FAIL: unexpected sentry-probe body:"
cat "$BODY"
exit 1

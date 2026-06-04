#!/usr/bin/env bash
# Verify observability wiring on staging (Tier 1 gate helper).
#
# When OTEL/SENTRY secrets exist, confirms secret presence + dispatches a probe
# with a known W3C trace ID. If a read-only Tempo/Grafana query endpoint is
# provided, it polls for that exact trace.
# Does NOT create credentials — use bootstrap-staging-observability.sh first.
#
# Usage:
#   ./scripts/verify-observability-trace.sh
#   ./scripts/verify-observability-trace.sh --require-trace
#   TEMPO_QUERY_URL=https://tempo.example.com ./scripts/verify-observability-trace.sh --require-trace
#   GRAFANA_URL=https://<stack>.grafana.net GRAFANA_TEMPO_DATASOURCE_UID=<uid> \
#     GRAFANA_API_TOKEN=<read-only-token> ./scripts/verify-observability-trace.sh --require-trace
#
set -euo pipefail

NS="${STAGING_NAMESPACE:-selva-staging}"
SECRET="${STAGING_SECRET:-selva-staging-secrets}"
BASE_URL="${STAGING_API_URL:-https://staging-api.selva.town}"
TENANT_ORG="${TRACE_PROBE_TENANT_ORG:-madfam}"
TRACE_QUERY_TIMEOUT_SECONDS="${TRACE_QUERY_TIMEOUT_SECONDS:-180}"
TRACE_QUERY_POLL_SECONDS="${TRACE_QUERY_POLL_SECONDS:-10}"
REQUIRE_TRACE=false

for arg in "$@"; do
  case "$arg" in
    --require-trace) REQUIRE_TRACE=true ;;
    --help|-h)
      awk 'NR > 1 { if ($0 !~ /^#/) exit; sub(/^# ?/, ""); print }' "$0"
      exit 0
      ;;
    *)
      echo "FAIL: unknown argument: $arg"
      exit 2
      ;;
  esac
done

echo "== Observability trace verification (namespace=${NS}) =="

./scripts/verify-staging-observability.sh --require-secret 2>/dev/null || {
  ./scripts/verify-staging-observability.sh
  exit 0
}

TOKEN=""
if command -v kubectl >/dev/null 2>&1; then
  TOKEN="$(kubectl -n "$NS" get secret "$SECRET" \
    -o jsonpath='{.data.WORKER_API_TOKEN}' 2>/dev/null | base64 -d || true)"
fi

if [[ -z "$TOKEN" ]]; then
  echo "SKIP: no worker token for dispatch probe"
  exit 0
fi

TRACE_ID="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(16))
PY
)"
SPAN_ID="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(8))
PY
)"
TRACEPARENT="00-${TRACE_ID}-${SPAN_ID}-01"
PROBE_BODY="$(mktemp -t selva-obs-probe.XXXXXX)"
TRACE_BODY="$(mktemp -t selva-trace-query.XXXXXX)"
trap 'rm -f "$PROBE_BODY" "$TRACE_BODY"' EXIT

START_EPOCH="$(($(date +%s) - 300))"
CODE="$(curl -sS -o "$PROBE_BODY" -w "%{http_code}" -X POST \
  "${BASE_URL}/api/v1/swarms/dispatch" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Selva-Tenant-Org: ${TENANT_ORG}" \
  -H "X-Request-ID: obs-trace-probe-${TRACE_ID}" \
  -H "Idempotency-Key: obs-trace-probe-${TRACE_ID}" \
  -H "traceparent: ${TRACEPARENT}" \
  -H "Content-Type: application/json" \
  -d '{"description":"obs-trace-probe","graph_type":"calibration","payload":{"probe":true}}')"

if [[ "$CODE" != "201" && "$CODE" != "200" ]]; then
  echo "WARN: dispatch probe returned ${CODE} (calibration graph may need worker deploy)"
  echo "TRACE_ID: ${TRACE_ID}"
  $REQUIRE_TRACE && exit 1
  exit 0
fi

echo "OK: dispatch probe ${CODE}"
echo "TRACE_ID: ${TRACE_ID}"

TEMPO_QUERY_URL="${TEMPO_QUERY_URL:-}" # Base URL before /api, e.g. https://tempo.example.com
TEMPO_AUTH_ARGS=()

if [[ -z "$TEMPO_QUERY_URL" && -n "${GRAFANA_URL:-}" && -n "${GRAFANA_TEMPO_DATASOURCE_UID:-}" ]]; then
  TEMPO_QUERY_URL="${GRAFANA_URL%/}/api/datasources/proxy/uid/${GRAFANA_TEMPO_DATASOURCE_UID}"
fi

if [[ -n "${TEMPO_QUERY_AUTH_HEADER:-}" ]]; then
  TEMPO_AUTH_ARGS=(-H "${TEMPO_QUERY_AUTH_HEADER}")
elif [[ -n "${GRAFANA_API_TOKEN:-}" ]]; then
  TEMPO_AUTH_ARGS=(-H "Authorization: Bearer ${GRAFANA_API_TOKEN}")
elif [[ -n "${TEMPO_USERNAME:-}" && -n "${TEMPO_API_KEY:-}" ]]; then
  TEMPO_AUTH_ARGS=(-u "${TEMPO_USERNAME}:${TEMPO_API_KEY}")
fi

if [[ -z "$TEMPO_QUERY_URL" ]]; then
  echo "SKIP: no TEMPO_QUERY_URL or GRAFANA_URL+GRAFANA_TEMPO_DATASOURCE_UID; verify TRACE_ID manually in Grafana Tempo"
  if $REQUIRE_TRACE; then
    echo "FAIL: --require-trace needs a read-only Tempo/Grafana query endpoint"
    exit 1
  fi
  echo "OK   observability secret present; manual trace confirmation pending"
  exit 0
fi

END_AT="$(($(date +%s) + TRACE_QUERY_TIMEOUT_SECONDS))"
QUERY_BASE="${TEMPO_QUERY_URL%/}/api/traces/${TRACE_ID}"

echo "Polling Tempo query API for trace (timeout=${TRACE_QUERY_TIMEOUT_SECONDS}s)"
while (( $(date +%s) <= END_AT )); do
  END_EPOCH="$(($(date +%s) + 300))"
  HTTP_CODE="$(curl -sS -o "$TRACE_BODY" -w "%{http_code}" -G \
    "${QUERY_BASE}" \
    "${TEMPO_AUTH_ARGS[@]}" \
    --data-urlencode "start=${START_EPOCH}" \
    --data-urlencode "end=${END_EPOCH}" || true)"

  if [[ "$HTTP_CODE" == "200" ]] && grep -qi "$TRACE_ID" "$TRACE_BODY"; then
    echo "OK: trace ${TRACE_ID} found in Tempo"
    exit 0
  fi

  sleep "$TRACE_QUERY_POLL_SECONDS"
done

if $REQUIRE_TRACE; then
  echo "FAIL: trace ${TRACE_ID} not found in Tempo within ${TRACE_QUERY_TIMEOUT_SECONDS}s"
  exit 1
fi

echo "WARN: trace ${TRACE_ID} not found automatically; verify manually in Grafana Tempo"

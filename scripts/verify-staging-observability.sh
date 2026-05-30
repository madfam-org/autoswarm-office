#!/usr/bin/env bash
# Verify staging observability secret wiring (Phase 0 Tier 1 operator gate).
#
# Checks that autoswarm-observability-secrets exists in autoswarm-staging and
# nexus-api picked up OTel/Sentry env vars. Secret values are never printed.
#
# Usage:
#   ./scripts/verify-staging-observability.sh
#   ./scripts/verify-staging-observability.sh --require-secret   # fail if missing
#
set -euo pipefail

REQUIRE=false
for arg in "$@"; do
  case "$arg" in
    --require-secret) REQUIRE=true ;;
  esac
done

NS="${STAGING_NAMESPACE:-autoswarm-staging}"
SECRET="${OBSERVABILITY_SECRET:-autoswarm-observability-secrets}"
FAILURES=()

pass() { echo "OK: $*"; }
fail() { echo "FAIL: $*"; FAILURES+=("$*"); }
skip() { echo "SKIP: $*"; }

echo "== Staging observability verification (namespace=${NS}) =="

if ! command -v kubectl >/dev/null 2>&1; then
  skip "kubectl unavailable — cluster checks not run"
  exit 0
fi

if kubectl -n "$NS" get secret "$SECRET" >/dev/null 2>&1; then
  pass "secret ${SECRET} exists"
else
  if $REQUIRE; then
    fail "secret ${SECRET} missing — create per infra/k8s/production/observability-secrets-template.yaml"
  else
    skip "secret ${SECRET} missing — OTel/Sentry no-op until operator provisions (Tier 1 backlog)"
    exit 0
  fi
fi

POD=$(kubectl -n "$NS" get pod -l app.kubernetes.io/name=nexus-api \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
if [[ -z "$POD" ]]; then
  fail "no nexus-api pod in ${NS}"
else
  pass "nexus-api pod ${POD}"
fi

otel="$(kubectl -n "$NS" exec "$POD" -- printenv OTEL_EXPORTER_OTLP_ENDPOINT 2>/dev/null || true)"
if [[ -n "$otel" ]]; then
  pass "OTEL_EXPORTER_OTLP_ENDPOINT set on nexus-api"
else
  fail "OTEL_EXPORTER_OTLP_ENDPOINT empty on nexus-api — restart deploy after secret create"
fi

sentry="$(kubectl -n "$NS" exec "$POD" -- printenv SENTRY_DSN 2>/dev/null || true)"
if [[ -n "$sentry" ]]; then
  pass "SENTRY_DSN set on nexus-api"
else
  skip "SENTRY_DSN empty on nexus-api (optional until Sentry projects created)"
fi

if ((${#FAILURES[@]} > 0)); then
  echo ""
  echo "Staging observability verification failed:"
  printf ' - %s\n' "${FAILURES[@]}"
  exit 1
fi

echo ""
echo "Staging observability verification passed."

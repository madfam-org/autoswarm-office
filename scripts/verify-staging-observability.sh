#!/usr/bin/env bash
# Verify observability secret wiring (Phase 0 Tier 1 / Wave 1 operator gate).
#
# Checks that selva-observability-secrets exists and deployments picked up
# OTel/Sentry env vars. Secret values are never printed.
#
# Usage:
#   ./scripts/verify-staging-observability.sh
#   ./scripts/verify-staging-observability.sh --require-secret
#   ./scripts/verify-staging-observability.sh --check-all
#   ./scripts/verify-staging-observability.sh --namespace selva --require-secret
#
set -euo pipefail

NS="${STAGING_NAMESPACE:-selva-staging}"
SECRET="${OBSERVABILITY_SECRET:-selva-observability-secrets}"
REQUIRE=false
CHECK_ALL=false
FAILURES=()

pass() { echo "OK: $*"; }
fail() { echo "FAIL: $*"; FAILURES+=("$*"); }
skip() { echo "SKIP: $*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --require-secret) REQUIRE=true ;;
    --check-all) CHECK_ALL=true ;;
    --namespace=*) NS="${1#*=}" ;;
    --namespace)
      NS="${2:?--namespace requires a value}"
      shift
      ;;
  esac
  shift
done

echo "== Observability verification (namespace=${NS}) =="

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

_check_pod_env() {
  local deploy="$1"
  local container="$2"
  local env_name="$3"
  local required="$4"

  local pod
  pod="$(kubectl -n "$NS" get pod -l "app.kubernetes.io/name=${deploy}" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [[ -z "$pod" ]]; then
    fail "no ${deploy} pod in ${NS}"
    return
  fi

  local val
  val="$(kubectl -n "$NS" exec "$pod" -c "$container" -- printenv "$env_name" 2>/dev/null || true)"
  if [[ -n "$val" ]]; then
    pass "${deploy}: ${env_name} set"
  elif [[ "$required" == "required" ]]; then
    fail "${deploy}: ${env_name} empty — restart deploy after secret create"
  else
    skip "${deploy}: ${env_name} empty (optional until Sentry projects exist)"
  fi
}

# OTel exporters ship on Python services that emit spans today.
OTEL_DEPLOYS=(nexus-api workers)
SENTRY_DEPLOYS=(nexus-api workers gateway colyseus office-ui admin)

if $CHECK_ALL; then
  for deploy in "${OTEL_DEPLOYS[@]}"; do
    _check_pod_env "$deploy" "$deploy" OTEL_EXPORTER_OTLP_ENDPOINT required
  done
  for deploy in "${SENTRY_DEPLOYS[@]}"; do
    _check_pod_env "$deploy" "$deploy" SENTRY_DSN optional
  done
else
  _check_pod_env nexus-api nexus-api OTEL_EXPORTER_OTLP_ENDPOINT required
  _check_pod_env nexus-api nexus-api SENTRY_DSN optional
fi

if ((${#FAILURES[@]} > 0)); then
  echo ""
  echo "Observability verification failed:"
  printf ' - %s\n' "${FAILURES[@]}"
  exit 1
fi

echo ""
echo "Observability verification passed (namespace=${NS})."

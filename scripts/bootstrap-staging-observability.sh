#!/usr/bin/env bash
# Bootstrap autoswarm-observability-secrets in staging (Tier 1 operator gate).
#
# Does NOT invent credentials — operator must export real values first:
#   export OTEL_EXPORTER_OTLP_ENDPOINT='https://otlp-gateway-...grafana.net/otlp'
#   export OTEL_EXPORTER_OTLP_HEADERS='Authorization=Basic ...'
#   export SENTRY_DSN_NEXUS_API='https://...@...ingest.de.sentry.io/...'
#   # optional: SENTRY_DSN_WORKERS, SENTRY_DSN_GATEWAY, etc.
#
# Usage:
#   ./scripts/bootstrap-staging-observability.sh --dry-run
#   ./scripts/bootstrap-staging-observability.sh
#
set -euo pipefail

NS="${STAGING_NAMESPACE:-autoswarm-staging}"
SECRET="${OBSERVABILITY_SECRET:-autoswarm-observability-secrets}"
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
  esac
done

echo "== Bootstrap staging observability secret (${NS}/${SECRET}) =="

if [[ -z "${OTEL_EXPORTER_OTLP_ENDPOINT:-}" ]]; then
  echo "FAIL: export OTEL_EXPORTER_OTLP_ENDPOINT before running"
  echo "      See docs/OBSERVABILITY_VENDOR_SELECTION.md and infra/k8s/production/observability-secrets-template.yaml"
  exit 1
fi

ARGS=(
  --from-literal=OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT}"
)
if [[ -n "${OTEL_EXPORTER_OTLP_HEADERS:-}" ]]; then
  ARGS+=(--from-literal=OTEL_EXPORTER_OTLP_HEADERS="${OTEL_EXPORTER_OTLP_HEADERS}")
fi
for key in SENTRY_DSN_NEXUS_API SENTRY_DSN_WORKERS SENTRY_DSN_GATEWAY SENTRY_DSN_COLYSEUS SENTRY_DSN_OFFICE_UI SENTRY_DSN_ADMIN; do
  val="${!key:-}"
  if [[ -n "$val" ]]; then
    ARGS+=(--from-literal="${key}=${val}")
  fi
done

if $DRY_RUN; then
  echo "DRY: kubectl create secret generic ${SECRET} -n ${NS} (${#ARGS[@]} literals)"
  exit 0
fi

if kubectl -n "$NS" get secret "$SECRET" >/dev/null 2>&1; then
  echo "Secret exists — patching (merge)"
  PATCH=$(python3 - <<'PY'
import json, os
keys = ["OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS",
        "SENTRY_DSN_NEXUS_API", "SENTRY_DSN_WORKERS", "SENTRY_DSN_GATEWAY",
        "SENTRY_DSN_COLYSEUS", "SENTRY_DSN_OFFICE_UI", "SENTRY_DSN_ADMIN"]
data = {k: os.environ[k] for k in keys if os.environ.get(k)}
print(json.dumps({"stringData": data}))
PY
)
  kubectl -n "$NS" patch secret "$SECRET" --type merge -p "$PATCH"
else
  kubectl create secret generic "$SECRET" -n "$NS" "${ARGS[@]}"
fi

kubectl -n "$NS" rollout restart deploy/nexus-api deploy/workers deploy/gateway deploy/colyseus deploy/office-ui deploy/admin
echo "OK   observability secret applied — pods restarted"
./scripts/verify-staging-observability.sh --require-secret

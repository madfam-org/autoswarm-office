#!/usr/bin/env bash
# Bootstrap selva-observability-secrets in production (Tier 1 operator gate).
#
# Same contract as bootstrap-staging-observability.sh but targets namespace
# ``selva``. Requires explicit operator credentials — never commit values.
#
# Usage:
#   export OTEL_EXPORTER_OTLP_ENDPOINT='https://otlp-gateway-...grafana.net/otlp'
#   export OTEL_EXPORTER_OTLP_HEADERS='Authorization=Basic ...'
#   export SENTRY_DSN_NEXUS_API='https://...@...ingest.de.sentry.io/...'
#   ./scripts/bootstrap-prod-observability.sh --dry-run
#   ./scripts/bootstrap-prod-observability.sh
#
set -euo pipefail

export STAGING_NAMESPACE="${PROD_NAMESPACE:-selva}"
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/bootstrap-staging-observability.sh" "$@"

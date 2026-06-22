#!/usr/bin/env bash
# Verify production observability secret wiring (Phase 0 / Wave 1).
#
# Usage:
#   ./scripts/verify-prod-observability.sh
#   ./scripts/verify-prod-observability.sh --require-secret
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${ROOT}/scripts/verify-staging-observability.sh" \
  --namespace "${PROD_NAMESPACE:-selva}" \
  "$@"

#!/usr/bin/env bash
# Phase 0 gate checker — runs local CI drift + optional prod/staging smokes.
#
# Usage:
#   ./scripts/verify-phase0-gates.sh              # local tests only
#   ./scripts/verify-phase0-gates.sh --prod       # + verify-doc-truth.sh
#   ./scripts/verify-phase0-gates.sh --staging    # + staging-smoke.sh
#   ./scripts/verify-phase0-gates.sh --all        # prod + staging smokes
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUN_PROD=false
RUN_STAGING=false
for arg in "$@"; do
  case "$arg" in
    --prod) RUN_PROD=true ;;
    --staging) RUN_STAGING=true ;;
    --all) RUN_PROD=true; RUN_STAGING=true ;;
  esac
done

echo "== Phase 0 local gates =="
uv run pytest apps/nexus-api/tests/test_doc_codification.py -q
uv run pytest apps/nexus-api/tests/test_tulana_campaign_import.py -q
uv run pytest apps/workers/tests/test_campaign_graph.py -q

if ! kubectl kustomize infra/k8s/overlays/staging >/dev/null; then
  echo "FAIL: staging kustomize build"
  exit 1
fi
echo "OK   staging kustomize build"

if ! kubectl kustomize infra/k8s/production >/dev/null; then
  echo "FAIL: production kustomize build"
  exit 1
fi
echo "OK   production kustomize build"

if ! kubectl kustomize infra/k8s/production | grep -q 'autoswarm-observability-secrets'; then
  echo "FAIL: production overlay missing observability secret refs"
  exit 1
fi
echo "OK   observability env wired in production overlay"

if [[ "$RUN_PROD" == true ]]; then
  echo "== Prod smoke (verify-doc-truth) =="
  ./scripts/verify-doc-truth.sh
fi

if [[ "$RUN_STAGING" == true ]]; then
  echo "== Staging smoke =="
  ./scripts/staging-smoke.sh
fi

echo "Phase 0 gates passed (operator still must provision OTel/Sentry secrets)."

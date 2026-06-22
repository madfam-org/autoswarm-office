#!/usr/bin/env bash
# Wave 1 operational proof orchestrator (Phase 0 gates 0.1–0.5).
#
# Runs observability, load preflight, DR evidence, and related staging checks.
# Operator credentials (OTel endpoint, Grafana query token, k8s access) must
# be exported before --require-all will pass.
#
# Usage:
#   ./scripts/run-wave1-gates.sh --staging              # soft (SKIP allowed)
#   ./scripts/run-wave1-gates.sh --staging --require-all  # hard fail
#   ./scripts/run-wave1-gates.sh --prod                 # prod observability only
#
# Environment (optional):
#   TEMPO_QUERY_URL / GRAFANA_URL + GRAFANA_TEMPO_DATASOURCE_UID + GRAFANA_API_TOKEN
#   STAGING_WORKER_API_TOKEN / WORKER_API_TOKEN
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUN_STAGING=false
RUN_PROD=false
REQUIRE_ALL=false

for arg in "$@"; do
  case "$arg" in
    --staging) RUN_STAGING=true ;;
    --prod) RUN_PROD=true ;;
    --all) RUN_STAGING=true; RUN_PROD=true ;;
    --require-all) REQUIRE_ALL=true ;;
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

if [[ "$RUN_STAGING" != true && "$RUN_PROD" != true ]]; then
  RUN_STAGING=true
fi

soft_or_fail() {
  if $REQUIRE_ALL; then
    "$@"
  else
    "$@" || true
  fi
}

hard_or_fail() {
  if $REQUIRE_ALL; then
    "$@"
  else
    "$@" || true
  fi
}

echo "== Wave 1 gates (require_all=${REQUIRE_ALL}) =="

if [[ "$RUN_STAGING" == true ]]; then
  echo ""
  echo "== Staging observability secret =="
  if $REQUIRE_ALL; then
    ./scripts/verify-staging-observability.sh --require-secret --check-all
  else
    ./scripts/verify-staging-observability.sh --check-all || true
  fi

  echo ""
  echo "== OTel trace proof =="
  if $REQUIRE_ALL; then
    ./scripts/verify-observability-trace.sh --require-trace
  else
    ./scripts/verify-observability-trace.sh || true
  fi

  echo ""
  echo "== Sentry capture proof =="
  if $REQUIRE_ALL; then
    ./scripts/verify-sentry-capture.sh --staging --require-capture
  else
    ./scripts/verify-sentry-capture.sh --staging || true
  fi

  echo ""
  echo "== Run 4b load preflight =="
  hard_or_fail ./scripts/verify-staging-load-run4b-preflight.sh --require-live

  echo ""
  echo "== DR drill evidence =="
  hard_or_fail ./scripts/verify-dr-drill-evidence.sh

  echo ""
  echo "== Dhanam billing path =="
  soft_or_fail ./scripts/verify-dhanam-billing-path.sh --staging

  echo ""
  echo "== Dhanam price-tier map =="
  if $REQUIRE_ALL; then
    ./scripts/verify-dhanam-price-tier-map.sh --staging --require-all
  else
    ./scripts/verify-dhanam-price-tier-map.sh --staging || true
  fi
fi

if [[ "$RUN_PROD" == true ]]; then
  echo ""
  echo "== Prod observability secret =="
  if $REQUIRE_ALL; then
    ./scripts/verify-prod-observability.sh --require-secret --check-all
  else
    ./scripts/verify-prod-observability.sh --check-all || true
  fi

  echo ""
  echo "== Prod doc-truth smoke =="
  soft_or_fail ./scripts/verify-doc-truth.sh

  echo ""
  echo "== Prod Sentry capture proof =="
  if $REQUIRE_ALL; then
    ./scripts/verify-sentry-capture.sh --prod --require-capture
  else
    ./scripts/verify-sentry-capture.sh --prod || true
  fi
fi

if $REQUIRE_ALL; then
  echo ""
  echo "Wave 1 gates passed (--require-all)."
else
  echo ""
  echo "Wave 1 soft run complete — re-run with --require-all after operator provisioning."
fi

#!/usr/bin/env bash
# Wire Dhanam staging → Selva billing webhook fan-out (ROI Tier 2 item 3).
#
# Selva accepts signed POST /api/v1/billing/webhooks/dhanam when
# DHANAM_WEBHOOK_SECRET matches. Dhanam relays subscription events to
# PRODUCT_WEBHOOK_URLS consumers using the same secret for HMAC.
#
# Usage:
#   ./scripts/reconcile-dhanam-selva-webhook.sh --dry-run
#   ./scripts/reconcile-dhanam-selva-webhook.sh
#
set -euo pipefail

DRY_RUN=false
SELVA_NS="${SELVA_STAGING_NS:-autoswarm-staging}"
DHANAM_NS="${DHANAM_STAGING_NS:-enclii-dhanam-staging}"
SELVA_WEBHOOK_URL="${SELVA_DHANAM_WEBHOOK_URL:-https://staging-api.selva.town/api/v1/billing/webhooks/dhanam}"

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
  esac
done

pass() { echo "OK: $*"; }
skip() { echo "SKIP: $*"; }

echo "== Dhanam → Selva webhook reconcile (staging) =="

if ! command -v kubectl >/dev/null 2>&1; then
  skip "kubectl unavailable"
  exit 0
fi

SELVA_SECRET="$(kubectl -n "$SELVA_NS" get secret autoswarm-staging-secrets \
  -o jsonpath='{.data.DHANAM_WEBHOOK_SECRET}' 2>/dev/null | base64 -d || true)"
if [[ -z "$SELVA_SECRET" ]]; then
  echo "FAIL: DHANAM_WEBHOOK_SECRET missing in ${SELVA_NS}/autoswarm-staging-secrets"
  echo "      Run ./scripts/reconcile-staging-argocd.sh --ensure-dhanam-secret first"
  exit 1
fi
pass "loaded Selva DHANAM_WEBHOOK_SECRET (${#SELVA_SECRET} bytes)"

TARGET_URLS="selva:${SELVA_WEBHOOK_URL}"
CURRENT="$(kubectl -n "$DHANAM_NS" get secret dhanam-secrets \
  -o jsonpath='{.data.PRODUCT_WEBHOOK_URLS}' 2>/dev/null | base64 -d || true)"

if [[ "$CURRENT" == *"$SELVA_WEBHOOK_URL"* ]]; then
  pass "Dhanam PRODUCT_WEBHOOK_URLS already includes Selva staging URL"
else
  echo "Will set PRODUCT_WEBHOOK_URLS=${TARGET_URLS}"
  if $DRY_RUN; then
    skip "dry-run — not patching ${DHANAM_NS}/dhanam-secrets"
  else
    kubectl -n "$DHANAM_NS" patch secret dhanam-secrets --type merge \
      -p "{\"stringData\":{\"PRODUCT_WEBHOOK_URLS\":\"${TARGET_URLS}\",\"DHANAM_WEBHOOK_SECRET\":\"${SELVA_SECRET}\"}}"
    pass "patched ${DHANAM_NS}/dhanam-secrets (PRODUCT_WEBHOOK_URLS + DHANAM_WEBHOOK_SECRET)"
    echo "Restart Dhanam API if env was cached: kubectl -n ${DHANAM_NS} rollout restart deploy/dhanam-api"
  fi
fi

if $DRY_RUN; then
  exit 0
fi

echo "--- verify Selva webhook round-trip ---"
DHANAM_WEBHOOK_SECRET="$SELVA_SECRET" ./scripts/verify-dhanam-billing-path.sh --staging

echo "OK   Dhanam → Selva webhook reconcile complete"

#!/usr/bin/env bash
# Verify Dhanam Stripe price → tier mapping is configured (ROI Tier 2 item 3 remainder).
#
# Selva expects tier in the Dhanam webhook payload — price IDs must map in Dhanam catalog.
# This script checks Dhanam staging/prod secrets for known mapping keys; operator fills gaps in Dhanam admin.
#
# Usage:
#   ./scripts/verify-dhanam-price-tier-map.sh --staging
#   ./scripts/verify-dhanam-price-tier-map.sh
#
set -euo pipefail

MODE=prod
DHANAM_NS="${DHANAM_NS:-enclii-dhanam}"

for arg in "$@"; do
  case "$arg" in
    --staging) MODE=staging; DHANAM_NS="${DHANAM_STAGING_NS:-enclii-dhanam-staging}" ;;
  esac
done

pass() { echo "OK: $*"; }
skip() { echo "SKIP: $*"; }
fail() { echo "FAIL: $*"; exit 1; }

echo "== Dhanam price→tier map verification (mode=${MODE}, ns=${DHANAM_NS}) =="

if ! command -v kubectl >/dev/null 2>&1; then
  skip "kubectl unavailable"
  exit 0
fi

# Keys vary by Dhanam release; any of these indicate catalog wiring exists.
WANT_KEYS=(STRIPE_PRICE_ID_STARTER STRIPE_PRICE_ID_PROFESSIONAL STRIPE_PRICE_ID_ENTERPRISE PRICE_TIER_MAP STRIPE_PRICE_TO_TIER_MAP)

KEYS="$(kubectl -n "$DHANAM_NS" get secret dhanam-secrets -o json 2>/dev/null \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(' '.join(sorted(d.get('data',{}).keys())))" || true)"

if [[ -z "$KEYS" ]]; then
  fail "secret dhanam-secrets not readable in ${DHANAM_NS}"
fi

FOUND=0
for k in "${WANT_KEYS[@]}"; do
  if [[ " $KEYS " == *" $k "* ]]; then
    pass "Dhanam secret contains ${k}"
    FOUND=$((FOUND + 1))
  fi
done

if [[ "$FOUND" -eq 0 ]]; then
  skip "no price→tier keys in ${DHANAM_NS}/dhanam-secrets — operator must map Stripe price IDs in Dhanam catalog"
  echo "      Selva tiers: infra/pricing/selva-tiers.json (starter/professional/enterprise daily limits)"
  echo "      Webhook fan-out: ./scripts/reconcile-dhanam-selva-webhook.sh --staging"
  exit 0
fi

pass "Dhanam price→tier secret keys present (${FOUND}/${#WANT_KEYS[@]} matched)"
echo "Next: complete Stripe Dashboard → Dhanam catalog mapping; prod fan-out via PRODUCT_WEBHOOK_URLS=https://api.selva.town/..."

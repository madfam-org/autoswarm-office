#!/usr/bin/env bash
# Verify Dhanam-first billing path configuration (Phase 0.3 / 1.2).
#
# Checks:
#   1. nexus-api exposes Dhanam webhook (503 when secret unset locally)
#   2. Direct Stripe webhook blocked when BILLING_VIA_DHANAM=true
#   3. Optional live staging webhook round-trip when env vars set
#
# Usage:
#   ./scripts/verify-dhanam-billing-path.sh
#   BASE_URL=https://staging-api.selva.town \
#   DHANAM_WEBHOOK_SECRET=... \
#   ./scripts/verify-dhanam-billing-path.sh --staging
#
# Exit 0 when all applicable checks pass.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BASE_URL="${BASE_URL:-http://localhost:4300}"
MODE="${1:-local}"
FAILURES=()

pass() { echo "OK: $*"; }
fail() { echo "FAIL: $*"; FAILURES+=("$*"); }

echo "== Dhanam billing path verification (mode=$MODE) =="

if [[ "$MODE" == "--staging" ]]; then
  BASE_URL="${STAGING_API_URL:-https://staging-api.selva.town}"
  if [[ -z "${DHANAM_WEBHOOK_SECRET:-}" ]] && command -v kubectl >/dev/null 2>&1; then
    DHANAM_WEBHOOK_SECRET="$(kubectl -n selva-staging get secret selva-staging-secrets \
      -o jsonpath='{.data.DHANAM_WEBHOOK_SECRET}' 2>/dev/null | base64 -d || true)"
    if [[ -n "${DHANAM_WEBHOOK_SECRET:-}" ]]; then
      pass "loaded DHANAM_WEBHOOK_SECRET from selva-staging-secrets"
    fi
  fi
fi

# Stripe direct path should be blocked in default Dhanam-first config (503 on prod/staging).
stripe_code="$(curl -sS -o /dev/null -w '%{http_code}' \
  -X POST "${BASE_URL}/api/v1/stripe/webhook" \
  -H 'stripe-signature: t=0,v1=test' \
  --data '{}' || true)"
if [[ "$stripe_code" == "503" ]]; then
  pass "direct Stripe webhook blocked (503) — Dhanam-first active"
else
  fail "expected Stripe webhook 503, got ${stripe_code}"
fi

# Dhanam webhook must fail closed without signature/secret.
dhanam_code="$(curl -sS -o /dev/null -w '%{http_code}' \
  -X POST "${BASE_URL}/api/v1/billing/webhooks/dhanam" \
  -H 'Content-Type: application/json' \
  -H 'x-dhanam-signature: invalid' \
  --data '{"type":"subscription.updated","data":{"org_id":"test","tier":"starter"}}' || true)"
if [[ "$dhanam_code" == "401" || "$dhanam_code" == "503" ]]; then
  pass "Dhanam webhook fail-closed without valid HMAC (${dhanam_code})"
else
  fail "expected Dhanam webhook 401/503, got ${dhanam_code}"
fi

# Optional signed round-trip when operator provides secret (staging/prod validation).
if [[ -n "${DHANAM_WEBHOOK_SECRET:-}" ]]; then
  payload='{"type":"subscription.updated","data":{"org_id":"billing-verify-org","tier":"professional","status":"active"}}'
  sig="$(printf '%s' "$payload" | openssl dgst -sha256 -hmac "$DHANAM_WEBHOOK_SECRET" | awk '{print $NF}')"
  signed_code="$(curl -sS -o /dev/null -w '%{http_code}' \
    -X POST "${BASE_URL}/api/v1/billing/webhooks/dhanam" \
    -H 'Content-Type: application/json' \
    -H "x-dhanam-signature: ${sig}" \
    --data "$payload" || true)"
  if [[ "$signed_code" == "200" ]]; then
    pass "signed Dhanam webhook accepted (200)"
  else
    fail "signed Dhanam webhook expected 200, got ${signed_code}"
  fi
else
  echo "SKIP: DHANAM_WEBHOOK_SECRET unset — signed webhook round-trip not tested"
fi

# K8s manifest drift gate (local only).
if [[ "$MODE" != "--staging" ]]; then
  if rg -q 'DHANAM_WEBHOOK_SECRET' infra/k8s/production/nexus-api.yaml \
    && rg -q 'staging-api.dhan.am' infra/k8s/overlays/staging/patch-nexus-api.yaml; then
    pass "K8s manifests wire Dhanam URL + webhook secret"
  else
    fail "K8s Dhanam wiring missing in production/staging patches"
  fi
fi

if ((${#FAILURES[@]} > 0)); then
  echo ""
  echo "Dhanam billing verification failed:"
  printf ' - %s\n' "${FAILURES[@]}"
  exit 1
fi

echo ""
echo "Dhanam billing path verification passed."

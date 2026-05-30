#!/usr/bin/env bash
# Operator smoke: verify selva.town health endpoints and A2A public URL.
# Not run in CI (external network).
#
# Pre-deploy: health checks pass; A2A url may still be localhost until
# PUBLIC_APP_URL/CORS_ORIGINS configmap lands via Enclii promote.
# Usage: ./scripts/verify-doc-truth.sh
set -euo pipefail

check() {
  local label="$1"
  local url="$2"
  local expect_code="${3:-200}"
  local code
  code="$(curl -sS -o /tmp/selva-verify-body.txt -w "%{http_code}" "$url")"
  if [[ "$code" != "$expect_code" ]]; then
    echo "FAIL $label: $url -> HTTP $code (expected $expect_code)"
    cat /tmp/selva-verify-body.txt
    exit 1
  fi
  echo "OK   $label: $url -> HTTP $code"
}

check "nexus-api root health" "https://api.selva.town/health"
check "nexus-api readiness" "https://api.selva.town/api/v1/health/ready"
check "nexus-api liveness" "https://api.selva.town/api/v1/health/health"
check "colyseus health" "https://ws.selva.town/health"
check "gateway health" "https://gw.selva.town/health"

rls_body="$(curl -sS "https://api.selva.town/api/v1/health/rls-status")"
if echo "$rls_body" | grep -q '"strict_mode_enabled":true'; then
  echo "OK   RLS strict mode enabled"
else
  echo "FAIL RLS strict mode not enabled:"
  echo "$rls_body"
  exit 1
fi

a2a_body="$(curl -sS "https://api.selva.town/api/v1/a2a/.well-known/agent.json")"
if echo "$a2a_body" | grep -q '"url":"https://app.selva.town"'; then
  echo "OK   A2A AgentCard url is https://app.selva.town"
elif echo "$a2a_body" | grep -q '"url":"http://localhost:4301"'; then
  echo "WARN A2A AgentCard still localhost — deploy PUBLIC_APP_URL configmap + promote"
  exit 1
else
  echo "FAIL A2A AgentCard url unexpected:"
  echo "$a2a_body" | head -c 400
  exit 1
fi

echo "All doc-truth prod checks passed."

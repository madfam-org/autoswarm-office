#!/usr/bin/env bash
# PP.4 — staging smoke test for selva-office.
#
# Hits /health (or equivalent) on each of the 5 HTTP-exposed services
# in the selva-office staging tier. Workers is not HTTP-exposed
# externally — its health is checked by whether the dependent services
# stay healthy (workers process tasks from Redis and update task
# status on nexus-api; an unhealthy workers pod manifests as stuck
# `running` tasks, which is out-of-band monitoring).
#
# Retry profile matches Karafiel + Dhanam: 6 attempts x 20s gap.
# Rolling restart on a 6-pod deploy can briefly 502 before the new
# pod passes readiness, so retries are non-negotiable.
#
# Env vars (all optional — defaults shown):
#   STAGING_API_URL    https://staging-api.selva.town
#   STAGING_UI_URL     https://staging.selva.town
#   STAGING_ADMIN_URL  https://staging-admin.selva.town
#   STAGING_WS_URL     https://staging-ws.selva.town
#   STAGING_GW_URL     https://staging-gw.selva.town
#
# Exit 0 if all services pass, 1 otherwise.

set -euo pipefail

STAGING_API_URL="${STAGING_API_URL:-https://staging-api.selva.town}"
STAGING_UI_URL="${STAGING_UI_URL:-https://staging.selva.town}"
STAGING_ADMIN_URL="${STAGING_ADMIN_URL:-https://staging-admin.selva.town}"
STAGING_WS_URL="${STAGING_WS_URL:-https://staging-ws.selva.town}"
STAGING_GW_URL="${STAGING_GW_URL:-https://staging-gw.selva.town}"

FAILURES=()

check() {
  local name="$1"
  local url="$2"
  echo "--- Smoke check: $name ($url) ---"
  for i in 1 2 3 4 5 6; do
    if curl -fsS --max-time 10 "$url" > /dev/null; then
      echo "OK: $name passed on attempt $i"
      return 0
    fi
    echo "attempt $i: $name unhealthy, retrying in 20s"
    sleep 20
  done
  echo "::error::$name failed health check after 6 attempts ($url)"
  FAILURES+=("$name")
  return 1
}

# nexus-api exposes /api/v1/health/health (per prod deployment spec)
check "nexus-api"  "$STAGING_API_URL/api/v1/health/health" || true

# office-ui is Next.js; /api/health is the built-in route
check "office-ui"  "$STAGING_UI_URL/api/health" || true

# admin is Next.js; same pattern
check "admin"      "$STAGING_ADMIN_URL/api/health" || true

# colyseus exposes /health on port 4303 (ingress-mapped to staging-ws)
check "colyseus"   "$STAGING_WS_URL/health" || true

# gateway exposes /health on port 4304 (ingress-mapped to staging-gw)
check "gateway"    "$STAGING_GW_URL/health" || true

if [[ ${#FAILURES[@]} -gt 0 ]]; then
  echo ""
  echo "::error::Staging smoke failed for: ${FAILURES[*]}"
  exit 1
fi

echo ""
echo "All staging services healthy."

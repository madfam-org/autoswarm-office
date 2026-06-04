#!/usr/bin/env bash
# Verify that the next quarterly Selva-owned secret rotation is scheduled.
#
# Usage:
#   ./scripts/verify-secret-rotation-schedule.sh
#   SECRET_ROTATION_SCHEDULE_FILE=docs/secret-rotations/2026Q3-schedule.md ./scripts/verify-secret-rotation-schedule.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SCHEDULE_DIR="${SECRET_ROTATION_SCHEDULE_DIR:-docs/secret-rotations}"
SCHEDULE_FILE="${SECRET_ROTATION_SCHEDULE_FILE:-}"

fail() { echo "FAIL: $*"; exit 1; }
pass() { echo "OK: $*"; }

if [[ -z "$SCHEDULE_FILE" ]]; then
  if [[ -d "$SCHEDULE_DIR" ]]; then
    SCHEDULE_FILE="$(find "$SCHEDULE_DIR" -maxdepth 1 -type f -name '20*Q*-schedule.md' | sort | tail -n 1)"
  fi
fi

[[ -n "$SCHEDULE_FILE" ]] || fail "no quarterly secret rotation schedule found in ${SCHEDULE_DIR}"
[[ -f "$SCHEDULE_FILE" ]] || fail "secret rotation schedule file not found: ${SCHEDULE_FILE}"

grep -Fq "| Status | SCHEDULED |" "$SCHEDULE_FILE" || fail "schedule missing SCHEDULED status"
grep -Fq "| Rotation window |" "$SCHEDULE_FILE" || fail "schedule missing rotation window"
grep -Fq "America/Mexico_City" "$SCHEDULE_FILE" || fail "schedule missing Mexico City timezone"
grep -Fq "worker-api-token" "$SCHEDULE_FILE" || fail "schedule missing worker-api-token target"
grep -Fq "consent-ledger-signing" "$SCHEDULE_FILE" || fail "schedule missing consent-ledger-signing target"
grep -Fq "colyseus-service" "$SCHEDULE_FILE" || fail "schedule missing colyseus-service target"
grep -Fq "./scripts/rotate-secret.sh --all --namespace=selva --dry-run" "$SCHEDULE_FILE" || fail "schedule missing dry-run command"
grep -Fq "./scripts/rotate-secret.sh --all --namespace=selva" "$SCHEDULE_FILE" || fail "schedule missing execute command"

if grep -Eq '\| (Status|Rotation window|Targets) \| (TBD|TODO|not provided|none) \|' "$SCHEDULE_FILE"; then
  fail "schedule contains placeholder required field: ${SCHEDULE_FILE}"
fi

pass "secret rotation schedule verified: ${SCHEDULE_FILE}"

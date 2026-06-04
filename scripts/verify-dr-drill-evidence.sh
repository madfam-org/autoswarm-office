#!/usr/bin/env bash
# Verify that Phase 0 has a dated backup/restore drill evidence record.
#
# Usage:
#   ./scripts/verify-dr-drill-evidence.sh
#   DR_DRILL_EVIDENCE_FILE=docs/dr-drills/20260604T200000Z.md ./scripts/verify-dr-drill-evidence.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

EVIDENCE_DIR="${DR_DRILL_EVIDENCE_DIR:-docs/dr-drills}"
EVIDENCE_FILE="${DR_DRILL_EVIDENCE_FILE:-}"

fail() { echo "FAIL: $*"; exit 1; }
pass() { echo "OK: $*"; }

if [[ -z "$EVIDENCE_FILE" ]]; then
  if [[ -d "$EVIDENCE_DIR" ]]; then
    EVIDENCE_FILE="$(find "$EVIDENCE_DIR" -maxdepth 1 -type f -name '20*T*Z.md' | sort | tail -n 1)"
  fi
fi

[[ -n "$EVIDENCE_FILE" ]] || fail "no timestamped DR drill evidence file found in ${EVIDENCE_DIR}"
[[ -f "$EVIDENCE_FILE" ]] || fail "DR drill evidence file not found: ${EVIDENCE_FILE}"

grep -Fq "| Status | PASS |" "$EVIDENCE_FILE" || fail "evidence missing PASS status: ${EVIDENCE_FILE}"
grep -Fq "| Measured RTO seconds |" "$EVIDENCE_FILE" || fail "evidence missing measured RTO: ${EVIDENCE_FILE}"
grep -Fq "| Backup age at restore seconds |" "$EVIDENCE_FILE" || fail "evidence missing backup age/RPO proxy: ${EVIDENCE_FILE}"
grep -Fq "| Restore target |" "$EVIDENCE_FILE" || fail "evidence missing restore target: ${EVIDENCE_FILE}"

if grep -Eq '\| (Measured RTO seconds|Backup age at restore seconds|Restore target) \| (TBD|skipped|not provided|none) \|' "$EVIDENCE_FILE"; then
  fail "evidence contains placeholder or skipped required field: ${EVIDENCE_FILE}"
fi

pass "DR drill evidence verified: ${EVIDENCE_FILE}"

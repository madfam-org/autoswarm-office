#!/usr/bin/env bash
# Run or preflight the Phase 0 database backup/restore drill.
#
# Default mode is non-mutating preflight. Execution mode is destructive to the
# restore target and is intentionally blocked unless all guard env vars are set.
#
# Usage:
#   ./scripts/run-db-restore-drill.sh --preflight
#   DR_DRILL_EXECUTE=yes \
#   DR_SOURCE_ENV=prod \
#   DR_TARGET_ENV=staging \
#   DR_BACKUP_DATABASE_URL=postgresql://... \
#   DR_RESTORE_DATABASE_URL=postgresql://... \
#     ./scripts/run-db-restore-drill.sh --execute
#
# Optional:
#   DR_BACKUP_FILE=./backups/selva_YYYYMMDD_HHMMSS.dump  # skip fresh backup
#   DR_HEALTH_URL=https://staging-api.selva.town/api/v1/health/ready
#   DR_EVIDENCE_DIR=docs/dr-drills
#   DR_SKIP_VERIFY=true
#   DR_SKIP_RESTORE=true
#   DR_SKIP_MIGRATIONS=true
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="preflight"
UPLOAD=false
for arg in "$@"; do
  case "$arg" in
    --preflight)
      MODE="preflight"
      ;;
    --execute)
      MODE="execute"
      ;;
    --upload)
      UPLOAD=true
      ;;
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

SOURCE_ENV="${DR_SOURCE_ENV:-}"
TARGET_ENV="${DR_TARGET_ENV:-}"
BACKUP_DATABASE_URL="${DR_BACKUP_DATABASE_URL:-}"
RESTORE_DATABASE_URL="${DR_RESTORE_DATABASE_URL:-}"
BACKUP_FILE="${DR_BACKUP_FILE:-}"
BACKUP_DIR="${BACKUP_DIR:-./backups/drills}"
EVIDENCE_DIR="${DR_EVIDENCE_DIR:-docs/dr-drills}"
SKIP_VERIFY="${DR_SKIP_VERIFY:-false}"
SKIP_RESTORE="${DR_SKIP_RESTORE:-false}"
SKIP_MIGRATIONS="${DR_SKIP_MIGRATIONS:-false}"
HEALTH_URL="${DR_HEALTH_URL:-}"
NOTES="${DR_NOTES:-}"

pass() { echo "OK: $*"; }
fail() { echo "FAIL: $*"; exit 1; }

is_true() {
  case "$1" in
    true|TRUE|yes|YES|1) return 0 ;;
    *) return 1 ;;
  esac
}

lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

stat_size() {
  stat -f%z "$1" 2>/dev/null || stat --printf="%s" "$1" 2>/dev/null || echo "unknown"
}

stat_mtime_epoch() {
  stat -f%m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null || echo "0"
}

require_tool() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "$1 not found in PATH"
  fi
  pass "$1 available"
}

validate_target() {
  if [[ -z "$TARGET_ENV" ]]; then
    fail "DR_TARGET_ENV is required"
  fi

  case "$(lower "$TARGET_ENV")" in
    prod|production|live|selva)
      fail "restore target '${TARGET_ENV}' is not allowed; use a clean non-production target"
      ;;
  esac

  pass "restore target '${TARGET_ENV}' is non-production"
}

echo "== DB restore drill ${MODE} =="

if [[ "$MODE" == "execute" && "${DR_DRILL_EXECUTE:-}" != "yes" ]]; then
  fail "set DR_DRILL_EXECUTE=yes to run the destructive drill"
fi

require_tool pg_dump
require_tool pg_restore
require_tool psql
if [[ -n "$HEALTH_URL" ]]; then
  require_tool curl
fi

if [[ -z "$SOURCE_ENV" ]]; then
  fail "DR_SOURCE_ENV is required"
fi
pass "source environment '${SOURCE_ENV}' declared"

validate_target

if [[ -n "$BACKUP_FILE" ]]; then
  [[ -f "$BACKUP_FILE" ]] || fail "DR_BACKUP_FILE not found: $BACKUP_FILE"
  pass "existing backup file found: $BACKUP_FILE"
else
  [[ -n "$BACKUP_DATABASE_URL" ]] || fail "DR_BACKUP_DATABASE_URL is required when DR_BACKUP_FILE is unset"
  pass "fresh backup source URL supplied"
fi

if ! is_true "$SKIP_VERIFY"; then
  [[ -n "$RESTORE_DATABASE_URL" ]] || fail "DR_RESTORE_DATABASE_URL is required for backup verification"
  pass "restore URL supplied for verification"
fi

if ! is_true "$SKIP_RESTORE"; then
  [[ -n "$RESTORE_DATABASE_URL" ]] || fail "DR_RESTORE_DATABASE_URL is required for restore"
  pass "restore URL supplied for destructive restore"
fi

if [[ "$MODE" != "execute" ]]; then
  echo ""
  echo "Preflight passed. Execution is intentionally blocked unless all of these are true:"
  echo "  --execute"
  echo "  DR_DRILL_EXECUTE=yes"
  echo "  DR_TARGET_ENV is a named non-production target"
  echo "  DR_RESTORE_DATABASE_URL points at the clean drill target"
  echo ""
  echo "Evidence will be written under ${EVIDENCE_DIR}/."
  exit 0
fi

mkdir -p "$BACKUP_DIR" "$EVIDENCE_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_FILE="${DR_EVIDENCE_FILE:-${EVIDENCE_DIR}/${STAMP}.md}"

START_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
BACKUP_COMPLETED_ISO="skipped"
VERIFY_COMPLETED_ISO="skipped"
RESTORE_STARTED_ISO="skipped"
RESTORE_COMPLETED_ISO="skipped"
HEALTH_COMPLETED_ISO="skipped"
STATUS="PASS"

echo "== Backup =="
if [[ -z "$BACKUP_FILE" ]]; then
  backup_args=()
  if [[ "$UPLOAD" == "true" ]]; then
    backup_args+=(--upload)
  fi
  DATABASE_URL="$BACKUP_DATABASE_URL" BACKUP_DIR="$BACKUP_DIR" \
    "${ROOT}/scripts/backup-postgres.sh" "${backup_args[@]}"
  BACKUP_FILE="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'selva_*.dump' | sort | tail -n 1)"
  [[ -n "$BACKUP_FILE" ]] || fail "backup did not produce a dump in ${BACKUP_DIR}"
fi
BACKUP_COMPLETED_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
BACKUP_SIZE="$(stat_size "$BACKUP_FILE")"
pass "backup ready: ${BACKUP_FILE} (${BACKUP_SIZE} bytes)"

echo "== Verify backup =="
if ! is_true "$SKIP_VERIFY"; then
  DATABASE_URL="$RESTORE_DATABASE_URL" "${ROOT}/scripts/verify-backup.sh" "$BACKUP_FILE"
  VERIFY_COMPLETED_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  pass "backup verification completed"
else
  pass "backup verification skipped by DR_SKIP_VERIFY"
fi

echo "== Restore target =="
RESTORE_START_EPOCH="$(date +%s)"
if ! is_true "$SKIP_RESTORE"; then
  RESTORE_STARTED_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  restore_args=(--force)
  if is_true "$SKIP_MIGRATIONS"; then
    restore_args+=(--skip-migrations)
  fi
  DATABASE_URL="$RESTORE_DATABASE_URL" \
    "${ROOT}/scripts/restore-postgres.sh" "$BACKUP_FILE" "${restore_args[@]}"
  RESTORE_COMPLETED_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  pass "restore completed"
else
  pass "restore skipped by DR_SKIP_RESTORE"
fi

echo "== Health check =="
if [[ -n "$HEALTH_URL" ]]; then
  curl -fsS --max-time 20 "$HEALTH_URL" >/dev/null
  HEALTH_COMPLETED_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  pass "health check passed: ${HEALTH_URL}"
else
  pass "health check skipped; DR_HEALTH_URL unset"
fi

END_EPOCH="$(date +%s)"
END_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RTO_SECONDS="$((END_EPOCH - RESTORE_START_EPOCH))"
BACKUP_MTIME="$(stat_mtime_epoch "$BACKUP_FILE")"
BACKUP_AGE_SECONDS="$((RESTORE_START_EPOCH - BACKUP_MTIME))"
if (( BACKUP_AGE_SECONDS < 0 )); then
  BACKUP_AGE_SECONDS=0
fi

cat > "$EVIDENCE_FILE" <<EOF
# DR Drill Evidence - ${STAMP}

| Field | Value |
|-------|-------|
| Status | ${STATUS} |
| Source environment | ${SOURCE_ENV} |
| Restore target | ${TARGET_ENV} |
| Backup file | ${BACKUP_FILE} |
| Backup size bytes | ${BACKUP_SIZE} |
| Started at | ${START_ISO} |
| Backup completed at | ${BACKUP_COMPLETED_ISO} |
| Verify completed at | ${VERIFY_COMPLETED_ISO} |
| Restore started at | ${RESTORE_STARTED_ISO} |
| Restore completed at | ${RESTORE_COMPLETED_ISO} |
| Health check completed at | ${HEALTH_COMPLETED_ISO} |
| Completed at | ${END_ISO} |
| Measured RTO seconds | ${RTO_SECONDS} |
| Backup age at restore seconds | ${BACKUP_AGE_SECONDS} |
| Health URL | ${HEALTH_URL:-not provided} |
| Notes | ${NOTES:-none} |

## Follow-up checklist

- [ ] Copy measured RTO/RPO into [DISASTER_RECOVERY.md](../DISASTER_RECOVERY.md) drill log.
- [ ] Attach this evidence file to the Phase 0 gate record.
- [ ] File follow-up issues for any manual/raw infra operation that should become an Enclii adapter.
EOF

echo "OK: evidence written to ${EVIDENCE_FILE}"

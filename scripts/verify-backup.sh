#!/usr/bin/env bash
set -euo pipefail

# Verify a PostgreSQL backup by restoring to a temporary database
# and validating that all expected tables are present with row counts.
#
# Usage: ./scripts/verify-backup.sh <backup_file>
#
# Environment variables:
#   DATABASE_URL - PostgreSQL connection string (used to derive temp DB connection)

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <backup_file>"
  echo ""
  echo "  Restores the backup to a temporary database, validates table"
  echo "  presence and row counts, then drops the temporary database."
  exit 1
fi

BACKUP_FILE="$1"
TEMP_DB="selva_verify_$(date +%s)"

if [ ! -f "${BACKUP_FILE}" ]; then
  echo "[verify] ERROR: Backup file not found: ${BACKUP_FILE}"
  exit 1
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "[verify] ERROR: DATABASE_URL is not set"
  exit 1
fi

# Verify required tools
for cmd in psql pg_restore; do
  if ! command -v "${cmd}" &>/dev/null; then
    echo "[verify] ERROR: ${cmd} not found in PATH"
    exit 1
  fi
done

# Extract base URL without database name
BASE_URL=$(echo "${DATABASE_URL}" | sed 's|/[^/]*$||')

# Cleanup function to ensure temp DB is dropped on exit
cleanup() {
  echo "[verify] Cleaning up temporary database: ${TEMP_DB}"
  psql "${DATABASE_URL}" -c "DROP DATABASE IF EXISTS ${TEMP_DB};" 2>/dev/null || true
}
trap cleanup EXIT

echo "[verify] Creating temporary database: ${TEMP_DB}"
psql "${DATABASE_URL}" -c "CREATE DATABASE ${TEMP_DB};"

TEMP_URL="${BASE_URL}/${TEMP_DB}"

echo "[verify] Restoring backup to temporary database..."
pg_restore "${BACKUP_FILE}" \
  --dbname="${TEMP_URL}" \
  --no-owner \
  --no-privileges \
  --single-transaction 2>/dev/null

echo "[verify] Validating tables..."
TABLES=$(psql "${TEMP_URL}" -t -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;")

echo "[verify] Tables found:"
echo "${TABLES}" | grep -v '^\s*$' | while read -r table; do
  table=$(echo "${table}" | xargs)  # trim whitespace
  if [ -n "${table}" ]; then
    COUNT=$(psql "${TEMP_URL}" -t -c "SELECT count(*) FROM \"${table}\";" | tr -d ' ')
    printf "  %-30s %s rows\n" "${table}" "${COUNT}"
  fi
done

# Verify expected tables exist (from 0000_initial_schema.py migration)
EXPECTED_TABLES="agents approval_requests compute_token_ledger departments swarm_tasks"
MISSING=""
for expected in ${EXPECTED_TABLES}; do
  if ! echo "${TABLES}" | grep -q "${expected}"; then
    MISSING="${MISSING} ${expected}"
  fi
done

# Also check for alembic_version table (indicates migrations ran)
if echo "${TABLES}" | grep -q "alembic_version"; then
  ALEMBIC_HEAD=$(psql "${TEMP_URL}" -t -c "SELECT version_num FROM alembic_version;" | xargs)
  echo "[verify] Alembic version: ${ALEMBIC_HEAD}"
fi

# The trap will handle cleanup

if [ -n "${MISSING}" ]; then
  echo "[verify] FAILED: Missing expected tables:${MISSING}"
  exit 1
fi

echo "[verify] Backup verification PASSED"

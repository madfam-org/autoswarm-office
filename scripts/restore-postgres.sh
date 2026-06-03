#!/usr/bin/env bash
set -euo pipefail

# Postgres restore script for Selva Office
# Restores a custom-format dump created by backup-postgres.sh.
#
# Usage: ./scripts/restore-postgres.sh <backup_file> [--skip-migrations] [--force]
#
# Environment variables:
#   DATABASE_URL - PostgreSQL connection string (required)
#
# Options:
#   --skip-migrations  Skip Alembic migration step after restore
#   --force            Skip confirmation prompt

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SKIP_MIGRATIONS=false
FORCE=false
BACKUP_FILE=""

# Parse arguments
for arg in "$@"; do
  case "${arg}" in
    --skip-migrations) SKIP_MIGRATIONS=true ;;
    --force) FORCE=true ;;
    -*) echo "[restore] ERROR: Unknown option: ${arg}"; exit 1 ;;
    *) BACKUP_FILE="${arg}" ;;
  esac
done

if [ -z "${BACKUP_FILE}" ]; then
  echo "Usage: $0 <backup_file> [--skip-migrations] [--force]"
  echo ""
  echo "  backup_file       Path to .dump file (from backup-postgres.sh)"
  echo "  --skip-migrations Skip Alembic migration after restore"
  echo "  --force           Skip confirmation prompt"
  exit 1
fi

if [ ! -f "${BACKUP_FILE}" ]; then
  echo "[restore] ERROR: Backup file not found: ${BACKUP_FILE}"
  exit 1
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "[restore] ERROR: DATABASE_URL is not set"
  exit 1
fi

# Verify pg_restore is available
if ! command -v pg_restore &>/dev/null; then
  echo "[restore] ERROR: pg_restore not found in PATH"
  exit 1
fi

FILESIZE=$(stat -f%z "${BACKUP_FILE}" 2>/dev/null || stat --printf="%s" "${BACKUP_FILE}" 2>/dev/null || echo "unknown")
echo "[restore] Backup file: ${BACKUP_FILE} (${FILESIZE} bytes)"
echo "[restore] Target database: ${DATABASE_URL%%@*}@..."
echo "[restore] WARNING: This will overwrite the current database contents!"

if [ "${FORCE}" != "true" ]; then
  read -p "[restore] Continue? (y/N) " -r
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "[restore] Aborted"
    exit 0
  fi
fi

echo "[restore] Starting PostgreSQL restore at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

pg_restore "${BACKUP_FILE}" \
  --dbname="${DATABASE_URL}" \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  --single-transaction

echo "[restore] Database restored successfully"

# Run Alembic migrations to ensure schema is up-to-date
if [ "${SKIP_MIGRATIONS}" != "true" ]; then
  echo "[restore] Running Alembic migrations to ensure schema is current..."
  cd "${PROJECT_ROOT}/apps/nexus-api"
  if command -v uv &>/dev/null; then
    uv run alembic upgrade head
  else
    echo "[restore] WARNING: uv not found, skipping Alembic migrations"
    echo "[restore] Run manually: cd apps/nexus-api && uv run alembic upgrade head"
  fi
else
  echo "[restore] Skipping Alembic migrations (--skip-migrations)"
fi

echo "[restore] Restore complete at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

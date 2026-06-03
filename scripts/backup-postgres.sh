#!/usr/bin/env bash
set -euo pipefail

# Postgres backup script for Selva Office
# Creates a compressed custom-format dump and optionally uploads to S3.
#
# Usage: ./scripts/backup-postgres.sh [--upload]
#
# Environment variables:
#   DATABASE_URL     - PostgreSQL connection string (required)
#   S3_BUCKET        - S3 bucket for remote backup (optional, required with --upload)
#   BACKUP_DIR       - Local backup directory (default: ./backups)
#   RETENTION_DAILY  - Number of daily backups to retain (default: 30)
#   RETENTION_WEEKLY - Number of weekly backups to retain (default: 12)

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAILY="${RETENTION_DAILY:-30}"
RETENTION_WEEKLY="${RETENTION_WEEKLY:-12}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DAY_OF_WEEK=$(date +%u)
FILENAME="selva_${TIMESTAMP}.dump"
FILEPATH="${BACKUP_DIR}/${FILENAME}"

mkdir -p "${BACKUP_DIR}"

echo "[backup] Starting PostgreSQL backup at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Validate DATABASE_URL
if [ -z "${DATABASE_URL:-}" ]; then
  echo "[backup] ERROR: DATABASE_URL is not set"
  exit 1
fi

# Verify pg_dump is available
if ! command -v pg_dump &>/dev/null; then
  echo "[backup] ERROR: pg_dump not found in PATH"
  exit 1
fi

# Create the backup
pg_dump "${DATABASE_URL}" \
  --format=custom \
  --compress=9 \
  --no-owner \
  --no-privileges \
  --file="${FILEPATH}"

FILESIZE=$(stat -f%z "${FILEPATH}" 2>/dev/null || stat --printf="%s" "${FILEPATH}" 2>/dev/null || echo "unknown")
echo "[backup] Backup created: ${FILEPATH} (${FILESIZE} bytes)"

# Validate the backup is not empty
if [ "${FILESIZE}" = "0" ] || [ "${FILESIZE}" = "unknown" ]; then
  echo "[backup] WARNING: Backup file may be empty or size could not be determined"
fi

# Upload to S3 if requested
if [ "${1:-}" = "--upload" ]; then
  if [ -z "${S3_BUCKET:-}" ]; then
    echo "[backup] ERROR: --upload requested but S3_BUCKET is not set"
    exit 1
  fi

  if ! command -v aws &>/dev/null; then
    echo "[backup] ERROR: aws CLI not found in PATH"
    exit 1
  fi

  # Determine S3 prefix (weekly on Sundays, daily otherwise)
  if [ "${DAY_OF_WEEK}" = "7" ]; then
    S3_PREFIX="weekly"
  else
    S3_PREFIX="daily"
  fi

  aws s3 cp "${FILEPATH}" "s3://${S3_BUCKET}/selva/${S3_PREFIX}/${FILENAME}"
  echo "[backup] Uploaded to s3://${S3_BUCKET}/selva/${S3_PREFIX}/${FILENAME}"

  # Rotate remote weekly backups
  if [ "${S3_PREFIX}" = "weekly" ]; then
    echo "[backup] Rotating remote weekly backups (keeping ${RETENTION_WEEKLY})"
    aws s3 ls "s3://${S3_BUCKET}/selva/weekly/" \
      | sort -r \
      | tail -n +"$((RETENTION_WEEKLY + 1))" \
      | awk '{print $4}' \
      | while read -r key; do
          aws s3 rm "s3://${S3_BUCKET}/selva/weekly/${key}"
        done
  fi
fi

# Rotate old local backups
echo "[backup] Rotating old local backups (keeping ${RETENTION_DAILY} daily)"
# shellcheck disable=SC2012
ls -t "${BACKUP_DIR}"/selva_*.dump 2>/dev/null | tail -n +"$((RETENTION_DAILY + 1))" | xargs -r rm -f

echo "[backup] Backup complete at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

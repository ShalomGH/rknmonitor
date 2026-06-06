#!/usr/bin/env bash
# rknmon backup script — pg_dump + gzip with rotation

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/rknmon}"
KEEP_DAYS="${KEEP_DAYS:-30}"
DATABASE_URL="${DATABASE_URL:-"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="rknmon_${TIMESTAMP}.sql.gz"
OUT="${BACKUP_DIR}/${FILENAME}"

mkdir -p "${BACKUP_DIR}"

if [[ -n "${DATABASE_URL}" ]]; then
    pg_dump "${DATABASE_URL}" | gzip > "${OUT}"
else
    echo "ERROR: DATABASE_URL is not set" >&2
    exit 1
fi

SIZE=$(du -h "${OUT}" | cut -f1)
echo "Backup created: ${OUT} (${SIZE})"

# Rotate old backups
DELETED=$(find "${BACKUP_DIR}" -name 'rknmon_*.sql.gz' -mtime +"${KEEP_DAYS}" -delete -print | wc -l)
echo "Rotated ${DELETED} backups older than ${KEEP_DAYS} days"

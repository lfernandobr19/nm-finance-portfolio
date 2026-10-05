#!/usr/bin/env bash
# Daily fiidesk Postgres backup (runs as user; uses passwordless `sudo docker`).
# Writes to $BACKUP_DIR (default $HOME/backups/fiidesk), retains N days.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/fiidesk}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
CONTAINER="${CONTAINER:-deploy-postgres-1}"

mkdir -p "$BACKUP_DIR"

STAMP="$(date +%Y%m%d_%H%M%S)"
FILE="$BACKUP_DIR/fiidesk_${STAMP}.sql.gz"

# Dump from inside the container (pg_dump is not installed on the host).
sudo docker exec "$CONTAINER" pg_dump -U fiidesk fiidesk | gzip > "$FILE"

# Sanity: refuse to keep an empty/truncated dump.
if [ ! -s "$FILE" ]; then
  echo "ERROR: backup $FILE is empty" >&2
  rm -f "$FILE"
  exit 1
fi

# Retention.
find "$BACKUP_DIR" -name 'fiidesk_*.sql.gz' -mtime "+${RETENTION_DAYS}" -delete

echo "Backup written to $FILE ($(du -h "$FILE" | cut -f1))"

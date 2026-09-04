#!/usr/bin/env bash
# Nightly backup of karly.db — keeps the last 14 copies.
# Runs as the same user that runs karly.service (marcus on OptiPlex).
set -euo pipefail

DB="${HOME}/Karly/karly.db"
BACKUP_DIR="${HOME}/karly-backups"
STAMP=$(date +%Y-%m-%d)
DEST="${BACKUP_DIR}/karly-${STAMP}.db"

mkdir -p "$BACKUP_DIR"

if [[ ! -f "$DB" ]]; then
    echo "karly-backup: $DB not found, skipping." >&2
    exit 0
fi

# sqlite3 .backup is safe to run while the bot is live.
sqlite3 "$DB" ".backup '${DEST}'"
echo "karly-backup: wrote ${DEST} ($(du -h "$DEST" | cut -f1))"

# Prune backups older than 14 days.
find "$BACKUP_DIR" -name 'karly-*.db' -mtime +14 -delete

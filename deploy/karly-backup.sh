#!/usr/bin/env bash
# Nightly backup of every Karly database found on this host — keeps the last 14
# copies of each. Each bot instance has its own file (karly_german.db /
# karly_english.db), so we back up all of them rather than assuming a single DB.
# Runs as the same user that runs the karly service(s).
set -euo pipefail

BACKUP_DIR="${HOME}/karly-backups"
STAMP=$(date +%Y-%m-%d)
mkdir -p "$BACKUP_DIR"

# Candidate locations where a Karly checkout (and its DB) may live on this host.
CHECKOUTS=("${HOME}/Karly" "${HOME}/PycharmProjects/Karly")

found_any=0
for dir in "${CHECKOUTS[@]}"; do
    [[ -d "$dir" ]] || continue
    # Match per-language DBs (karly_german.db, karly_english.db) and any legacy
    # single karly.db, but skip archived/journal files.
    for db in "$dir"/karly_*.db "$dir"/karly.db; do
        [[ -f "$db" ]] || continue
        found_any=1
        name=$(basename "$db" .db)
        dest="${BACKUP_DIR}/${name}-${STAMP}.db"
        # sqlite3 .backup is safe to run while the bot is live.
        sqlite3 "$db" ".backup '${dest}'"
        echo "karly-backup: wrote ${dest} ($(du -h "$dest" | cut -f1))"
    done
done

if [[ "$found_any" -eq 0 ]]; then
    echo "karly-backup: no Karly databases found, skipping." >&2
    exit 0
fi

# Prune backups older than 14 days.
find "$BACKUP_DIR" -name 'karly*-*.db' -mtime +14 -delete

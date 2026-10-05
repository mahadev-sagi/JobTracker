#!/usr/bin/env bash
# Daily database backup (cron, see bootstrap.sh). Keeps BACKUP_KEEP archives
# in BACKUP_DIR and optionally copies each to BACKUP_S3_URI.
#
# A backup on the same disk survives mistakes, not a lost instance. Set
# BACKUP_S3_URI, or copy the files elsewhere now and then.
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DEPLOY_DIR"
# shellcheck disable=SC1091
set -a; source .env; set +a

dir="${BACKUP_DIR:-/var/backups/jobtracker}"
keep="${BACKUP_KEEP:-14}"
mkdir -p "$dir"
chmod 700 "$dir"
file="$dir/jobtracker-$(date -u +%Y%m%dT%H%M%SZ).dump"

# Custom format: compressed, and restorable table by table.
docker compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    --format=custom --no-owner --no-acl > "$file.partial"
# An archive pg_restore cannot list is not a backup.
docker compose exec -T db pg_restore --list < "$file.partial" > /dev/null
mv "$file.partial" "$file"
chmod 600 "$file"

if [ -n "${BACKUP_S3_URI:-}" ]; then
    aws s3 cp --only-show-errors "$file" "${BACKUP_S3_URI%/}/"
fi

# Newest first; delete everything past the first $keep.
ls -1t "$dir"/jobtracker-*.dump | tail -n +"$((keep + 1))" | xargs -r rm -f
echo "Backup written: $file"

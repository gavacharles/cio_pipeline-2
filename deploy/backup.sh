#!/usr/bin/env bash
# Nightly consistent copy of the participant database (safe while the app is running),
# keeping 30 days. Copy /srv/cio_backups off the server too (e.g. rclone to cloud storage).
set -euo pipefail
DB="${CIO_DB:-/srv/cio_pipeline-2/data/market/exchange.sqlite}"
DEST=/srv/cio_backups
mkdir -p "$DEST"
STAMP=$(date +%Y-%m-%d)
sqlite3 "$DB" ".backup '$DEST/exchange-$STAMP.sqlite'"
gzip -f "$DEST/exchange-$STAMP.sqlite"
find "$DEST" -name 'exchange-*.sqlite.gz' -mtime +30 -delete
echo "backup ok: $DEST/exchange-$STAMP.sqlite.gz"

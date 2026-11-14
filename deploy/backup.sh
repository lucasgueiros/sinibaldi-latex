#!/usr/bin/env bash
# Backup diário do esquema do editor no banco. Agendado pelo bootstrap em /etc/cron.d/<instância>:
#   backup.sh [/srv/<instância>]     (padrão: /srv/sinibaldi)
#
# O esquema também entra no backup do site da Academia (pg_dump do banco inteiro), mas este dump,
# só do esquema, é o que se restaura sem tocar no site:
#   pg_restore --no-owner --role=<DB_USER> -d <DB_NAME> --clean --if-exists -n <DB_SCHEMA> db-AAAAMMDD-HHMM.dump
# Não há mídias: os dados do scan (dados/) vêm do checkout de trabalho e o cache/ é regenerável.
set -euo pipefail
BASE="${1:-/srv/sinibaldi}"
INSTANCE="$(basename "$BASE")"
set -a; source "/etc/$INSTANCE/env"; set +a
DEST="$BASE/backups"
STAMP=$(date +%Y%m%d-%H%M)
mkdir -p "$DEST"
PGPASSWORD="${DB_PASSWORD:-}" pg_dump -h "${DB_HOST:-localhost}" -p "${DB_PORT:-5432}" -U "$DB_USER" \
    -Fc -n "${DB_SCHEMA:-sinibaldi}" "$DB_NAME" > "$DEST/db-$STAMP.dump.tmp"
mv "$DEST/db-$STAMP.dump.tmp" "$DEST/db-$STAMP.dump"
find "$DEST" -type f -name 'db-*.dump' -mtime +"${BACKUP_RETENTION_DAYS:-30}" -delete

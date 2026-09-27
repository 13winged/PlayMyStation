#!/bin/sh
# Ежедневный бэкап PostgreSQL (pg_dump, custom format).
# Запускается cron'ом из backup-сервиса в docker-compose.
# Переменные: DATABASE_URL (обязательно), BACKUP_DIR (default /backups),
# BACKUP_RETENTION_DAYS (default 7).
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"

if [ -z "${DATABASE_URL:-}" ]; then
  echo "pg_backup: DATABASE_URL is not set" >&2
  exit 1
fi

# pg_dump не понимает SQLAlchemy-схемы вида postgresql+asyncpg://
CLEAN_URL="$(printf '%s' "$DATABASE_URL" \
  | sed 's#^postgresql+asyncpg://#postgresql://#; s#^postgresql+psycopg2://#postgresql://#')"

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
FILE="$BACKUP_DIR/playmystation-$STAMP.dump"

pg_dump "$CLEAN_URL" -Fc -f "$FILE"
echo "pg_backup: wrote $FILE ($(du -h "$FILE" | cut -f1))"

# Ротация: удаляем дампы старше RETENTION_DAYS суток.
# shellcheck disable=SC2086
find "$BACKUP_DIR" -maxdepth 1 -name 'playmystation-*.dump' -mtime +"$RETENTION_DAYS" -delete
echo "pg_backup: done, backups kept:"
ls -1 "$BACKUP_DIR"/playmystation-*.dump 2>/dev/null | tail -10 || true

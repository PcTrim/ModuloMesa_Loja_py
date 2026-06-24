#!/bin/bash
# Backup antes de atualizar LojaOnline em producao.
# Uso: cd /var/www/html/LojaOnline && sudo bash deploy/backup_production.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"
TS="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${HOME}/lojaonline_backups"
mkdir -p "$BACKUP_DIR"

echo "==> Backup em $BACKUP_DIR (timestamp $TS)"

if [ -f .env ]; then
  cp .env "$BACKUP_DIR/.env.backup-$TS"
  echo "OK: .env"
else
  echo "AVISO: .env nao encontrado em $APP_DIR"
fi

DB_NAME="${MYSQL_DATABASE:-loja2001}"
if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a
  source .env 2>/dev/null || true
  set +a
  DB_NAME="${MYSQL_DATABASE:-loja2001}"
fi

if command -v mysqldump >/dev/null 2>&1 && [ -n "${MYSQL_USER:-}" ]; then
  mysqldump -h "${MYSQL_HOST:-127.0.0.1}" -P "${MYSQL_PORT:-3306}" \
    -u "$MYSQL_USER" -p"${MYSQL_PASSWORD:-}" "$DB_NAME" \
    > "$BACKUP_DIR/backup_${DB_NAME}_$TS.sql" 2>/dev/null || \
    mysqldump -h "${MYSQL_HOST:-127.0.0.1}" -P "${MYSQL_PORT:-3306}" \
      -u "$MYSQL_USER" -p "$DB_NAME" \
      > "$BACKUP_DIR/backup_${DB_NAME}_$TS.sql"
  echo "OK: mysqldump $DB_NAME"
else
  echo "AVISO: mysqldump ignorado (defina MYSQL_* no .env ou rode manualmente)"
fi

tar czf "$BACKUP_DIR/backup_LojaOnline_$TS.tar.gz" \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  -C "$(dirname "$APP_DIR")" "$(basename "$APP_DIR")"

echo "OK: $BACKUP_DIR/backup_LojaOnline_$TS.tar.gz"
echo "==> Backup concluido"

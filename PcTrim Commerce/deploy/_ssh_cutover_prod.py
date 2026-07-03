#!/usr/bin/env python3
"""Cutover produção: loja2001 -> pctrim_commerce (altera .env + restart)."""
from __future__ import annotations

import base64
import os
import sys
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import paramiko

REMOTE_ENV = "/var/www/html/LojaOnline/.env"
PROD_DIR = "/var/www/html/LojaOnline"

CUTOVER_SCRIPT = textwrap.dedent(r"""
set -euo pipefail
BACKUP_DIR=$(ls -dt "$HOME"/mysql_migration_* 2>/dev/null | head -1)
CREDS_FILE="$BACKUP_DIR/mysql_users_credentials.env"
TS=$(date +%Y%m%d_%H%M%S)

[ -f "$CREDS_FILE" ] || { echo "ERRO: $CREDS_FILE ausente"; exit 1; }
source "$CREDS_FILE"

set -a
source __REMOTE_ENV__
set +a

CNF="/tmp/.my.cnf.cutover.$$"
cat > "$CNF" <<EOF
[client]
host=${MYSQL_HOST:-127.0.0.1}
port=${MYSQL_PORT:-3306}
user=${MYSQL_USER}
password=${MYSQL_PASSWORD}
EOF
chmod 600 "$CNF"

DB_SRC="${MYSQL_DATABASE:-loja2001}"
SYNC="$BACKUP_DIR/${DB_SRC}_cutover_pre_switch_${TS}.sql"

echo "=== 1. Backup .env antes do cutover ==="
cp __REMOTE_ENV__ "$BACKUP_DIR/.env.antes_cutover_${TS}"
cp __REMOTE_ENV__ ~/lojaonline_backups/.env.backup-cutover-${TS} 2>/dev/null || \
  mkdir -p ~/lojaonline_backups && cp __REMOTE_ENV__ ~/lojaonline_backups/.env.backup-cutover-${TS}

echo "=== 2. Sync final loja2001 -> pctrim_commerce ==="
MYSQLDUMP_EXTRA=""
if mysqldump --help 2>&1 | grep -q column-statistics; then MYSQLDUMP_EXTRA="--column-statistics=0"; fi
mysqldump --defaults-extra-file="$CNF" \
  --single-transaction --routines --triggers --events --hex-blob \
  --add-drop-table --default-character-set=utf8mb4 --set-gtid-purged=OFF \
  $MYSQLDUMP_EXTRA "$DB_SRC" > "$SYNC"
ls -lh "$SYNC"
sed '/^USE `/d; /^CREATE DATABASE `/d' "$SYNC" | mysql --defaults-extra-file="$CNF" -D pctrim_commerce

echo "=== 3. Atualizar .env producao ==="
sed -i "s/^MYSQL_DATABASE=.*/MYSQL_DATABASE=pctrim_commerce/" __REMOTE_ENV__
sed -i "s/^MYSQL_USER=.*/MYSQL_USER=pctrim_prod/" __REMOTE_ENV__
sed -i "s/^MYSQL_PASSWORD=.*/MYSQL_PASSWORD=$PCTrim_PROD_PASSWORD/" __REMOTE_ENV__
grep -E '^ENVIRONMENT=|^MYSQL_(HOST|PORT|DATABASE|USER)=' __REMOTE_ENV__ | sed 's/PASSWORD=.*/PASSWORD=***/'

echo "=== 4. Reiniciar lojaonline ==="
systemctl restart lojaonline
sleep 2
systemctl is-active lojaonline

echo "=== 5. Teste conexao pctrim_prod ==="
CNF_P="/tmp/.my.cnf.prod.$$"
cat > "$CNF_P" <<EOF
[client]
host=${MYSQL_HOST}
port=${MYSQL_PORT}
user=pctrim_prod
password=$PCTrim_PROD_PASSWORD
EOF
chmod 600 "$CNF_P"
mysql --defaults-extra-file="$CNF_P" -D pctrim_commerce -e "SELECT COUNT(*) AS usuarios FROM usuarios;"
curl -sI http://127.0.0.1:8001/login | head -3

rm -f "$CNF" "$CNF_P"

echo "=== CUTOVER CONCLUIDO ==="
echo "Producao agora usa pctrim_commerce + pctrim_prod"
echo "loja2001 mantido como fallback (nao apagado)"
echo "Rollback: cp $BACKUP_DIR/.env.antes_cutover_${TS} __REMOTE_ENV__ && systemctl restart lojaonline"
""").replace("__REMOTE_ENV__", REMOTE_ENV)


def filezilla_creds() -> tuple[str, int, str, str]:
    fz = Path(os.environ.get("APPDATA", "")) / "FileZilla" / "sitemanager.xml"
    root = ET.parse(fz).getroot()
    for srv in root.findall(".//Server"):
        name = (srv.findtext("Name") or "").lower()
        if "hostinguer" in name or "hostinger" in name:
            enc = srv.find("Pass")
            pwd = ""
            if enc is not None and enc.text:
                pwd = base64.b64decode(enc.text).decode("utf-8", errors="replace")
            return (
                srv.findtext("Host") or "",
                int(srv.findtext("Port") or "22"),
                srv.findtext("User") or "",
                pwd,
            )
    raise RuntimeError("Hostinger não encontrado no FileZilla")


def main() -> int:
    host, port, user, pwd = filezilla_creds()
    print(f"==> Cutover producao -> pctrim_commerce ({user}@{host})")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=pwd, timeout=30)
    try:
        _, stdout, stderr = client.exec_command(CUTOVER_SCRIPT, timeout=600)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        print(out)
        if err.strip():
            print("STDERR:", err, file=sys.stderr)
        code = stdout.channel.recv_exit_status()
        return code
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())

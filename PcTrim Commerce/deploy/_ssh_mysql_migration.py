#!/usr/bin/env python3
"""Executa fases da migração MySQL no servidor Hostinger via SSH."""
from __future__ import annotations

import argparse
import base64
import os
import sys
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import paramiko

REMOTE_ENV = "/var/www/html/LojaOnline/.env"
APP_DIR = "/var/www/html/LojaOnline"


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


def ssh_exec(client: paramiko.SSHClient, cmd: str, timeout: int = 600) -> tuple[int, str, str]:
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


PHASE0_SCRIPT = (
    textwrap.dedent(r"""
set -euo pipefail
export MIG_TS=$(date +%Y%m%d_%H%M%S)
export BACKUP_DIR="$HOME/mysql_migration_${MIG_TS}"
mkdir -p "$BACKUP_DIR"
echo "BACKUP_DIR=$BACKUP_DIR" | tee "$BACKUP_DIR/migration_vars.env"

if [ -f __REMOTE_ENV__ ]; then
  cp __REMOTE_ENV__ "$BACKUP_DIR/.env.producao.antes_cutover"
  echo "OK: backup .env"
else
  echo "ERRO: .env nao encontrado" >&2
  exit 1
fi

set -a
source __REMOTE_ENV__
set +a

MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:?MYSQL_USER ausente no .env}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:?MYSQL_PASSWORD ausente no .env}"
DB_SRC="${MYSQL_DATABASE:-loja2001}"

echo "=== Pré-check ==="
df -h "$HOME" /var/lib/mysql 2>/dev/null || df -h "$HOME"
mysql --version 2>/dev/null || echo "AVISO: mysql client path"
echo "Banco origem: $DB_SRC"
echo "Host: $MYSQL_HOST:$MYSQL_PORT User: $MYSQL_USER"

CNF="$BACKUP_DIR/.my.cnf.$$"
cat > "$CNF" <<EOF
[client]
host=$MYSQL_HOST
port=$MYSQL_PORT
user=$MYSQL_USER
password=$MYSQL_PASSWORD
EOF
chmod 600 "$CNF"

mysql --defaults-extra-file="$CNF" -e "
SELECT table_schema,
       ROUND(SUM(data_length + index_length) / 1024 / 1024, 1) AS mb
FROM information_schema.tables
WHERE table_schema = '$DB_SRC'
GROUP BY table_schema;" || true

echo "=== FASE 0: mysqldump + gzip ==="
MYSQLDUMP_EXTRA=""
if mysqldump --help 2>&1 | grep -q column-statistics; then
  MYSQLDUMP_EXTRA="--column-statistics=0"
fi
mysqldump --defaults-extra-file="$CNF" \
  --single-transaction \
  --routines \
  --triggers \
  --events \
  --hex-blob \
  --default-character-set=utf8mb4 \
  --set-gtid-purged=OFF \
  $MYSQLDUMP_EXTRA \
  "$DB_SRC" | gzip > "$BACKUP_DIR/${DB_SRC}_PRE_MIGRACAO_${MIG_TS}.sql.gz"

DUMP_GZ="$BACKUP_DIR/${DB_SRC}_PRE_MIGRACAO_${MIG_TS}.sql.gz"
gzip -t "$DUMP_GZ"
ls -lh "$DUMP_GZ"
rm -f "$CNF"

echo "=== FASE 0 CONCLUIDA ==="
echo "BACKUP_DIR=$BACKUP_DIR"
echo "DUMP_GZ=$DUMP_GZ"
echo "DB_SRC=$DB_SRC"
""")
    .replace("__REMOTE_ENV__", REMOTE_ENV)
)

PHASE1_SCRIPT = (
    textwrap.dedent(r"""
set -euo pipefail

set -a
source __REMOTE_ENV__
set +a

MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:?MYSQL_USER ausente no .env}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:?MYSQL_PASSWORD ausente no .env}"

CNF="/tmp/.my.cnf.migration.$$"
cat > "$CNF" <<EOF
[client]
host=$MYSQL_HOST
port=$MYSQL_PORT
user=$MYSQL_USER
password=$MYSQL_PASSWORD
EOF
chmod 600 "$CNF"

echo "=== FASE 1: criar bancos destino ==="
echo "Host: $MYSQL_HOST:$MYSQL_PORT User: $MYSQL_USER"

mysql --defaults-extra-file="$CNF" <<'SQL'
CREATE DATABASE IF NOT EXISTS pctrim_commerce
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS pctrim_commerce_hml
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
SQL

echo "=== Bancos criados ==="
mysql --defaults-extra-file="$CNF" -e "SHOW DATABASES LIKE 'pctrim_commerce%';"

echo "=== Charset/collation ==="
mysql --defaults-extra-file="$CNF" -e "
SELECT schema_name, default_character_set_name, default_collation_name
FROM information_schema.schemata
WHERE schema_name IN ('pctrim_commerce','pctrim_commerce_hml','loja2001')
ORDER BY schema_name;"

rm -f "$CNF"

echo "=== FASE 1 CONCLUIDA ==="
echo "App continua em loja2001 (.env inalterado)"
""")
    .replace("__REMOTE_ENV__", REMOTE_ENV)
)

PHASE2_SCRIPT = (
    textwrap.dedent(r"""
set -euo pipefail

BACKUP_DIR=$(ls -dt "$HOME"/mysql_migration_* 2>/dev/null | head -1)
if [ -z "$BACKUP_DIR" ] || [ ! -d "$BACKUP_DIR" ]; then
  echo "ERRO: BACKUP_DIR nao encontrado. Execute Fase 0 primeiro." >&2
  exit 1
fi
echo "BACKUP_DIR=$BACKUP_DIR"

set -a
source __REMOTE_ENV__
set +a

MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:?MYSQL_USER ausente no .env}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:?MYSQL_PASSWORD ausente no .env}"
DB_SRC="${MYSQL_DATABASE:-loja2001}"

export MIG_TS=$(date +%Y%m%d_%H%M%S)
export DUMP_FILE="$BACKUP_DIR/${DB_SRC}_full_${MIG_TS}.sql"

CNF="/tmp/.my.cnf.migration.$$"
cat > "$CNF" <<EOF
[client]
host=$MYSQL_HOST
port=$MYSQL_PORT
user=$MYSQL_USER
password=$MYSQL_PASSWORD
EOF
chmod 600 "$CNF"

echo "=== FASE 2: dump completo de $DB_SRC ==="
echo "Host: $MYSQL_HOST:$MYSQL_PORT User: $MYSQL_USER"
echo "Arquivo: $DUMP_FILE"

MYSQLDUMP_EXTRA=""
if mysqldump --help 2>&1 | grep -q column-statistics; then
  MYSQLDUMP_EXTRA="--column-statistics=0"
fi

mysqldump --defaults-extra-file="$CNF" \
  --single-transaction \
  --routines \
  --triggers \
  --events \
  --hex-blob \
  --add-drop-table \
  --default-character-set=utf8mb4 \
  --set-gtid-purged=OFF \
  $MYSQLDUMP_EXTRA \
  "$DB_SRC" > "$DUMP_FILE"

echo "=== Metadados do dump ==="
wc -l "$DUMP_FILE"
ls -lh "$DUMP_FILE"
grep -c "^CREATE TABLE" "$DUMP_FILE" || true
grep -c "^CREATE.*TRIGGER" "$DUMP_FILE" || true
grep -c "^CREATE.*VIEW" "$DUMP_FILE" || true
grep -c "^CREATE.*PROCEDURE\|^CREATE.*FUNCTION" "$DUMP_FILE" || true

echo "DUMP_FILE=$DUMP_FILE" >> "$BACKUP_DIR/migration_vars.env"
echo "DB_SRC=$DB_SRC" >> "$BACKUP_DIR/migration_vars.env"

rm -f "$CNF"

echo "=== FASE 2 CONCLUIDA ==="
echo "DUMP_FILE=$DUMP_FILE"
echo "App continua em loja2001 (.env inalterado)"
""")
    .replace("__REMOTE_ENV__", REMOTE_ENV)
)

PHASE3_SCRIPT = (
    textwrap.dedent(r"""
set -euo pipefail

BACKUP_DIR=$(ls -dt "$HOME"/mysql_migration_* 2>/dev/null | head -1)
if [ -z "$BACKUP_DIR" ] || [ ! -d "$BACKUP_DIR" ]; then
  echo "ERRO: BACKUP_DIR nao encontrado." >&2
  exit 1
fi

DUMP_FILE=""
if [ -f "$BACKUP_DIR/migration_vars.env" ]; then
  # shellcheck disable=SC1090
  source "$BACKUP_DIR/migration_vars.env"
fi
if [ -z "$DUMP_FILE" ] || [ ! -f "$DUMP_FILE" ]; then
  DUMP_FILE=$(ls -t "$BACKUP_DIR"/*_full_*.sql 2>/dev/null | head -1)
fi
if [ -z "$DUMP_FILE" ] || [ ! -f "$DUMP_FILE" ]; then
  echo "ERRO: DUMP_FILE nao encontrado. Execute Fase 2 primeiro." >&2
  exit 1
fi
echo "BACKUP_DIR=$BACKUP_DIR"
echo "DUMP_FILE=$DUMP_FILE"

set -a
source __REMOTE_ENV__
set +a

MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:?MYSQL_USER ausente no .env}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:?MYSQL_PASSWORD ausente no .env}"
DB_SRC="${MYSQL_DATABASE:-loja2001}"

CNF="/tmp/.my.cnf.migration.$$"
cat > "$CNF" <<EOF
[client]
host=$MYSQL_HOST
port=$MYSQL_PORT
user=$MYSQL_USER
password=$MYSQL_PASSWORD
EOF
chmod 600 "$CNF"

TABELAS_ORIGEM=$(mysql --defaults-extra-file="$CNF" -N -e "
SELECT COUNT(*) FROM information_schema.tables
WHERE table_schema='$DB_SRC' AND table_type='BASE TABLE';")
echo "Tabelas em $DB_SRC (antes): $TABELAS_ORIGEM"

importar_dump() {
  local BANCO="$1"
  case "$BANCO" in
    pctrim_commerce|pctrim_commerce_hml) ;;
    *)
      echo "ERRO: banco nao permitido: $BANCO" >&2
      exit 1
      ;;
  esac
  echo ""
  echo "=========================================="
  echo "  IMPORT em: $BANCO"
  echo "  Arquivo: $DUMP_FILE"
  echo "  USE/CREATE DATABASE removidos do stream"
  echo "  loja2001 permanece intocado"
  echo "=========================================="
  sed '/^USE `/d; /^CREATE DATABASE `/d' "$DUMP_FILE" \
    | mysql --defaults-extra-file="$CNF" -D "$BANCO"
  echo "OK: import concluido em $BANCO"
}

echo "=== FASE 3: importacao segura ==="
importar_dump pctrim_commerce
importar_dump pctrim_commerce_hml

echo ""
echo "=== Verificacao pos-import ==="
mysql --defaults-extra-file="$CNF" -e "
SELECT table_schema, COUNT(*) AS tabelas
FROM information_schema.tables
WHERE table_schema IN ('$DB_SRC','pctrim_commerce','pctrim_commerce_hml')
  AND table_type='BASE TABLE'
GROUP BY table_schema
ORDER BY table_schema;"

TABELAS_ORIGEM_DEPOIS=$(mysql --defaults-extra-file="$CNF" -N -e "
SELECT COUNT(*) FROM information_schema.tables
WHERE table_schema='$DB_SRC' AND table_type='BASE TABLE';")
if [ "$TABELAS_ORIGEM" != "$TABELAS_ORIGEM_DEPOIS" ]; then
  echo "ERRO: contagem de tabelas em $DB_SRC mudou ($TABELAS_ORIGEM -> $TABELAS_ORIGEM_DEPOIS)" >&2
  exit 1
fi
echo "OK: $DB_SRC inalterado ($TABELAS_ORIGEM_DEPOIS tabelas)"

rm -f "$CNF"

echo "=== FASE 3 CONCLUIDA ==="
echo "App continua em loja2001 (.env inalterado)"
""")
    .replace("__REMOTE_ENV__", REMOTE_ENV)
)

PHASE4_SCRIPT = (
    textwrap.dedent(r"""
set -euo pipefail

BACKUP_DIR=$(ls -dt "$HOME"/mysql_migration_* 2>/dev/null | head -1)
if [ -z "$BACKUP_DIR" ] || [ ! -d "$BACKUP_DIR" ]; then
  echo "ERRO: BACKUP_DIR nao encontrado." >&2
  exit 1
fi
CREDS_FILE="$BACKUP_DIR/mysql_users_credentials.env"
echo "BACKUP_DIR=$BACKUP_DIR"

set -a
source __REMOTE_ENV__
set +a

MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:?MYSQL_USER ausente no .env}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:?MYSQL_PASSWORD ausente no .env}"

CNF="/tmp/.my.cnf.migration.$$"
cat > "$CNF" <<EOF
[client]
host=$MYSQL_HOST
port=$MYSQL_PORT
user=$MYSQL_USER
password=$MYSQL_PASSWORD
EOF
chmod 600 "$CNF"

if [ -f "$CREDS_FILE" ]; then
  # shellcheck disable=SC1090
  source "$CREDS_FILE"
  echo "Reutilizando senhas de $CREDS_FILE"
else
  PCTrim_PROD_PASSWORD=$(openssl rand -base64 24)
  PCTrim_HML_PASSWORD=$(openssl rand -base64 24)
  umask 077
  cat > "$CREDS_FILE" <<EOF
PCTrim_PROD_PASSWORD=$PCTrim_PROD_PASSWORD
PCTrim_HML_PASSWORD=$PCTrim_HML_PASSWORD
EOF
  chmod 600 "$CREDS_FILE"
  echo "Senhas geradas em $CREDS_FILE"
fi

PRIVS="SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES, CREATE TEMPORARY TABLES, LOCK TABLES, EXECUTE, CREATE VIEW, SHOW VIEW, CREATE ROUTINE, ALTER ROUTINE, TRIGGER, EVENT"

echo "=== FASE 4: usuarios e permissoes ==="

for HOST in localhost 127.0.0.1 '%'; do
  mysql --defaults-extra-file="$CNF" -e "
GRANT $PRIVS ON pctrim_commerce.* TO 'pctrim_prod'@'$HOST' IDENTIFIED BY '$PCTrim_PROD_PASSWORD';
GRANT $PRIVS ON pctrim_commerce_hml.* TO 'pctrim_hml'@'$HOST' IDENTIFIED BY '$PCTrim_HML_PASSWORD';"
done
mysql --defaults-extra-file="$CNF" -e "FLUSH PRIVILEGES;"

echo ""
echo "=== GRANTS pctrim_prod ==="
mysql --defaults-extra-file="$CNF" -e "SHOW GRANTS FOR 'pctrim_prod'@'localhost';"

echo ""
echo "=== GRANTS pctrim_hml ==="
mysql --defaults-extra-file="$CNF" -e "SHOW GRANTS FOR 'pctrim_hml'@'localhost';"

CNF_PROD="/tmp/.my.cnf.prod.$$"
cat > "$CNF_PROD" <<EOF
[client]
host=$MYSQL_HOST
port=$MYSQL_PORT
user=pctrim_prod
password=$PCTrim_PROD_PASSWORD
EOF
chmod 600 "$CNF_PROD"

CNF_HML="/tmp/.my.cnf.hml.$$"
cat > "$CNF_HML" <<EOF
[client]
host=$MYSQL_HOST
port=$MYSQL_PORT
user=pctrim_hml
password=$PCTrim_HML_PASSWORD
EOF
chmod 600 "$CNF_HML"

echo ""
echo "=== Teste positivo pctrim_prod -> pctrim_commerce ==="
mysql --defaults-extra-file="$CNF_PROD" -D pctrim_commerce -e "SELECT COUNT(*) AS usuarios FROM usuarios;"

echo ""
echo "=== Teste positivo pctrim_hml -> pctrim_commerce_hml ==="
mysql --defaults-extra-file="$CNF_HML" -D pctrim_commerce_hml -e "SELECT COUNT(*) AS usuarios FROM usuarios;"

echo ""
echo "=== Teste negativo pctrim_hml -> pctrim_commerce (deve falhar) ==="
if mysql --defaults-extra-file="$CNF_HML" -D pctrim_commerce -e "SELECT 1;" 2>/dev/null; then
  echo "ERRO: pctrim_hml conseguiu acessar pctrim_commerce" >&2
  exit 1
else
  echo "OK: acesso negado como esperado"
fi

echo ""
echo "=== Teste negativo pctrim_prod -> pctrim_commerce_hml (deve falhar) ==="
if mysql --defaults-extra-file="$CNF_PROD" -D pctrim_commerce_hml -e "SELECT 1;" 2>/dev/null; then
  echo "ERRO: pctrim_prod conseguiu acessar pctrim_commerce_hml" >&2
  exit 1
else
  echo "OK: acesso negado como esperado"
fi

rm -f "$CNF" "$CNF_PROD" "$CNF_HML"

echo ""
echo "=== Credenciais (guarde para cutover Fase 6 / HML Fase 7) ==="
echo "Arquivo: $CREDS_FILE"
echo "pctrim_prod / pctrim_commerce"
echo "pctrim_hml  / pctrim_commerce_hml"
echo "PCTrim_PROD_PASSWORD=${PCTrim_PROD_PASSWORD:0:4}**** (len=${#PCTrim_PROD_PASSWORD})"
echo "PCTrim_HML_PASSWORD=${PCTrim_HML_PASSWORD:0:4}**** (len=${#PCTrim_HML_PASSWORD})"
echo "Para ver senhas completas no servidor: cat $CREDS_FILE"

echo "=== FASE 4 CONCLUIDA ==="
echo "App continua em loja2001 com root (.env inalterado)"
""")
    .replace("__REMOTE_ENV__", REMOTE_ENV)
)

PHASE5_SCRIPT = (
    textwrap.dedent(r"""
set -euo pipefail
BACKUP_DIR=$(ls -dt "$HOME"/mysql_migration_* 2>/dev/null | head -1)
set -a; source __REMOTE_ENV__; set +a
CNF="/tmp/.my.cnf.migration.$$"
cat > "$CNF" <<EOF
[client]
host=${MYSQL_HOST:-127.0.0.1}
port=${MYSQL_PORT:-3306}
user=${MYSQL_USER}
password=${MYSQL_PASSWORD}
EOF
chmod 600 "$CNF"
DB_SRC="${MYSQL_DATABASE:-loja2001}"
CREDS_FILE="$BACKUP_DIR/mysql_users_credentials.env"
[ -f "$CREDS_FILE" ] && source "$CREDS_FILE"

echo "=== FASE 5: validacao completa ==="
FAIL=0
check_eq() { [ "$1" = "$2" ] || { echo "FALHA: $3 ($1 != $2)"; FAIL=1; }; }

T_ORIG=$(mysql --defaults-extra-file="$CNF" -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$DB_SRC' AND table_type='BASE TABLE';")
T_PROD=$(mysql --defaults-extra-file="$CNF" -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='pctrim_commerce' AND table_type='BASE TABLE';")
T_HML=$(mysql --defaults-extra-file="$CNF" -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='pctrim_commerce_hml' AND table_type='BASE TABLE';")
echo "Tabelas: origem=$T_ORIG prod=$T_PROD hml=$T_HML"
check_eq "$T_ORIG" "$T_PROD" "tabelas prod"
check_eq "$T_ORIG" "$T_HML" "tabelas hml"

mysql --defaults-extra-file="$CNF" -e "
SELECT table_schema, COUNT(*) AS tabelas FROM information_schema.tables
WHERE table_schema IN ('$DB_SRC','pctrim_commerce','pctrim_commerce_hml') AND table_type='BASE TABLE'
GROUP BY table_schema;"

echo "=== CHECKSUM (primeiras 5 tabelas) ==="
TABLES=$(mysql --defaults-extra-file="$CNF" -N -e "SELECT table_name FROM information_schema.tables WHERE table_schema='$DB_SRC' AND table_type='BASE TABLE' ORDER BY table_name LIMIT 5;")
for T in $TABLES; do
  CS=$(mysql --defaults-extra-file="$CNF" -N -e "CHECKSUM TABLE \`$DB_SRC\`.\`$T\`, \`pctrim_commerce\`.\`$T\`, \`pctrim_commerce_hml\`.\`$T\`;")
  echo "$T: $CS"
  C1=$(echo "$CS" | sed -n '1p' | awk '{print $2}')
  C2=$(echo "$CS" | sed -n '2p' | awk '{print $2}')
  C3=$(echo "$CS" | sed -n '3p' | awk '{print $2}')
  [ "$C1" = "$C2" ] && [ "$C2" = "$C3" ] || { echo "FALHA checksum $T"; FAIL=1; }
done

mysql --defaults-extra-file="$CNF" -e "
SELECT trigger_schema, COUNT(*) c FROM information_schema.triggers WHERE trigger_schema IN ('$DB_SRC','pctrim_commerce','pctrim_commerce_hml') GROUP BY trigger_schema;
SELECT table_schema, COUNT(*) c FROM information_schema.views WHERE table_schema IN ('$DB_SRC','pctrim_commerce','pctrim_commerce_hml') GROUP BY table_schema;
SELECT routine_schema, COUNT(*) c FROM information_schema.routines WHERE routine_schema IN ('$DB_SRC','pctrim_commerce','pctrim_commerce_hml') GROUP BY routine_schema;" 2>/dev/null || true

if [ -n "${PCTrim_PROD_PASSWORD:-}" ]; then
  CNF_P="/tmp/.my.cnf.p.$$"; cat > "$CNF_P" <<EOF
[client]
host=${MYSQL_HOST}
port=${MYSQL_PORT}
user=pctrim_prod
password=$PCTrim_PROD_PASSWORD
EOF
  chmod 600 "$CNF_P"
  mysql --defaults-extra-file="$CNF_P" -D pctrim_commerce -e "SELECT COUNT(*) AS ok FROM usuarios;" >/dev/null && echo "OK pctrim_prod" || { echo "FALHA pctrim_prod"; FAIL=1; }
  mysql --defaults-extra-file="$CNF_P" -D pctrim_commerce_hml -e "SELECT 1;" 2>/dev/null && { echo "FALHA prod acessa hml"; FAIL=1; } || echo "OK prod isolado"
  rm -f "$CNF_P"
  CNF_H="/tmp/.my.cnf.h.$$"; cat > "$CNF_H" <<EOF
[client]
host=${MYSQL_HOST}
port=${MYSQL_PORT}
user=pctrim_hml
password=$PCTrim_HML_PASSWORD
EOF
  chmod 600 "$CNF_H"
  mysql --defaults-extra-file="$CNF_H" -D pctrim_commerce_hml -e "SELECT COUNT(*) AS ok FROM usuarios;" >/dev/null && echo "OK pctrim_hml" || { echo "FALHA pctrim_hml"; FAIL=1; }
  mysql --defaults-extra-file="$CNF_H" -D pctrim_commerce -e "SELECT 1;" 2>/dev/null && { echo "FALHA hml acessa prod"; FAIL=1; } || echo "OK hml isolado"
  rm -f "$CNF_H"
fi

rm -f "$CNF"
[ "$FAIL" -eq 0 ] && echo "=== FASE 5 CONCLUIDA OK ===" || { echo "=== FASE 5 FALHOU ==="; exit 1; }
""")
    .replace("__REMOTE_ENV__", REMOTE_ENV)
)

PHASE6_SCRIPT = (
    textwrap.dedent(r"""
set -euo pipefail
BACKUP_DIR=$(ls -dt "$HOME"/mysql_migration_* 2>/dev/null | head -1)
set -a; source __REMOTE_ENV__; set +a
CNF="/tmp/.my.cnf.migration.$$"
cat > "$CNF" <<EOF
[client]
host=${MYSQL_HOST:-127.0.0.1}
port=${MYSQL_PORT:-3306}
user=${MYSQL_USER}
password=${MYSQL_PASSWORD}
EOF
chmod 600 "$CNF"
DB_SRC="${MYSQL_DATABASE:-loja2001}"
TS=$(date +%Y%m%d_%H%M%S)
SYNC="$BACKUP_DIR/${DB_SRC}_cutover_final_${TS}.sql"

echo "=== FASE 6: sync final (SEM alterar .env) ==="
MYSQLDUMP_EXTRA=""
if mysqldump --help 2>&1 | grep -q column-statistics; then MYSQLDUMP_EXTRA="--column-statistics=0"; fi
mysqldump --defaults-extra-file="$CNF" --single-transaction --routines --triggers --events --hex-blob --add-drop-table --default-character-set=utf8mb4 --set-gtid-purged=OFF $MYSQLDUMP_EXTRA "$DB_SRC" > "$SYNC"
ls -lh "$SYNC"

for BANCO in pctrim_commerce pctrim_commerce_hml; do
  echo "Sync import -> $BANCO"
  sed '/^USE `/d; /^CREATE DATABASE `/d' "$SYNC" | mysql --defaults-extra-file="$CNF" -D "$BANCO"
done

echo "=== .env producao NAO alterado (cutover manual pendente) ==="
grep -E '^MYSQL_(DATABASE|USER)=' __REMOTE_ENV__ || true

rm -f "$CNF"
echo "SYNC_FILE=$SYNC" >> "$BACKUP_DIR/migration_vars.env"
echo "=== FASE 6 CONCLUIDA (banco sync; app ainda em loja2001) ==="
""")
    .replace("__REMOTE_ENV__", REMOTE_ENV)
)

PHASE7_SCRIPT = (
    textwrap.dedent(r"""
set -euo pipefail
BACKUP_DIR=$(ls -dt "$HOME"/mysql_migration_* 2>/dev/null | head -1)
CREDS_FILE="$BACKUP_DIR/mysql_users_credentials.env"
HML_DIR="/var/www/html/LojaOnline_hml"
PROD_DIR="/var/www/html/LojaOnline"
SERVICE="/etc/systemd/system/lojaonline-hml.service"

[ -f "$CREDS_FILE" ] || { echo "ERRO: credenciais Fase 4 ausentes"; exit 1; }
source "$CREDS_FILE"

echo "=== FASE 7: instancia homologacao ==="
if [ ! -d "$HML_DIR" ]; then
  cp -a "$PROD_DIR" "$HML_DIR"
  echo "OK: copiado $PROD_DIR -> $HML_DIR"
else
  echo "OK: $HML_DIR ja existe"
fi

if [ -f "$PROD_DIR/.env" ]; then
  cp "$PROD_DIR/.env" "$HML_DIR/.env"
  sed -i 's/^ENVIRONMENT=.*/ENVIRONMENT=homologation/' "$HML_DIR/.env"
  sed -i 's/^MYSQL_DATABASE=.*/MYSQL_DATABASE=pctrim_commerce_hml/' "$HML_DIR/.env"
  sed -i 's/^MYSQL_USER=.*/MYSQL_USER=pctrim_hml/' "$HML_DIR/.env"
  sed -i "s/^MYSQL_PASSWORD=.*/MYSQL_PASSWORD=$PCTrim_HML_PASSWORD/" "$HML_DIR/.env"
  echo "OK: .env HML configurado"
fi

cat > "$SERVICE" <<'UNIT'
[Unit]
Description=LojaOnline Flask HML (Gunicorn)
After=network.target mysql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/html/LojaOnline_hml
EnvironmentFile=/var/www/html/LojaOnline_hml/.env
ExecStart=/var/www/html/LojaOnline_hml/.venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8002 --timeout 120 wsgi:application
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

chown -R www-data:www-data "$HML_DIR" 2>/dev/null || true
systemctl daemon-reload
systemctl enable lojaonline-hml
systemctl restart lojaonline-hml
sleep 2
systemctl is-active lojaonline-hml && echo "OK: lojaonline-hml ativo porta 8002" || { systemctl status lojaonline-hml --no-pager; exit 1; }

echo "=== Producao inalterada ==="
grep -E '^MYSQL_(DATABASE|USER|HOST)=' "$PROD_DIR/.env" || true
echo "=== FASE 7 CONCLUIDA ==="
""")
    .replace("__REMOTE_ENV__", REMOTE_ENV)
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["0", "1", "2", "3", "4", "5", "6", "7", "rest"], help="Fase a executar")
    args = parser.parse_args()

    host, port, user, pwd = filezilla_creds()
    print(f"==> SSH {user}@{host}:{port} — FASE {args.phase}")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=pwd, timeout=30)
    phases = {
        "0": PHASE0_SCRIPT,
        "1": PHASE1_SCRIPT,
        "2": PHASE2_SCRIPT,
        "3": PHASE3_SCRIPT,
        "4": PHASE4_SCRIPT,
        "5": PHASE5_SCRIPT,
        "6": PHASE6_SCRIPT,
        "7": PHASE7_SCRIPT,
    }
    run_list = ["5", "6", "7"] if args.phase == "rest" else [args.phase]
    try:
        for ph in run_list:
            print(f"\n{'='*50}\n>>> EXECUTANDO FASE {ph}\n{'='*50}")
            code, out, err = ssh_exec(client, phases[ph], timeout=1800)
            print(out)
            if err.strip():
                print("STDERR:", err, file=sys.stderr)
            if code != 0:
                print(f"FASE {ph} FALHOU (exit {code})", file=sys.stderr)
                return code
            print(f"FASE {ph} OK")
        return 0
    finally:
        client.close()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

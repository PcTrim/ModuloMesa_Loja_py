#!/usr/bin/env python3
"""Dump dual (prod + hml) compatível com MySQL 8 — execução 100% remota via SSH.

Arquitetura (NÃO existe MySQL local no PC):
  1. Este script roda no Windows e conecta via SSH no VPS Hostinger.
  2. No VPS, mysqldump fala com MySQL em 127.0.0.1:3308 (loopback do servidor).
  3. Credenciais vêm de /var/www/html/LojaOnline/.env (remoto).
  4. O .sql final é baixado via SFTP (paramiko) para deploy/dist/.

Bases: pctrim_commerce + pctrim_commerce_hml

EVENTs: qualquer CREATE EVENT (incluindo /*!50106 ... EVENT) e removido/
comentado no dump final — nenhum EVENT permanece ativo.
"""
from __future__ import annotations

import base64
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import paramiko

DEPLOY_DIR = Path(__file__).resolve().parent
DIST_DIR = DEPLOY_DIR / "dist"
REMOTE_ENV = "/var/www/html/LojaOnline/.env"
DATABASES = ("pctrim_commerce", "pctrim_commerce_hml")
# Porta MySQL no VPS (confirmada). Spec genérica cita 3306; neste ambiente é 3308.
DEFAULT_MYSQL_PORT = "3308"

REMOTE_BASH = r"""
set -euo pipefail

REMOTE_ENV="__REMOTE_ENV__"
OUT_FILE="__OUT_FILE__"
STAGING_DIR="$(dirname "$OUT_FILE")"
mkdir -p "$STAGING_DIR"

if [ ! -f "$REMOTE_ENV" ]; then
  echo "ERRO: .env remoto nao encontrado: $REMOTE_ENV" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$REMOTE_ENV"
set +a

MYSQL_USER="${MYSQL_USER:?MYSQL_USER ausente no .env}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:?MYSQL_PASSWORD ausente no .env}"
# Dump no VPS: sempre 127.0.0.1 (loopback do servidor). Ignora MYSQL_HOST externo.
MYSQL_PORT="${MYSQL_PORT:-__DEFAULT_MYSQL_PORT__}"
MYSQL_USER_HML="${MYSQL_USER_HML:-$MYSQL_USER}"
MYSQL_PASSWORD_HML="${MYSQL_PASSWORD_HML:-$MYSQL_PASSWORD}"

# ~/.my.cnf temporario para a sessao (format especificado); restaura/remove ao sair.
CNF_HOME="${HOME:-/root}/.my.cnf"
CNF_BACKUP=""
cleanup() {
  if [ -n "$CNF_BACKUP" ] && [ -f "$CNF_BACKUP" ]; then
    mv -f "$CNF_BACKUP" "$CNF_HOME"
  else
    rm -f "$CNF_HOME"
  fi
  rm -f "$STAGING_DIR"/_dump_*.raw.sql "$STAGING_DIR"/_dump_*.clean.sql
}
trap cleanup EXIT

if [ -f "$CNF_HOME" ]; then
  CNF_BACKUP="$(mktemp "${HOME:-/root}/.my.cnf.pre_dump.XXXXXX")"
  cp -a "$CNF_HOME" "$CNF_BACKUP"
fi

write_cnf() {
  local u="$1"
  local p="$2"
  cat > "$CNF_HOME" <<EOF
[client]
host=127.0.0.1
port=$MYSQL_PORT
user=$u
password=$p
EOF
  chmod 600 "$CNF_HOME"
}

postprocess() {
  local src="$1"
  local dst="$2"
  python3 - "$src" "$dst" <<'PY'
import re, sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src, "r", encoding="utf-8", errors="replace").read()

# Remover CREATE DATABASE / USE emitidos por --databases (wrapper externo ja fornece).
text = re.sub(
    r"(?im)^CREATE\s+DATABASE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?[^`;\n]+`?\s*;?\s*\n?",
    "",
    text,
)
text = re.sub(r"(?im)^USE\s+`?[^`;\n]+`?\s*;\s*\n?", "", text)

# 1) Remover DEFINER
text = re.sub(r"DEFINER\s*=\s*`[^`]*`\s*@\s*`[^`]*`", "", text, flags=re.I)
text = re.sub(r"DEFINER\s*=\s*'[^']*'\s*@\s*'[^']*'", "", text, flags=re.I)

# 2) Remover NO_AUTO_CREATE_USER
text = re.sub(r",?\s*NO_AUTO_CREATE_USER", "", text, flags=re.I)

# 3) MyISAM -> InnoDB
text = re.sub(r"\bTYPE\s*=\s*MyISAM\b", "ENGINE=InnoDB", text, flags=re.I)
text = re.sub(r"\bENGINE\s*=\s*MyISAM\b", "ENGINE=InnoDB", text, flags=re.I)

# 4) Remover display width (exceto tinyint(1))
def strip_width(m):
    typ = m.group(1)
    width = m.group(2)
    if typ.lower() == "tinyint" and width == "1":
        return m.group(0)
    return typ
text = re.sub(
    r"\b(tinyint|smallint|mediumint|int|integer|bigint)\((\d+)\)",
    strip_width,
    text,
    flags=re.I,
)

# 5) Charset -> utf8mb4 em DDL
text = re.sub(
    r"\bCHARACTER\s+SET\s+(utf8(?!mb4)|latin1|utf8mb3)\b",
    "CHARACTER SET utf8mb4",
    text,
    flags=re.I,
)
text = re.sub(
    r"\bDEFAULT\s+CHARSET\s*=\s*(utf8(?!mb4)|latin1|utf8mb3)\b",
    "DEFAULT CHARSET=utf8mb4",
    text,
    flags=re.I,
)
text = re.sub(
    r"\bCHARSET\s*=\s*(utf8(?!mb4)|latin1|utf8mb3)\b",
    "CHARSET=utf8mb4",
    text,
    flags=re.I,
)

# 6) Remover/comentar TODOS os EVENTs (CREATE EVENT e formas /*!50106 ... EVENT)
EVENT_MARKER = "-- EVENT REMOVIDO PARA COMPATIBILIDADE MYSQL 8\n"
EVENT_START = re.compile(
    r"(?is)"
    r"(?:"
    r"/\*!\d+\s+CREATE\s*\*/(?:\s*/\*!\d+\s+[^*]*\*/)*\s*/\*!\d+\s+EVENT\b"
    r"|"
    r"/\*!\d+\s+CREATE\s+EVENT\b"
    r"|"
    r"/\*!\d+\s+DROP\s+EVENT\b"
    r"|"
    r"(?:^|\n)\s*(?:CREATE|DROP)\s+EVENT\b"
    r")"
)

def find_stmt_end(sql: str, start: int) -> int:
    # Fim do statement (apos ponto-e-virgula), respeitando aspas e comentarios
    n = len(sql)
    i = start
    in_str = False
    while i < n:
        ch = sql[i]
        if not in_str and ch == "/" and i + 1 < n and sql[i + 1] == "*":
            end = sql.find("*/", i + 2)
            if end < 0:
                return n
            i = end + 2
            continue
        if ch == "'" and not in_str:
            in_str = True
            i += 1
            continue
        if ch == "'" and in_str:
            if i + 1 < n and sql[i + 1] == "'":
                i += 2
                continue
            in_str = False
            i += 1
            continue
        if ch == ";" and not in_str:
            return i + 1
        i += 1
    return n


def strip_events(sql: str) -> str:
    out = []
    pos = 0
    while True:
        m = EVENT_START.search(sql, pos)
        if not m:
            out.append(sql[pos:])
            break
        out.append(sql[pos:m.start()])
        end = find_stmt_end(sql, m.end())
        # Inclui newlines finais do bloco removido
        while end < len(sql) and sql[end] in "\r\n":
            end += 1
        out.append(EVENT_MARKER)
        pos = end
    return "".join(out)

text = strip_events(text)

# Garantia: nenhum EVENT ativo (linha nao-comentada)
if re.search(r"(?im)^(?!\s*--).*CREATE\s+EVENT\b", text) or re.search(
    r"(?i)/\*!\d+[^*]*EVENT\b", text
):
    # Ultima passagem: comentar qualquer residual suspeito
    text = re.sub(
        r"(?im)^(.*\bEVENT\b.*)$",
        lambda m: m.group(0) if m.group(0).lstrip().startswith("--") else "-- " + m.group(0),
        text,
    )

open(dst, "w", encoding="utf-8", newline="\n").write(text)
PY
}

: > "$OUT_FILE"
echo "-- Dump dual MySQL 8 gerado em $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$OUT_FILE"
echo "-- Origem: VPS Hostinger (SSH) | mysqldump em 127.0.0.1:$MYSQL_PORT" >> "$OUT_FILE"
echo "-- Bases: pctrim_commerce + pctrim_commerce_hml" >> "$OUT_FILE"
echo "-- Pos-processamento: DEFINER, InnoDB, utf8mb4, EVENTs removidos" >> "$OUT_FILE"
echo "-- AVISO: nao ha MySQL local no PC; arquivo gerado no servidor remoto." >> "$OUT_FILE"
echo "" >> "$OUT_FILE"

dump_one() {
  local DB="$1"
  local U="$2"
  local P="$3"
  echo "==> Dump de $DB (user=$U host=127.0.0.1 port=$MYSQL_PORT) ..."
  RAW="$STAGING_DIR/_dump_${DB}.raw.sql"
  CLEAN="$STAGING_DIR/_dump_${DB}.clean.sql"
  write_cnf "$U" "$P"

  mysqldump \
    --single-transaction \
    --routines \
    --triggers \
    --events \
    --hex-blob \
    --add-drop-table \
    --default-character-set=utf8mb4 \
    --set-gtid-purged=OFF \
    --column-statistics=0 \
    --skip-comments \
    --databases "$DB" > "$RAW"

  postprocess "$RAW" "$CLEAN"

  {
    echo "-- ========== DATABASE: ${DB} =========="
    echo "CREATE DATABASE IF NOT EXISTS \`${DB}\`"
    echo "  DEFAULT CHARACTER SET utf8mb4"
    echo "  DEFAULT COLLATE utf8mb4_unicode_ci;"
    echo "USE \`${DB}\`;"
    echo "SET NAMES utf8mb4;"
    echo "SET FOREIGN_KEY_CHECKS=0;"
    echo ""
    cat "$CLEAN"
    echo ""
    echo "SET FOREIGN_KEY_CHECKS=1;"
    echo ""
  } >> "$OUT_FILE"

  rm -f "$RAW" "$CLEAN"
  echo "OK: $DB"
}

dump_one "pctrim_commerce" "$MYSQL_USER" "$MYSQL_PASSWORD"
dump_one "pctrim_commerce_hml" "$MYSQL_USER_HML" "$MYSQL_PASSWORD_HML"

# Nenhum EVENT ativo no dump final
if grep -Piq '^\s*(?!--)(.*\bCREATE\s+EVENT\b|/\*!\d+.*\bEVENT\b)' "$OUT_FILE" 2>/dev/null; then
  echo "AVISO: residual de EVENT detectado — forcando limpeza..." >&2
  python3 - "$OUT_FILE" <<'PY'
import re, sys
path = sys.argv[1]
text = open(path, encoding="utf-8", errors="replace").read()
text = re.sub(r"(?is)/\*!\d+[^*]*EVENT\b.*?;", "-- EVENT REMOVIDO PARA COMPATIBILIDADE MYSQL 8\n", text)
text = re.sub(r"(?im)^\s*CREATE\s+EVENT\b.*?;", "-- EVENT REMOVIDO PARA COMPATIBILIDADE MYSQL 8\n", text)
open(path, "w", encoding="utf-8", newline="\n").write(text)
PY
fi

need_ok=1
for needle in "CREATE TABLE" "INSERT INTO" "USE \`pctrim_commerce\`" "USE \`pctrim_commerce_hml\`"; do
  if ! grep -Fq "$needle" "$OUT_FILE"; then
    echo "ERRO validacao: faltou '$needle'" >&2
    need_ok=0
  fi
done
if [ "$need_ok" != "1" ]; then
  exit 2
fi

TABLES=$(grep -c '^CREATE TABLE' "$OUT_FILE" || true)
INSERTS=$(grep -c '^INSERT INTO' "$OUT_FILE" || true)
SIZE=$(wc -c < "$OUT_FILE" | tr -d ' ')
echo "DUMP_OK"
echo "OUT_FILE=$OUT_FILE"
echo "SIZE_BYTES=$SIZE"
echo "CREATE_TABLE_COUNT=$TABLES"
echo "INSERT_INTO_COUNT=$INSERTS"
"""


def load_env_file() -> dict[str, str]:
    cfg: dict[str, str] = {}
    env_path = DEPLOY_DIR / "deploy.local.env"
    if not env_path.is_file():
        return cfg
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip()
    return cfg


def _server_tuple(srv) -> tuple[str, int, str, str]:
    enc = srv.find("Pass")
    if enc is None or not enc.text:
        raise RuntimeError("Senha SSH nao salva no FileZilla")
    pwd = base64.b64decode(enc.text).decode("utf-8", errors="replace")
    return (
        srv.findtext("Host") or "",
        int(srv.findtext("Port") or "22"),
        srv.findtext("User") or "",
        pwd,
    )


def filezilla_hostinger_creds() -> tuple[str, int, str, str]:
    """Prefere o site 'hostinguer' (VPS LojaOnline); evita Hostinger_8 e similares."""
    fz = Path(os.environ.get("APPDATA", "")) / "FileZilla" / "sitemanager.xml"
    if not fz.is_file():
        raise RuntimeError("FileZilla sitemanager.xml nao encontrado")
    root = ET.parse(fz).getroot()
    preferred = None
    fallback = None
    for srv in root.findall(".//Server"):
        name = (srv.findtext("Name") or "").strip().lower()
        host = (srv.findtext("Host") or "").strip()
        if name == "hostinguer" or host == "92.113.33.100":
            preferred = _server_tuple(srv)
            break
        if fallback is None and ("hostinguer" in name or "hostinger" in name):
            if host == "92.113.33.100":
                fallback = _server_tuple(srv)
    if preferred:
        return preferred
    if fallback:
        return fallback
    raise RuntimeError("Site hostinguer (92.113.33.100) nao encontrado no FileZilla")


def resolve_ssh() -> tuple[str, int, str, str]:
    cfg = load_env_file()
    host = cfg.get("DEPLOY_SSH_HOST", "")
    port = int(cfg.get("DEPLOY_SSH_PORT", "22"))
    user = cfg.get("DEPLOY_SSH_USER", "")
    password = os.environ.get("DEPLOY_SSH_PASSWORD", "")
    if not host or not user:
        return filezilla_hostinger_creds()
    if not password:
        password = os.environ.get("DEPLOY_SSH_PASSWORD", "")
        if not password:
            _, _, _, password = filezilla_hostinger_creds()
    return host, port, user, password


def ssh_exec(client: paramiko.SSHClient, cmd: str, check: bool = True, timeout: int = 3600) -> tuple[int, str, str]:
    print(f"\n$ {cmd[:200]}{'...' if len(cmd) > 200 else ''}")
    _, stdout, stderr = client.exec_command(cmd, get_pty=False, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")
    if err.strip():
        sys.stderr.buffer.write(err.encode("utf-8", errors="replace"))
        sys.stderr.buffer.write(b"\n")
    if check and code != 0:
        raise RuntimeError(f"Comando falhou (exit {code})")
    return code, out, err


def sftp_put(client: paramiko.SSHClient, local: Path, remote: str) -> None:
    sftp = client.open_sftp()
    try:
        sftp.put(str(local), remote)
    finally:
        sftp.close()


def sftp_get(client: paramiko.SSHClient, remote: str, local: Path) -> None:
    sftp = client.open_sftp()
    try:
        sftp.get(remote, str(local))
    finally:
        sftp.close()


def local_validate(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    checks = {
        "CREATE TABLE": "CREATE TABLE" in text,
        "INSERT INTO": "INSERT INTO" in text,
        "USE `pctrim_commerce`": "USE `pctrim_commerce`" in text,
        "USE `pctrim_commerce_hml`": "USE `pctrim_commerce_hml`" in text,
    }
    missing = [k for k, ok in checks.items() if not ok]
    if missing:
        raise RuntimeError(f"Validacao local falhou; faltou: {', '.join(missing)}")

    # Nenhum EVENT ativo (ignora linhas ja comentadas com --)
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("--"):
            continue
        if re.search(r"(?i)\bCREATE\s+EVENT\b", line):
            raise RuntimeError("Validacao falhou: CREATE EVENT ativo ainda presente no dump")
        if re.search(r"(?i)/\*!\d+[^*]*\bEVENT\b", line):
            raise RuntimeError("Validacao falhou: EVENT em comentario condicional ainda ativo")
        if re.search(r"(?i)^\s*DROP\s+EVENT\b", line):
            raise RuntimeError("Validacao falhou: DROP EVENT ativo ainda presente no dump")

    tables = len(re.findall(r"(?m)^CREATE TABLE", text))
    inserts = len(re.findall(r"(?m)^INSERT INTO", text))
    return {"create_table": tables, "insert_into": inserts, "size": path.stat().st_size}


def main() -> int:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    local_name = f"pctrim_commerce_dual_mysql8_{ts}.sql"
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    local_path = DIST_DIR / local_name
    remote_path = f"/tmp/{local_name}"

    host, port, user, password = resolve_ssh()
    print(f"==> SSH {user}@{host}:{port}")
    print("==> Dump REMOTO (sem MySQL local no PC)")
    print(f"==> MySQL no VPS: 127.0.0.1:{DEFAULT_MYSQL_PORT}")
    print(f"==> Bases: {', '.join(DATABASES)}")
    print(f"==> Saida local: {local_path}")

    script = (
        REMOTE_BASH.replace("__REMOTE_ENV__", REMOTE_ENV)
        .replace("__OUT_FILE__", remote_path)
        .replace("__DEFAULT_MYSQL_PORT__", DEFAULT_MYSQL_PORT)
    )

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=password, timeout=30)

    remote_script = f"/tmp/dump_dual_mysql8_{ts}.sh"
    try:
        print("\n==> Enviando script remoto...")
        local_sh = DIST_DIR / f"_remote_dump_{ts}.sh"
        local_sh.write_text(script, encoding="utf-8", newline="\n")
        try:
            sftp_put(client, local_sh, remote_script)
        finally:
            local_sh.unlink(missing_ok=True)

        print("==> Gerando dump no servidor (pode demorar)...")
        code, out, _err = ssh_exec(
            client,
            f"sed -i 's/\\r$//' '{remote_script}' && chmod +x '{remote_script}' && bash '{remote_script}'",
            check=False,
            timeout=3600,
        )
        ssh_exec(client, f"rm -f '{remote_script}'", check=False)
        if code != 0:
            raise RuntimeError(f"Dump remoto falhou (exit {code})")
        if "DUMP_OK" not in out:
            raise RuntimeError("Dump remoto nao retornou DUMP_OK")

        print(f"\n==> Download SFTP: {remote_path} -> {local_path}")
        sftp_get(client, remote_path, local_path)
        ssh_exec(client, f"rm -f '{remote_path}'", check=False)

        stats = local_validate(local_path)
        size_mb = stats["size"] / (1024 * 1024)
        print("\n==> Dump concluido")
        print(f"    Arquivo: {local_path}")
        print(f"    Tamanho: {size_mb:.2f} MB ({stats['size']} bytes)")
        print(f"    CREATE TABLE (aprox.): {stats['create_table']}")
        print(f"    INSERT INTO (aprox.): {stats['insert_into']}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1)

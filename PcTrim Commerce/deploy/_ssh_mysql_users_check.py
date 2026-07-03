#!/usr/bin/env python3
"""Consulta usuários MySQL com acesso a loja2001 (somente leitura)."""
from __future__ import annotations

import base64
import os
import sys
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import paramiko

REMOTE_ENV = "/var/www/html/LojaOnline/.env"


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


CHECK_SCRIPT = (
    textwrap.dedent(r"""
set -a
source __REMOTE_ENV__
set +a

CNF="/tmp/.my.cnf.check.$$"
cat > "$CNF" <<EOF
[client]
host=${MYSQL_HOST:-127.0.0.1}
port=${MYSQL_PORT:-3306}
user=${MYSQL_USER}
password=${MYSQL_PASSWORD}
EOF
chmod 600 "$CNF"

echo "=== Credencial usada pela app (.env) ==="
echo "MYSQL_HOST=${MYSQL_HOST}"
echo "MYSQL_PORT=${MYSQL_PORT}"
echo "MYSQL_USER=${MYSQL_USER}"
echo "MYSQL_DATABASE=${MYSQL_DATABASE}"
echo ""

echo "=== GRANTS do usuario da app (CURRENT_USER) ==="
mysql --defaults-extra-file="$CNF" -e "SHOW GRANTS FOR CURRENT_USER();" 2>&1 || true
echo ""

echo "=== Contas com privilegio explicito em loja2001 (mysql.db) ==="
mysql --defaults-extra-file="$CNF" -N -e "
SELECT CONCAT('\`', user, '\`@\`', host, '\`') AS account,
       Select_priv, Insert_priv, Update_priv, Delete_priv
FROM mysql.db
WHERE db = 'loja2001'
ORDER BY user, host;" 2>&1 || true
echo ""

echo "=== Usuarios locais com ALL PRIVILEGES (*.*) ==="
mysql --defaults-extra-file="$CNF" -N -e "
SELECT CONCAT('\`', user, '\`@\`', host, '\`')
FROM mysql.user
WHERE Super_priv = 'Y' OR Grant_priv = 'Y'
ORDER BY user, host;" 2>&1 || true
echo ""

echo "=== Lista resumida de contas MySQL ==="
mysql --defaults-extra-file="$CNF" -N -e "
SELECT CONCAT(user, '@', host) FROM mysql.user ORDER BY user, host;" 2>&1 | head -40

rm -f "$CNF"
""")
    .replace("__REMOTE_ENV__", REMOTE_ENV)
)


def main() -> int:
    host, port, user, pwd = filezilla_creds()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=pwd, timeout=30)
    try:
        _, stdout, stderr = client.exec_command(CHECK_SCRIPT, timeout=60)
        print(stdout.read().decode("utf-8", errors="replace"))
        err = stderr.read().decode("utf-8", errors="replace")
        if err.strip():
            print("STDERR:", err, file=sys.stderr)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

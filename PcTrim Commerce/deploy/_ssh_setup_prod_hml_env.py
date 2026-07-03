#!/usr/bin/env python3
"""Adiciona MYSQL_*_HML no .env de producao se ausente e reinicia lojaonline."""
import base64
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import paramiko

REMOTE_CMD = r"""
set -e
ENV="/var/www/html/LojaOnline/.env"
CREDS=$(ls -dt /root/mysql_migration_*/mysql_users_credentials.env 2>/dev/null | head -1 || true)
if [ -z "$CREDS" ]; then
  CREDS=$(ls -dt "$HOME"/mysql_migration_*/mysql_users_credentials.env 2>/dev/null | head -1 || true)
fi
HML_PASS=""
if [ -n "$CREDS" ] && [ -f "$CREDS" ]; then
  HML_PASS=$(grep -E '^PCTrim_HML_PASSWORD=' "$CREDS" | head -1 | cut -d= -f2-)
fi
if grep -q '^MYSQL_PASSWORD_HML=' "$ENV" 2>/dev/null; then
  echo HML_ALREADY_SET
else
  if [ -n "$HML_PASS" ]; then
    printf '\n# Homologacao — lojas com ambiente=homologation\nMYSQL_DATABASE_HML=pctrim_commerce_hml\nMYSQL_USER_HML=pctrim_hml\nMYSQL_PASSWORD_HML=%s\n' "$HML_PASS" >> "$ENV"
    echo HML_ENV_ADDED
  else
    echo HML_PASS_NOT_FOUND
  fi
fi
grep -E '^MYSQL_(DATABASE_HML|USER_HML|PASSWORD_HML)=' "$ENV" | sed 's/PASSWORD_HML=.*/PASSWORD_HML=***/'
sudo systemctl restart lojaonline
sleep 2
curl -s -o /dev/null -w 'HTTP:%{http_code}\n' http://127.0.0.1:8001/login/form
grep APP_VERSION /var/www/html/LojaOnline/version.py
cd /var/www/html/LojaOnline && .venv/bin/python -c "from dotenv import load_dotenv; load_dotenv('.env'); from config import Config; print('hml configured:', Config.admin_db_configured('homologation'))"
cd /var/www/html/LojaOnline && .venv/bin/python -c "from dotenv import load_dotenv; load_dotenv('.env'); from services.login_tenant_db import locate_login_user; t,r=locate_login_user('marcio'); print('marcio target:', t, 'id:', r.get('id_cliente'))"
"""


def main() -> int:
    fz = Path(os.environ["APPDATA"]) / "FileZilla" / "sitemanager.xml"
    root = ET.parse(fz).getroot()
    for srv in root.findall(".//Server"):
        n = (srv.findtext("Name") or "").lower()
        if "hostinger" in n or "hostinguer" in n:
            host = srv.findtext("Host")
            port = int(srv.findtext("Port") or 22)
            user = srv.findtext("User")
            pwd = base64.b64decode(srv.find("Pass").text).decode("utf-8", errors="replace")
            break
    else:
        raise RuntimeError("Hostinger SSH not found in FileZilla")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=pwd, timeout=30)
    try:
        _, stdout, stderr = client.exec_command(REMOTE_CMD, timeout=120)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        print(out)
        if err.strip():
            print("STDERR:", err)
        return 0 if stdout.channel.recv_exit_status() == 0 else 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())

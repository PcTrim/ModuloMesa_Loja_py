#!/usr/bin/env python3
"""Expõe homologação em https://pedidofacil.online/LojaOnlineHml/"""
from __future__ import annotations

import base64
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import paramiko

SETUP_SCRIPT = """
set -euo pipefail
APACHE="/etc/apache2/sites-enabled/000-default-le-ssl.conf"
HML_ENV="/var/www/html/LojaOnline_hml/.env"
TS=$(date +%Y%m%d_%H%M%S)
cp "$APACHE" "${APACHE}.bak.hml.${TS}"

python3 << 'PYEOF'
from pathlib import Path
p = Path("/etc/apache2/sites-enabled/000-default-le-ssl.conf")
text = p.read_text()
block = '''
    # --- LojaOnline HML ---
    Alias /LojaOnlineHml/static /var/www/html/LojaOnline_hml/static
    <Directory /var/www/html/LojaOnline_hml/static>
        Require all granted
    </Directory>
    ProxyPass /LojaOnlineHml/static !
    ProxyPass /LojaOnlineHml/ http://127.0.0.1:8002/
    ProxyPassReverse /LojaOnlineHml/ http://127.0.0.1:8002/
'''
needle = "    ProxyPassReverse /LojaOnline/ http://127.0.0.1:8001/"
if "LojaOnlineHml" not in text:
    if needle not in text:
        raise SystemExit("ERRO: bloco LojaOnline nao encontrado")
    p.write_text(text.replace(needle, needle + block, 1))
    print("OK: Apache atualizado")
else:
    print("OK: LojaOnlineHml ja configurado")
PYEOF

if grep -q '^LOJA_URL_PREFIX=' "$HML_ENV"; then
  sed -i 's|^LOJA_URL_PREFIX=.*|LOJA_URL_PREFIX=/LojaOnlineHml|' "$HML_ENV"
else
  echo 'LOJA_URL_PREFIX=/LojaOnlineHml' >> "$HML_ENV"
fi
grep -E '^ENVIRONMENT=|^LOJA_URL_PREFIX=|^MYSQL_DATABASE=' "$HML_ENV"

apache2ctl configtest
systemctl reload apache2
systemctl restart lojaonline-hml
sleep 2
systemctl is-active lojaonline-hml

curl -sI https://pedidofacil.online/LojaOnlineHml/login | head -10
echo ""
echo ">>> HOMOLOGACAO: https://pedidofacil.online/LojaOnlineHml/login"
echo ">>> PRODUCAO:    https://pedidofacil.online/LojaOnline/login"
"""


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
    print(f"==> URL homologacao ({user}@{host})")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=pwd, timeout=30)
    try:
        _, stdout, stderr = client.exec_command(SETUP_SCRIPT, timeout=120)
        print(stdout.read().decode("utf-8", errors="replace"))
        err = stderr.read().decode("utf-8", errors="replace")
        if err.strip():
            print("STDERR:", err, file=sys.stderr)
        return stdout.channel.recv_exit_status()
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())

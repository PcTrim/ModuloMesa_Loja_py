"""Testa criar_instancia uazapi no servidor (loja 2003)."""
from __future__ import annotations

import base64
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import paramiko

REMOTE = "/var/www/html/LojaOnline"


def _creds():
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
    raise RuntimeError("Hostinger nao encontrado")


def main() -> int:
    host, port, user, pwd = _creds()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=pwd, timeout=30)
    py = f"""
cd '{REMOTE}' && .venv/bin/python - <<'PY'
from config import Config
from services import uazapi
print('URL', Config.UZAPI_URL)
print('ADMIN', bool(Config.UZAPI_ADMIN_TOKEN))
print('ENV', uazapi.servidor_env_status())
cfg = uazapi.obter_config(2003)
print('CFG_2003', bool(cfg), (cfg or {{}}).get('instancia_nome'))
if not cfg or not cfg.get('instancia_token'):
    res = uazapi.criar_instancia(2003, 'loja_2003')
    print('CRIAR', res)
else:
    st = uazapi.status_instancia(2003)
    print('STATUS', st)
    res = uazapi.criar_instancia(2003, 'loja_2003_v2')
    print('CRIAR_NOVO', res)
PY
"""
    try:
        _, stdout, stderr = client.exec_command(py, get_pty=True)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        print(out)
        if err.strip():
            print(err, file=sys.stderr)
        return 0 if "CRIAR {'ok': True" in out or "STATUS {'ok': True" in out else 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())

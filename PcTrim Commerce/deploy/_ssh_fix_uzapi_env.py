"""Garante UZAPI_URL no .env de producao e reinicia lojaonline."""
from __future__ import annotations

import base64
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import paramiko

REMOTE = "/var/www/html/LojaOnline"
ENV_FILE = f"{REMOTE}/.env"
UZAPI_URL = "https://pctrim.uazapi.com"


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


def _run(client, cmd, check=True):
    print(f"$ {cmd}")
    _, stdout, stderr = client.exec_command(cmd, get_pty=True)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.strip())
    if err.strip():
        print(err.strip())
    if check and code != 0:
        raise RuntimeError(f"Comando falhou ({code})")
    return code, out, err


def main() -> int:
    host, port, user, pwd = _creds()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=pwd, timeout=30)
    try:
        _run(
            client,
            f"grep -q '^UZAPI_URL=' {ENV_FILE} || echo 'UZAPI_URL={UZAPI_URL}' >> {ENV_FILE}",
            check=False,
        )
        _run(client, f"grep '^UZAPI_' {ENV_FILE} | sed 's/=.*/=***/'", check=False)
        _run(client, "sudo systemctl restart lojaonline")
        _run(client, "sleep 2 && sudo systemctl is-active lojaonline", check=False)
        _run(
            client,
            "curl -s http://127.0.0.1:8001/loja-build | head -n 1",
            check=False,
        )
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())

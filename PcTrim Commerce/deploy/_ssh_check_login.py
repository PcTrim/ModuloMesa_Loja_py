#!/usr/bin/env python3
"""Diagnóstico rápido de login em produção."""
from __future__ import annotations

import base64
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import paramiko

REMOTE = "/var/www/html/LojaOnline"


def creds():
    fz = Path(os.environ.get("APPDATA", "")) / "FileZilla" / "sitemanager.xml"
    root = ET.parse(fz).getroot()
    for srv in root.findall(".//Server"):
        name = (srv.findtext("Name") or "").lower()
        if "hostinger" in name or "hostinguer" in name:
            host = srv.findtext("Host") or ""
            port = int(srv.findtext("Port") or "22")
            user = srv.findtext("User") or ""
            enc = srv.find("Pass")
            pwd = base64.b64decode(enc.text).decode("utf-8", errors="replace")
            return host, port, user, pwd
    raise RuntimeError("Hostinger não encontrado no FileZilla")


def run(client, cmd):
    print(f"\n$ {cmd}")
    _, stdout, stderr = client.exec_command(cmd, get_pty=True)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print("STDERR:", err.rstrip())
    return stdout.channel.recv_exit_status()


def main():
    host, port, user, pwd = creds()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=pwd, timeout=30)
    try:
        run(client, "systemctl is-active lojaonline")
        run(client, "journalctl -u lojaonline -n 50 --no-pager | tail -n 50")
        payload = (
            '{"usuario":"marcio","senha":"test","csrf_token":"x","metodo":"senha"}'
        )
        run(
            client,
            "curl -s -w '\\nHTTP:%{http_code}\\n' -X POST "
            "http://127.0.0.1:8001/login "
            "-H 'Content-Type: application/json' "
            f"-d '{payload}'",
        )
        run(
            client,
            "grep -E 'MYSQL_.*_(PROD|HML)|APP_VERSION' "
            f"{REMOTE}/.env {REMOTE}/version.py 2>/dev/null | head -20",
        )
        run(
            client,
            f"cd {REMOTE} && source .venv/bin/activate && python -c \""
            "from services.login_tenant_db import locate_login_user; "
            "print(locate_login_user('marcio'))\"",
        )
    finally:
        client.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1)

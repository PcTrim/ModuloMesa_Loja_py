"""Verifica UZAPI_* no .env de produção (valores mascarados)."""
from __future__ import annotations

import base64
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import paramiko

REMOTE = "/var/www/html/LojaOnline/.env"


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
    raise RuntimeError("Hostinger não encontrado no FileZilla")


def _mask_line(line: str) -> str:
    if "=" not in line:
        return line
    k, v = line.split("=", 1)
    v = v.strip().strip('"').strip("'")
    if not v:
        return f"{k}=(vazio)"
    return f"{k}=({'*' * min(8, len(v))} len={len(v)})"


def main() -> int:
    host, port, user, pwd = _creds()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=pwd, timeout=30)
    try:
        _, stdout, _ = client.exec_command(f"grep -E '^(UZAPI_|admintoken=)' {REMOTE} || true")
        text = stdout.read().decode("utf-8", errors="replace")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            print("NENHUMA variavel UZAPI/admintoken encontrada no .env de producao")
            return 1
        for ln in lines:
            print(_mask_line(ln))
        has_url = any(re.match(r"^UZAPI_URL=", ln) and ln.split("=", 1)[1].strip() for ln in lines)
        has_admin = any(
            re.match(r"^(UZAPI_ADMIN_TOKEN|UZAPI_ADMTOKEN|admintoken)=", ln)
            and ln.split("=", 1)[1].strip()
            for ln in lines
        )
        print(f"UZAPI_URL ok: {has_url}")
        print(f"UZAPI_ADMIN ok: {has_admin}")
        return 0 if has_url and has_admin else 2
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())

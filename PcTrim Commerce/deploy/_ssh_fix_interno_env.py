#!/usr/bin/env python3
"""Ajusta .env de produção para base Interno (porta 3308) e valida conexão."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

DEPLOY_DIR = Path(__file__).resolve().parent
REMOTE_PATH = "/var/www/html/LojaOnline"

INTERNO_BLOCK = """
# Base interna — clientes para Admin > Lojas (leitura)
MYSQL_DATABASE_INTERNO=interno
MYSQL_HOST_INTERNO=127.0.0.1
MYSQL_PORT_INTERNO=3308
MYSQL_USER_INTERNO=root
MYSQL_PASSWORD_INTERNO=pctrim
""".strip()


def load_env_file() -> dict[str, str]:
    cfg: dict[str, str] = {}
    env_path = DEPLOY_DIR / "deploy.local.env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


def filezilla_creds() -> tuple[str, int, str, str]:
    import base64
    import xml.etree.ElementTree as ET

    fz = Path(os.environ.get("APPDATA", "")) / "FileZilla" / "sitemanager.xml"
    root = ET.parse(fz).getroot()
    for srv in root.findall(".//Server"):
        name = (srv.findtext("Name") or "").lower()
        if "hostinguer" in name or "hostinger" in name:
            host = srv.findtext("Host") or ""
            port = int(srv.findtext("Port") or "22")
            user = srv.findtext("User") or ""
            enc = srv.find("Pass")
            pwd = base64.b64decode(enc.text).decode("utf-8", errors="replace")
            return host, port, user, pwd
    raise RuntimeError("Hostinger nao encontrado no FileZilla")


def ssh_exec(client: paramiko.SSHClient, cmd: str) -> tuple[int, str]:
    _, stdout, stderr = client.exec_command(cmd, get_pty=True)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    text = (out + err).strip()
    print(f"\n$ {cmd}\n{text}\n")
    return code, text


def main() -> int:
    cfg = load_env_file()
    host = cfg.get("DEPLOY_SSH_HOST", "")
    port = int(cfg.get("DEPLOY_SSH_PORT", "22"))
    user = cfg.get("DEPLOY_SSH_USER", "")
    password = cfg.get("DEPLOY_SSH_PASSWORD", "")
    remote = cfg.get("DEPLOY_REMOTE_PATH", REMOTE_PATH)

    if not host or not user:
        host, port, user, password = filezilla_creds()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=password, timeout=30)

    try:
        fix_cmd = f"""
set -e
cd '{remote}'
ENV_FILE=.env
cp "$ENV_FILE" "$ENV_FILE.bak-interno-$(date +%Y%m%d_%H%M%S)"
grep -v '^MYSQL_DATABASE_INTERNO=' "$ENV_FILE" | grep -v '^MYSQL_HOST_INTERNO=' | grep -v '^MYSQL_PORT_INTERNO=' | grep -v '^MYSQL_USER_INTERNO=' | grep -v '^MYSQL_PASSWORD_INTERNO=' > "$ENV_FILE.tmp" || true
mv "$ENV_FILE.tmp" "$ENV_FILE"
cat >> "$ENV_FILE" << 'EOF'

{INTERNO_BLOCK}
EOF
grep -E '^MYSQL_(HOST|PORT|USER|PASSWORD|DATABASE)(_INTERNO)?=' "$ENV_FILE" | sed 's/PASSWORD.*/PASSWORD=***/'
"""
        code, _ = ssh_exec(client, fix_cmd)
        if code != 0:
            return 1

        ssh_exec(
            client,
            f"cd '{remote}' && .venv/bin/python scripts/check_interno_db.py",
        )
        ssh_exec(client, "sudo systemctl restart lojaonline")
        ssh_exec(
            client,
            "sleep 2 && curl -s -o /dev/null -w 'HTTP %{http_code}\\n' http://127.0.0.1:8001/login/form",
        )
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

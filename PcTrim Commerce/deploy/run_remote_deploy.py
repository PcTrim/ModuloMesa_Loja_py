#!/usr/bin/env python3
"""Deploy remoto LojaOnline via SSH (backup + upload ZIP + update)."""
from __future__ import annotations

import base64
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import paramiko
from scp import SCPClient

DEPLOY_DIR = Path(__file__).resolve().parent
APP_ROOT = DEPLOY_DIR.parent
REMOTE_PATH = "/var/www/html/LojaOnline"


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


def filezilla_hostinger_creds() -> tuple[str, int, str, str]:
    fz = Path(os.environ.get("APPDATA", "")) / "FileZilla" / "sitemanager.xml"
    if not fz.is_file():
        raise RuntimeError("FileZilla sitemanager.xml nao encontrado")
    root = ET.parse(fz).getroot()
    for srv in root.findall(".//Server"):
        name = (srv.findtext("Name") or "").lower()
        if "hostinguer" in name or "hostinger" in name:
            host = srv.findtext("Host") or ""
            port = int(srv.findtext("Port") or "22")
            user = srv.findtext("User") or ""
            enc = srv.find("Pass")
            if enc is None or not enc.text:
                raise RuntimeError("Senha SSH nao salva no FileZilla")
            pwd = base64.b64decode(enc.text).decode("utf-8", errors="replace")
            return host, port, user, pwd
    raise RuntimeError("Site hostinguer/hostinger nao encontrado no FileZilla")


def latest_zip() -> Path:
    dist = DEPLOY_DIR / "dist"
    zips = sorted(dist.glob("LojaOnline_upload_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        raise RuntimeError("Execute pack_for_upload.ps1 primeiro")
    return zips[0]


def ssh_exec(client: paramiko.SSHClient, cmd: str, check: bool = True) -> tuple[int, str, str]:
    print(f"\n$ {cmd}")
    _, stdout, stderr = client.exec_command(cmd, get_pty=True)
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


def main() -> int:
    cfg = load_env_file()
    host = cfg.get("DEPLOY_SSH_HOST", "")
    port = int(cfg.get("DEPLOY_SSH_PORT", "22"))
    user = cfg.get("DEPLOY_SSH_USER", "")
    password = os.environ.get("DEPLOY_SSH_PASSWORD", "")
    remote = cfg.get("DEPLOY_REMOTE_PATH", REMOTE_PATH)

    if not host or not user:
        host, port, user, password = filezilla_hostinger_creds()
    elif not password:
        password = os.environ.get("DEPLOY_SSH_PASSWORD", "")
        if not password:
            _, _, _, password = filezilla_hostinger_creds()

    zip_path = latest_zip()
    print(f"==> Deploy para {user}@{host}:{port}")
    print(f"==> Pacote: {zip_path.name}")
    print(f"==> Remoto: {remote}")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=password, timeout=30)

    try:
        # Fase 1 — backup (comandos inline se script ainda nao existir)
        ts_cmd = "$(date +%Y%m%d_%H%M%S)"
        backup_cmd = f"""
set -e
cd '{remote}'
TS={ts_cmd}
mkdir -p ~/lojaonline_backups
if [ -f .env ]; then cp .env ~/lojaonline_backups/.env.backup-$TS; fi
if [ -f deploy/backup_production.sh ]; then
  bash deploy/backup_production.sh || true
else
  tar czf ~/lojaonline_backups/backup_LojaOnline_$TS.tar.gz --exclude='.venv' --exclude='__pycache__' -C "$(dirname '{remote}')" "$(basename '{remote}')" || true
fi
echo BACKUP_DONE
"""
        ssh_exec(client, backup_cmd, check=False)

        # Fase 2 — upload
        remote_zip = "/tmp/LojaOnline_upload.zip"
        with SCPClient(client.get_transport()) as scp:
            scp.put(str(zip_path), remote_zip)
        print(f"==> Upload OK: {remote_zip}")

        extract_cmd = f"""
set -e
cd '{remote}'
unzip -o '{remote_zip}' -d '{remote}' || test -f app.py
rm -f '{remote_zip}'
chmod +x deploy/*.sh 2>/dev/null || true
sed -i 's/\\r$//' deploy/*.sh 2>/dev/null || true
echo EXTRACT_DONE
"""
        ssh_exec(client, extract_cmd)

        # Fase 3-4 — update + restart
        ssh_exec(client, f"cd '{remote}' && bash deploy/update_production.sh")

        code, out, _ = ssh_exec(
            client,
            "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/login/form",
            check=False,
        )
        public = cfg.get("DEPLOY_PUBLIC_URL", "https://pedidofacil.online/LojaOnline/login/form")
        print(f"\n==> Deploy concluido. HTTP local login/form: {out.strip()}")
        print(f"==> Valide no navegador: {public}")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1)

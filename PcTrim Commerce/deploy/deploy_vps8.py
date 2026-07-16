#!/usr/bin/env python3
"""Deploy da versao atual para a VPS nova (Hostinger_8 / 85.31.231.84).

Destino: /var/www/ModuloMesa_Loja_py/PcTrim Commerce
App: python3 app.py na porta 2001 com LOJA_URL_PREFIX=/LojaOnline
"""
from __future__ import annotations

import base64
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib import request

import paramiko

DEPLOY_DIR = Path(__file__).resolve().parent
DIST_DIR = DEPLOY_DIR / "dist"
REMOTE_APP = "/var/www/ModuloMesa_Loja_py/PcTrim Commerce"
PUBLIC_URL = "http://85.31.231.84:2001/LojaOnline/login/form"


def filezilla_vps8() -> tuple[str, int, str, str]:
    fz = Path(os.environ.get("APPDATA", "")) / "FileZilla" / "sitemanager.xml"
    root = ET.parse(fz).getroot()
    for srv in root.findall(".//Server"):
        if (srv.findtext("Host") or "").strip() == "85.31.231.84":
            enc = srv.find("Pass")
            if enc is None or not enc.text:
                raise RuntimeError("Senha SSH Hostinger_8 ausente")
            pwd = base64.b64decode(enc.text).decode("utf-8", errors="replace")
            return (
                srv.findtext("Host") or "",
                int(srv.findtext("Port") or "22"),
                srv.findtext("User") or "root",
                pwd,
            )
    raise RuntimeError("Hostinger_8 (85.31.231.84) nao encontrado no FileZilla")


def latest_zip() -> Path:
    zips = sorted(DIST_DIR.glob("LojaOnline_upload_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        raise RuntimeError("Nenhum ZIP em deploy/dist — rode pack_for_upload.ps1")
    return zips[0]


def read_local_version() -> str:
    text = (DEPLOY_DIR.parent / "version.py").read_text(encoding="utf-8")
    import re

    m = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', text)
    return m.group(1) if m else "?"


def ssh_exec(client: paramiko.SSHClient, cmd: str, check: bool = True, timeout: int = 600) -> tuple[int, str, str]:
    print(f"\n$ {cmd[:300]}{'...' if len(cmd) > 300 else ''}")
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


def main() -> int:
    if os.environ.get("SKIP_TEST_GATE", "").strip() not in ("1", "true", "yes"):
        print("==> Rodando test gate antes do deploy...")
        import runpy

        gate_path = DEPLOY_DIR.parent / "tests" / "run_gate.py"
        # Executa como __main__ para respeitar exit code
        ns = runpy.run_path(str(gate_path), run_name="__not_main__")
        code = int(ns["run_gate"]())
        if code != 0:
            print(f"ERRO: test gate falhou (exit {code}). Abortando deploy.")
            print("      Use SKIP_TEST_GATE=1 apenas se precisar pular conscientemente.")
            return code
    else:
        print("==> SKIP_TEST_GATE=1 — gate local ignorado")

    version = read_local_version()
    zip_path = latest_zip()
    host, port, user, password = filezilla_vps8()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    remote_zip = f"/tmp/LojaOnline_upload_{ts}.zip"

    print(f"==> Deploy VPS8 {user}@{host}:{port}")
    print(f"==> Versao: {version}")
    print(f"==> Pacote: {zip_path.name}")
    print(f"==> Destino: {REMOTE_APP}")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=password, timeout=30)

    try:
        # Backup .env + upload
        ssh_exec(
            client,
            f"""
set -e
mkdir -p '{REMOTE_APP}'
mkdir -p ~/lojaonline_vps8_backups
if [ -f '{REMOTE_APP}/.env' ]; then
  cp -a '{REMOTE_APP}/.env' ~/lojaonline_vps8_backups/.env.backup-{ts}
  echo 'ENV_BACKUP_OK'
else
  echo 'ENV_MISSING'
fi
""",
        )

        print(f"\n==> Upload SFTP {zip_path.name} -> {remote_zip}")
        sftp = client.open_sftp()
        try:
            sftp.put(str(zip_path), remote_zip)
        finally:
            sftp.close()

        # Extract over app dir, restore .env, ensure prefix
        ssh_exec(
            client,
            f"""
set -e
cd '{REMOTE_APP}'
ENV_BAK=~/lojaonline_vps8_backups/.env.backup-{ts}
# unzip pode nao existir nesta VPS — usa Python (overwrite explicito)
python3 - <<'PY'
import zipfile
from pathlib import Path

zip_path = Path('{remote_zip}')
dest = Path('{REMOTE_APP}')
written = 0
skipped = 0
with zipfile.ZipFile(zip_path, 'r') as zf:
    for info in zf.infolist():
        name = info.filename.replace('\\\\', '/')
        if not name or name.endswith('/'):
            continue
        # nunca extrair venvs empacotados por engano
        parts = name.split('/')
        if '.venv' in parts or '__pycache__' in parts:
            skipped += 1
            continue
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, 'wb') as out:
            out.write(src.read())
        written += 1
print('EXTRACTED', written, 'files skipped', skipped)
zip_path.unlink(missing_ok=True)
print('ZIP_REMOVED')

idx = dest / 'templates' / 'index.html'
text = idx.read_text(encoding='utf-8')
if 'flex-wrap:nowrap' not in text or 'max-height:54px' not in text:
    raise SystemExit('POST_EXTRACT_CSS_FAIL: templates/index.html sem class-tabs compacto')
print('POST_EXTRACT_CSS_OK')
PY
if [ -f "$ENV_BAK" ]; then
  cp -a "$ENV_BAK" '{REMOTE_APP}/.env'
fi
# Garantir LOJA_URL_PREFIX
if grep -q '^LOJA_URL_PREFIX=' '{REMOTE_APP}/.env' 2>/dev/null; then
  sed -i 's|^LOJA_URL_PREFIX=.*|LOJA_URL_PREFIX=/LojaOnline|' '{REMOTE_APP}/.env'
else
  printf '\\nLOJA_URL_PREFIX=/LojaOnline\\n' >> '{REMOTE_APP}/.env'
fi
chmod +x '{REMOTE_APP}/deploy'/*.sh 2>/dev/null || true
sed -i 's/\\r$//' '{REMOTE_APP}/deploy'/*.sh 2>/dev/null || true
grep -E '^APP_VERSION' '{REMOTE_APP}/version.py' || true
grep -E '^(LOJA_URL_PREFIX|MYSQL_HOST|MYSQL_PORT|MYSQL_DATABASE)=' '{REMOTE_APP}/.env' | sed -E 's/(PASSWORD)=.*/\\1=***/'
echo EXTRACT_OK
""",
        )

        # Garante templates PDV mesmo se extract falhar em overwrite
        print("\n==> Force put templates/index.html + mesa.html")
        sftp = client.open_sftp()
        try:
            for rel in ("templates/index.html", "templates/mesa.html"):
                local = DEPLOY_DIR.parent / rel
                remote = f"{REMOTE_APP}/{rel}"
                print(f"    {rel}")
                sftp.put(str(local), remote)
        finally:
            sftp.close()
        ssh_exec(
            client,
            f"""
python3 - <<'PY'
from pathlib import Path
t = Path('{REMOTE_APP}/templates/index.html').read_text(encoding='utf-8')
assert 'flex-wrap:nowrap' in t and 'max-height:54px' in t, 'FORCE_PUT_CSS_FAIL'
print('FORCE_PUT_CSS_OK')
PY
""",
        )

        # Restart app.py on :2001
        ssh_exec(
            client,
            f"""
set -e
PID=$(ss -lntp 2>/dev/null | awk '/:2001/ {{print}}' | sed -n 's/.*pid=\\([0-9]*\\).*/\\1/p' | head -1)
if [ -n "$PID" ]; then
  echo "Stopping pid=$PID"
  kill "$PID" || true
  sleep 2
  kill -9 "$PID" 2>/dev/null || true
fi
mkdir -p '{REMOTE_APP}/data'
cd '{REMOTE_APP}'
nohup python3 app.py > '{REMOTE_APP}/data/app_2001.log' 2>&1 &
echo "started pid=$!"
sleep 4
ss -lntp | grep 2001 || true
grep -E 'APP_VERSION|Serving Flask|Access denied|Error' '{REMOTE_APP}/data/app_2001.log' | tail -n 30 || true
# versao no processo
python3 - <<'PY'
from pathlib import Path
import re
t = Path("{REMOTE_APP}/version.py").read_text(encoding="utf-8")
m = re.search(r'APP_VERSION\\s*=\\s*[\"\\']([^\"\\']+)[\"\\']', t)
print("VERSION_FILE", m.group(1) if m else "?")
PY
curl -s -o /dev/null -w 'login_form=%{{http_code}}\\n' http://127.0.0.1:2001/LojaOnline/login/form
curl -s -D - -o /dev/null http://127.0.0.1:2001/LojaOnline/login/form | grep -iE 'HTTP/|X-App-Version|Location' || true
""",
            check=False,
        )

        time.sleep(1)
        print(f"\n==> Validando {PUBLIC_URL}")
        with request.urlopen(PUBLIC_URL, timeout=20) as resp:
            print(f"EXTERNAL HTTP {resp.status}")
            ver = resp.headers.get("X-App-Version")
            if ver:
                print(f"X-App-Version: {ver}")
        print(f"\n==> Deploy VPS8 concluido (v{version})")
        print(f"    Abra: {PUBLIC_URL}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1)

#!/usr/bin/env python3
"""Corrige LOJA_URL_PREFIX e reinicia app.py na VPS8."""
from __future__ import annotations

import base64
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import paramiko

APP = "/var/www/ModuloMesa_Loja_py/PcTrim Commerce"
TARGET = "http://127.0.0.1:2001/LojaOnline/login/form"


def creds():
    fz = Path(os.environ.get("APPDATA", "")) / "FileZilla" / "sitemanager.xml"
    root = ET.parse(fz).getroot()
    for srv in root.findall(".//Server"):
        if (srv.findtext("Host") or "") == "85.31.231.84":
            enc = srv.find("Pass")
            pwd = base64.b64decode(enc.text).decode("utf-8", errors="replace")
            return srv.findtext("Host"), int(srv.findtext("Port") or 22), srv.findtext("User"), pwd
    raise RuntimeError("VPS8 nao encontrada")


def run(client, cmd, timeout=120, check=True):
    print(f"\n$ {cmd[:500]}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip()[:8000])
    if err.strip():
        print("STDERR:", err.rstrip()[:2000])
    print(f"exit={code}")
    if check and code != 0:
        raise RuntimeError(f"cmd failed exit={code}")
    return code, out, err


def main():
    host, port, user, pwd = creds()
    print(f"==> SSH {user}@{host}:{port}")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=pwd, timeout=30)
    try:
        # 1) Ensure LOJA_URL_PREFIX in .env
        run(
            client,
            f"""
set -e
ENV='{APP}/.env'
cp -a "$ENV" "$ENV.bak.$(date +%Y%m%d_%H%M%S)"
if grep -q '^LOJA_URL_PREFIX=' "$ENV"; then
  sed -i 's|^LOJA_URL_PREFIX=.*|LOJA_URL_PREFIX=/LojaOnline|' "$ENV"
else
  printf '\\nLOJA_URL_PREFIX=/LojaOnline\\n' >> "$ENV"
fi
grep -E '^(MYSQL_HOST|MYSQL_PORT|MYSQL_DATABASE|LOJA_URL_PREFIX|ENVIRONMENT)=' "$ENV"
""",
        )

        # 2) Sanity: usuarios table
        run(
            client,
            f"cd '{APP}' && python3 - <<'PY'\n"
            "from pathlib import Path\n"
            "env={}\n"
            "for line in Path('.env').read_text(encoding='utf-8', errors='replace').splitlines():\n"
            "  line=line.strip()\n"
            "  if not line or line.startswith('#') or '=' not in line: continue\n"
            "  k,v=line.split('=',1); env[k.strip()]=v.strip()\n"
            "import mysql.connector\n"
            "c=mysql.connector.connect(host=env['MYSQL_HOST'], port=int(env['MYSQL_PORT']),\n"
            "  user=env['MYSQL_USER'], password=env['MYSQL_PASSWORD'], database=env['MYSQL_DATABASE'])\n"
            "cur=c.cursor()\n"
            "cur.execute(\"SHOW TABLES LIKE 'usuarios'\")\n"
            "print('has_usuarios', bool(cur.fetchone()))\n"
            "try:\n"
            "  cur.execute('SELECT COUNT(*) FROM usuarios')\n"
            "  print('usuarios_count', cur.fetchone()[0])\n"
            "except Exception as e:\n"
            "  print('usuarios_err', e)\n"
            "c.close()\n"
            "PY",
        )

        # 3) Restart app.py on :2001
        run(
            client,
            f"""
set -e
# Mata processo atual na porta 2001
PID=$(ss -lntp | awk '/:2001/ {{print}}' | sed -n 's/.*pid=\\([0-9]*\\).*/\\1/p' | head -1)
if [ -n "$PID" ]; then
  echo "Killing pid=$PID"
  kill "$PID" || true
  sleep 2
  kill -9 "$PID" 2>/dev/null || true
fi
mkdir -p '{APP}/data'
cd '{APP}'
nohup python3 app.py > '{APP}/data/app_2001.log' 2>&1 &
echo "started pid=$!"
sleep 3
ss -lntp | grep 2001 || true
tail -n 40 '{APP}/data/app_2001.log' || true
""",
            check=False,
        )

        time.sleep(2)
        # 4) Validate URLs
        run(
            client,
            f"""
curl -s -o /dev/null -w 'loja=%{{http_code}}\\n' '{TARGET}'
curl -s -o /dev/null -w 'plain=%{{http_code}}\\n' 'http://127.0.0.1:2001/login/form'
curl -s '{TARGET}' | head -c 500; echo
""",
            check=False,
        )
        # External check from this machine
        print("\n==> Teste externo (PC -> VPS)")
    finally:
        client.close()

    import urllib.request

    url = "http://85.31.231.84:2001/LojaOnline/login/form"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            body = resp.read(800).decode("utf-8", errors="replace")
            print(f"EXTERNAL HTTP {resp.status}")
            print(body[:400])
    except Exception as exc:
        print(f"EXTERNAL FAIL: {exc}")
        raise SystemExit(1)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1)

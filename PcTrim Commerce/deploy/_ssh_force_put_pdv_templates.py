"""Force-upload PDV templates to VPS8 and verify class-tabs CSS."""
from __future__ import annotations

import base64
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
REMOTE = "/var/www/ModuloMesa_Loja_py/PcTrim Commerce"
FILES = [
    ("templates/index.html", f"{REMOTE}/templates/index.html"),
    ("templates/mesa.html", f"{REMOTE}/templates/mesa.html"),
]


def creds():
    fz = Path(os.environ.get("APPDATA", "")) / "FileZilla" / "sitemanager.xml"
    root = ET.parse(fz).getroot()
    for srv in root.findall(".//Server"):
        if (srv.findtext("Host") or "").strip() == "85.31.231.84":
            enc = srv.find("Pass")
            pwd = base64.b64decode(enc.text).decode("utf-8", errors="replace")
            return (
                srv.findtext("Host") or "",
                int(srv.findtext("Port") or "22"),
                srv.findtext("User") or "root",
                pwd,
            )
    raise RuntimeError("VPS8 not found")


def main() -> int:
    host, port, user, pwd = creds()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=pwd, timeout=30)
    try:
        sftp = client.open_sftp()
        try:
            for rel, remote in FILES:
                local = ROOT / rel
                print(f"PUT {local} -> {remote}")
                sftp.put(str(local), remote)
        finally:
            sftp.close()

        _, stdout, stderr = client.exec_command(
            f"""
python3 - <<'PY'
from pathlib import Path
p = Path('{REMOTE}/templates/index.html')
t = p.read_text(encoding='utf-8')
ok_nowrap = 'flex-wrap:nowrap' in t
ok_max = 'max-height:54px' in t
print('nowrap', ok_nowrap)
print('max34', ok_max)
print('size', p.stat().st_size)
if not (ok_nowrap and ok_max):
    raise SystemExit('CSS_CHECK_FAIL')
print('CSS_OK')
PY
# restart
PID=$(ss -lntp 2>/dev/null | awk '/:2001/ {{print}}' | sed -n 's/.*pid=\\([0-9]*\\).*/\\1/p' | head -1)
if [ -n "$PID" ]; then kill "$PID" || true; sleep 2; kill -9 "$PID" 2>/dev/null || true; fi
cd '{REMOTE}'
nohup python3 app.py > '{REMOTE}/data/app_2001.log' 2>&1 &
echo RESTARTED $!
sleep 3
curl -s -D - -o /dev/null http://127.0.0.1:2001/LojaOnline/login/form | grep -iE 'HTTP/|X-App-Version' || true
"""
        )
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
        if err.strip():
            sys.stdout.buffer.write(b"\nSTDERR:\n")
            sys.stdout.buffer.write(err.encode("utf-8", errors="replace")[-1500:])
        code = stdout.channel.recv_exit_status()
        return code
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())

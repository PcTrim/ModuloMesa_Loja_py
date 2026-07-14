#!/usr/bin/env python3
"""Cria/ajusta usuario MySQL pctrim_hml na VPS8."""
from __future__ import annotations

import base64
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib import request

import paramiko

APP = "/var/www/ModuloMesa_Loja_py/PcTrim Commerce"

REMOTE_PY = r"""
from pathlib import Path
import mysql.connector

env = {}
for line in Path(".env").read_text(encoding="utf-8", errors="replace").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    env[k.strip()] = v.strip()

def sql_quote(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"

root = mysql.connector.connect(
    host=env["MYSQL_HOST"],
    port=int(env["MYSQL_PORT"]),
    user=env["MYSQL_USER"],
    password=env["MYSQL_PASSWORD"],
)
cur = root.cursor()
hml_user = env.get("MYSQL_USER_HML") or "pctrim_hml"
hml_pass = env.get("MYSQL_PASSWORD_HML") or ""
hml_db = env.get("MYSQL_DATABASE_HML") or "pctrim_commerce_hml"
print("fixing", hml_user, "on", hml_db)

u = sql_quote(hml_user)
p = sql_quote(hml_pass)
for host in ("localhost", "127.0.0.1", "%"):
    h = sql_quote(host)
    cur.execute(f"CREATE USER IF NOT EXISTS {u}@{h} IDENTIFIED BY {p}")
    cur.execute(f"ALTER USER {u}@{h} IDENTIFIED BY {p}")
    cur.execute(f"GRANT ALL PRIVILEGES ON `{hml_db}`.* TO {u}@{h}")
root.commit()
cur.execute("FLUSH PRIVILEGES")

c2 = mysql.connector.connect(
    host="127.0.0.1",
    port=int(env["MYSQL_PORT"]),
    user=hml_user,
    password=hml_pass,
    database=hml_db,
)
cur2 = c2.cursor()
cur2.execute(
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s",
    (hml_db,),
)
print("HML_OK tables", cur2.fetchone()[0])
c2.close()
root.close()
print("DONE")
"""


def creds():
    fz = Path(os.environ.get("APPDATA", "")) / "FileZilla" / "sitemanager.xml"
    root = ET.parse(fz).getroot()
    for srv in root.findall(".//Server"):
        if (srv.findtext("Host") or "") == "85.31.231.84":
            enc = srv.find("Pass")
            pwd = base64.b64decode(enc.text).decode("utf-8", errors="replace")
            return srv.findtext("Host"), int(srv.findtext("Port") or 22), srv.findtext("User"), pwd
    raise RuntimeError("VPS8 nao encontrada")


def main():
    host, port, user, pwd = creds()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=pwd, timeout=30)
    try:
        # Upload helper script via sftp to avoid quoting hell
        remote = "/tmp/fix_hml_user.py"
        sftp = client.open_sftp()
        with sftp.file(remote, "w") as f:
            f.write(REMOTE_PY)
        sftp.close()
        _, stdout, stderr = client.exec_command(f"cd '{APP}' && python3 {remote}", timeout=60)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        print(out)
        if err.strip():
            print("STDERR:", err)
        print("exit=", code)
        client.exec_command(f"rm -f {remote}")
        if code != 0:
            raise RuntimeError("falha ao criar usuario hml")
        _, stdout, _ = client.exec_command(
            "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:2001/LojaOnline/login/form"
        )
        print("login_form=", stdout.read().decode().strip())
    finally:
        client.close()

    url = "http://85.31.231.84:2001/LojaOnline/login/form"
    with request.urlopen(url, timeout=15) as resp:
        print(f"EXTERNAL {url} -> HTTP {resp.status}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1)

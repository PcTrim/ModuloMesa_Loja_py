#!/usr/bin/env python3
"""Consulta e corrige ambiente do usuário marcio em produção."""
from __future__ import annotations

import base64
import os
import textwrap
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
    raise RuntimeError("Hostinger não encontrado")


def run(client, cmd):
    _, stdout, _ = client.exec_command(cmd, get_pty=True)
    return stdout.read().decode("utf-8", errors="replace")


def main():
    host, port, user, pwd = creds()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=pwd, timeout=30)
    script = textwrap.dedent(
        """
        import os, sys
        sys.path.insert(0, '/var/www/html/LojaOnline')
        os.chdir('/var/www/html/LojaOnline')
        from dotenv import load_dotenv
        load_dotenv()
        import mysql.connector
        conn = mysql.connector.connect(
            host=os.getenv('MYSQL_HOST', '127.0.0.1'),
            user=os.getenv('MYSQL_USER'),
            password=os.getenv('MYSQL_PASSWORD'),
            port=int(os.getenv('MYSQL_PORT') or 3306),
            database=os.getenv('MYSQL_DATABASE', 'pctrim_commerce'),
        )
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT u.usuario, u.id_cliente, d.nome, d.ambiente "
            "FROM usuarios u LEFT JOIN dadosloja d ON d.id_cliente = u.id_cliente "
            "WHERE LOWER(u.usuario) = 'marcio' LIMIT 5"
        )
        rows = cur.fetchall()
        print('ANTES:', rows)
        for r in rows:
            cid = r.get('id_cliente')
            if cid:
                cur2 = conn.cursor()
                cur2.execute(
                    "UPDATE dadosloja SET ambiente = 'production' WHERE id_cliente = %s",
                    (cid,),
                )
                conn.commit()
                cur2.close()
                print('UPDATED id_cliente', cid, '-> production')
        cur.execute(
            "SELECT u.usuario, u.id_cliente, d.nome, d.ambiente "
            "FROM usuarios u LEFT JOIN dadosloja d ON d.id_cliente = u.id_cliente "
            "WHERE LOWER(u.usuario) = 'marcio' LIMIT 5"
        )
        print('DEPOIS:', cur.fetchall())
        cur.close()
        conn.close()
        """
    ).strip()
    b64 = base64.b64encode(script.encode()).decode()
    try:
        out = run(
            client,
            f"cd {REMOTE} && source .venv/bin/activate && "
            f"python -c \"import base64; exec(base64.b64decode('{b64}'))\"",
        )
        print(out)
        out2 = run(
            client,
            f"cd {REMOTE} && source .venv/bin/activate && python -c "
            "\"from services.login_tenant_db import locate_login_user; print(locate_login_user('marcio'))\"",
        )
        print(out2)
    finally:
        client.close()


if __name__ == "__main__":
    main()

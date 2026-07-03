#!/usr/bin/env python3
"""Lê senha HML do servidor (não imprime)."""
import base64, os, xml.etree.ElementTree as ET
from pathlib import Path
import paramiko

fz = Path(os.environ["APPDATA"]) / "FileZilla" / "sitemanager.xml"
root = ET.parse(fz).getroot()
for srv in root.findall(".//Server"):
    n = (srv.findtext("Name") or "").lower()
    if "hostinger" in n or "hostinguer" in n:
        host, port = srv.findtext("Host"), int(srv.findtext("Port") or 22)
        user, pwd = srv.findtext("User"), base64.b64decode(srv.find("Pass").text).decode("utf-8", "replace")
        break
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(host, port=port, username=user, password=pwd, timeout=30)
_, o, _ = c.exec_command("grep PCTrim_HML_PASSWORD /root/mysql_migration_20260702_173205/mysql_users_credentials.env", timeout=20)
line = o.read().decode().strip()
c.close()
print(line.split("=", 1)[1] if "=" in line else "")

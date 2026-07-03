#!/usr/bin/env python3
import base64, os, xml.etree.ElementTree as ET
from pathlib import Path
import paramiko

fz = Path(os.environ["APPDATA"]) / "FileZilla" / "sitemanager.xml"
root = ET.parse(fz).getroot()
for srv in root.findall(".//Server"):
    n = (srv.findtext("Name") or "").lower()
    if "hostinger" in n or "hostinguer" in n:
        host = srv.findtext("Host")
        port = int(srv.findtext("Port") or 22)
        user = srv.findtext("User")
        pwd = base64.b64decode(srv.find("Pass").text).decode("utf-8", errors="replace")
        break
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(host, port=port, username=user, password=pwd, timeout=30)
_, o, _ = c.exec_command("cat /etc/apache2/sites-enabled/000-default-le-ssl.conf", timeout=30)
print(o.read().decode())
c.close()

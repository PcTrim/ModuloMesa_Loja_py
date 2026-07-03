#!/usr/bin/env python3
import base64, os, re, xml.etree.ElementTree as ET
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

cmd = r"""
grep LOJA_URL /var/www/html/LojaOnline/.env /var/www/html/LojaOnline_hml/.env
echo '--- static tests ---'
for u in \
  'https://pedidofacil.online/LojaOnlineHml/static/ui_touch.css' \
  'https://pedidofacil.online/LojaOnlineHml/static/topbar_meta.css' \
  'https://pedidofacil.online/LojaOnline/static/ui_touch.css'; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "$u")
  echo "$code $u"
done
echo '--- html static refs ---'
curl -s https://pedidofacil.online/LojaOnlineHml/login | grep -oE 'href="[^"]+\.css[^"]*"|src="[^"]+\.css[^"]*"' | head -10
"""
_, o, _ = c.exec_command(cmd, timeout=60)
print(o.read().decode())
c.close()

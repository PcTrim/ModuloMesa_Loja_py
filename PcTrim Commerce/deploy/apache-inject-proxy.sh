#!/bin/bash

# Insere proxy LojaOnline em /LojaOnline/ no VirtualHost de pedidofacil.online.

set -e

ARQUIVO=$(grep -l "ServerName pedidofacil.online" /etc/apache2/sites-enabled/* 2>/dev/null | head -1)

if [ -z "$ARQUIVO" ]; then

  echo "Nenhum site com ServerName pedidofacil.online em sites-enabled."

  exit 1

fi

echo "Arquivo: $ARQUIVO"

if grep -q "ProxyPass /LojaOnline/" "$ARQUIVO"; then

  echo "Proxy /LojaOnline/ ja existe neste arquivo."

  exit 0

fi

# Remover proxy na raiz (conflita com outro site)

if grep -q "ProxyPass / http://127.0.0.1:8001/" "$ARQUIVO"; then

  echo "Removendo ProxyPass / (raiz) — use apenas /LojaOnline/"

  sudo sed -i '/ProxyPass \/ http:\/\/127.0.0.1:8001\//d' "$ARQUIVO"

  sudo sed -i '/ProxyPassReverse \/ http:\/\/127.0.0.1:8001\//d' "$ARQUIVO"

  sudo sed -i '/ProxyPass \/static !/d' "$ARQUIVO"

  sudo sed -i '/Alias \/static \/var\/www\/html\/LojaOnline\/static/d' "$ARQUIVO"

  sudo sed -i '/Directory \/var\/www\/html\/LojaOnline\/static/,/<\/Directory>/d' "$ARQUIVO"

fi

sudo cp "$ARQUIVO" "${ARQUIVO}.bak.$(date +%Y%m%d%H%M%S)"

sudo perl -i -0pe 's|</VirtualHost>|    ProxyPreserveHost On\n    RequestHeader set X-Forwarded-Proto "https"\n    Alias /LojaOnline/static /var/www/html/LojaOnline/static\n    <Directory /var/www/html/LojaOnline/static>\n        Require all granted\n    </Directory>\n    ProxyPass /LojaOnline/static !\n    ProxyPass /LojaOnline/ http://127.0.0.1:8001/\n    ProxyPassReverse /LojaOnline/ http://127.0.0.1:8001/\n</VirtualHost>|' "$ARQUIVO"

echo "Proxy /LojaOnline/ inserido. Teste:"

sudo apache2ctl configtest

echo "Se Syntax OK: sudo systemctl reload apache2"

echo "No .env: LOJA_URL_PREFIX=/LojaOnline"

echo "URL: https://pedidofacil.online/LojaOnline/login/form"


#!/bin/bash
# Atualizacao pos-upload (Fases 3-4 do deploy).
# Uso: cd /var/www/html/LojaOnline && bash deploy/update_production.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

echo "==> LojaOnline update em $APP_DIR"

if [ ! -f .env ]; then
  echo "ERRO: .env nao encontrado. Nao sobrescreva o .env de producao."
  exit 1
fi

bash deploy/fix_scripts_no_servidor.sh

if [ ! -d .venv ]; then
  echo "==> Criando venv..."
  python3 -m venv .venv
fi

# shellcheck source=/dev/null
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

bash deploy/bootstrap_schema.sh

mkdir -p data/pedidos_salvos data/relatorios
if id www-data >/dev/null 2>&1; then
  sudo chown -R www-data:www-data data
fi
chmod 755 data data/pedidos_salvos data/relatorios

echo "==> Reiniciando lojaonline..."
sudo systemctl restart lojaonline
sleep 2
sudo systemctl status lojaonline --no-pager || true

echo "==> Teste local Gunicorn:"
HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/login/form || echo '000')"
echo "curl /login/form => HTTP $HTTP_CODE"

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ]; then
  echo "==> Update OK"
else
  echo "AVISO: HTTP inesperado. Verifique: journalctl -u lojaonline -n 80 --no-pager"
  exit 1
fi

echo ""
echo "==> Versao em version.py:"
grep -E '^APP_VERSION' version.py || true

BUILD_BODY="$(curl -s http://127.0.0.1:8001/loja-build || true)"
echo "==> /loja-build:"
echo "$BUILD_BODY" | head -n 8

FILE_VER="$(grep -E '^APP_VERSION' version.py | sed -n 's/.*"\([^"]*\)".*/\1/p')"
RUN_VER="$(echo "$BUILD_BODY" | sed -n 's/^APP_VERSION=//p' | head -n 1)"
if [ -n "$FILE_VER" ] && [ -n "$RUN_VER" ] && [ "$FILE_VER" != "$RUN_VER" ]; then
  echo "AVISO: versao no disco ($FILE_VER) difere da versao em execucao ($RUN_VER). Reinicie lojaonline."
  exit 1
fi
if [ -n "$RUN_VER" ]; then
  echo "==> Versao ativa confirmada: $RUN_VER"
fi

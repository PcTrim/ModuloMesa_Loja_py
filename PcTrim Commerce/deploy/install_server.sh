#!/bin/bash
# Instalacao inicial no servidor Linux (rode via SSH na pasta do app).
# Uso: cd /var/www/html/LojaOnline && bash deploy/install_server.sh
set -e
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

echo "==> Pasta: $APP_DIR"

if [ ! -f .env ]; then
  echo "Crie .env a partir de deploy/env.production.example antes de continuar."
  exit 1
fi

python3 -m venv .venv
# shellcheck source=/dev/null
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

mkdir -p data/pedidos_salvos data/relatorios
chmod 755 data data/pedidos_salvos data/relatorios

echo "==> Proximo: bash deploy/bootstrap_schema.sh"
echo "==> Depois: sudo cp deploy/lojaonline.service /etc/systemd/system/"
echo "==> sudo systemctl daemon-reload && sudo systemctl enable --now lojaonline"

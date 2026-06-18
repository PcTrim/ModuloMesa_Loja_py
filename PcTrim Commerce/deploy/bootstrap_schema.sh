#!/bin/bash
# Rode UMA VEZ no servidor apos o primeiro deploy (SSH).
set -e
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"
if [ -f .venv/bin/activate ]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi
if [ ! -f .env ]; then
  echo "Arquivo .env nao encontrado em $APP_DIR"
  exit 1
fi
python -c "from dotenv import load_dotenv; load_dotenv(); from app import bootstrap_schema; bootstrap_schema(); print('bootstrap_schema OK')"

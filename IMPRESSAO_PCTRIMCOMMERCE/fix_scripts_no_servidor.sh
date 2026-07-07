#!/bin/bash
# Corrige fins de linha Windows (CRLF) nos scripts apos upload pelo FileZilla.
# Uso: cd /var/www/html/LojaOnline && bash deploy/fix_scripts_no_servidor.sh
set -e
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"
for f in deploy/*.sh; do
  if [ -f "$f" ]; then
    sed -i 's/\r$//' "$f"
    chmod +x "$f"
    echo "OK: $f"
  fi
done
sed -i 's/\r$//' deploy/lojaonline.service 2>/dev/null || true
if [ -f requirements.txt ] && grep -q $'\x00' requirements.txt 2>/dev/null; then
  printf '%s\n' \
    'Flask>=3.0,<4' \
    'python-dotenv>=1.0,<2' \
    'mysql-connector-python>=8.0,<10' \
    'requests>=2.28,<3' \
    'bcrypt>=4.0,<5' \
    'gunicorn>=21.0,<24' \
    > requirements.txt
  echo "OK: requirements.txt recriado (UTF-8)"
fi
echo "Scripts prontos para Linux."

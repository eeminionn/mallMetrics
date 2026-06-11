#!/bin/zsh

set -e

PROJECT_DIR="/Users/eeminionn/Documents/Codex/2026-06-10/necesito-que-busques-un-repositorio-en/work/mallMetrics"
HOST="127.0.0.1"
PORT="8000"
URL="http://${HOST}:${PORT}/"

cd "$PROJECT_DIR"

echo "mallMetrics"
echo "Proyecto: $PROJECT_DIR"
echo "URL: $URL"
echo

if lsof -iTCP:${PORT} -sTCP:LISTEN -n -P >/dev/null 2>&1; then
  echo "Ya hay un proceso usando el puerto ${PORT}."
  echo "Si ese proceso es mallMetrics, abre:"
  echo "$URL"
  echo
  read -r "?Presiona Enter para cerrar..."
  exit 0
fi

echo "Levantando servidor Django..."
echo "Para detenerlo, usa Control-C en esta ventana."
echo

exec python3 manage.py runserver ${HOST}:${PORT}

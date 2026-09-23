#!/usr/bin/env bash
# Режим разработки: backend (uvicorn --reload, :8000) + frontend (Vite, :5173, проксирует /api на :8000)
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  echo "→ Создаю виртуальное окружение и ставлю зависимости…"
  python3 -m venv .venv
  .venv/bin/pip install -r backend/requirements-dev.txt
fi
if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm ci)
fi

trap 'kill 0' EXIT
(cd backend && ../.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000) &
(cd frontend && npm run dev -- --host 127.0.0.1) &
echo ""
echo "  Интерфейс:  http://localhost:5173   (админ-панель: http://localhost:5173/admin)"
echo "  API docs:   http://localhost:8000/api/docs"
echo ""
wait

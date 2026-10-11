#!/usr/bin/env bash
# 백엔드(FastAPI :8000)와 대시보드(Next.js :3000)를 함께 실행 — 모두 localhost에만 바인딩
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -d "$ROOT/backend/.venv" ]; then
  python3 -m venv "$ROOT/backend/.venv"
  "$ROOT/backend/.venv/bin/pip" install -q -e "$ROOT/backend[dev]"
fi
[ -d "$ROOT/web/node_modules" ] || (cd "$ROOT/web" && npm install)
[ -f "$ROOT/backend/.env" ] || { cp "$ROOT/backend/.env.example" "$ROOT/backend/.env"; echo "backend/.env 생성됨 — DASHBOARD_PASSWORD를 바꾸세요"; }

trap 'kill 0' EXIT
(cd "$ROOT/backend" && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) &
(cd "$ROOT/web" && npm run dev -- --hostname 127.0.0.1 --port 3000) &
wait

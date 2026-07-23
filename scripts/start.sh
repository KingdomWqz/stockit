#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT/.pids"

mkdir -p "$PID_DIR"

# ---------- Server (FastAPI) ----------
echo "==> Starting server (FastAPI + uvicorn) ..."
cd "$ROOT/server"
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_DIR/server.pid"
echo "    server pid: $SERVER_PID  (http://localhost:8000)"

# ---------- Web (Next.js) ----------
echo "==> Starting web (Next.js dev) ..."
cd "$ROOT/web"
npm run dev &
WEB_PID=$!
echo "$WEB_PID" > "$PID_DIR/web.pid"
echo "    web pid:    $WEB_PID  (http://localhost:3000)"

echo ""
echo "Both services started. Use scripts/stop.sh to stop."

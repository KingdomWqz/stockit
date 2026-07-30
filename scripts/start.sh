#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT/.pids"

mkdir -p "$PID_DIR"

# Return 0 if something is already listening on $1
port_in_use() { ss -ltn 2>/dev/null | grep -q ":$1 "; }

# ---------- Server (FastAPI) ----------
if port_in_use 8000; then
    echo "==> server: port 8000 already in use, skipping (already running?)"
    rm -f "$PID_DIR/server.pid"
else
    echo "==> Starting server (FastAPI + uvicorn) ..."
    cd "$ROOT/server"
    uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
    SERVER_PID=$!
    echo "$SERVER_PID" > "$PID_DIR/server.pid"
    echo "    server pid: $SERVER_PID  (http://localhost:8000)"
fi

# ---------- Web (Next.js) ----------
if port_in_use 3000; then
    echo "==> web: port 3000 already in use, skipping (already running?)"
    rm -f "$PID_DIR/web.pid"
else
    echo "==> Starting web (Next.js dev) ..."
    cd "$ROOT/web"
    npm run dev &
    WEB_PID=$!
    echo "$WEB_PID" > "$PID_DIR/web.pid"
    echo "    web pid:    $WEB_PID  (http://localhost:3000)"
fi

echo ""
echo "Done. Use scripts/stop.sh to stop; run stop.sh then start.sh to restart."

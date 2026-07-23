#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT/.pids"

stop_one() {
    local name="$1"
    local pid_file="$PID_DIR/$name.pid"

    if [ ! -f "$pid_file" ]; then
        echo "==> $name: no pid file, skipping"
        return
    fi

    local pid
    pid=$(cat "$pid_file")

    if kill -0 "$pid" 2>/dev/null; then
        echo "==> Stopping $name (pid $pid) ..."
        kill "$pid"
        # Wait a bit for graceful shutdown, then force kill if still alive
        sleep 1
        if kill -0 "$pid" 2>/dev/null; then
            echo "    forcing kill ..."
            kill -9 "$pid" 2>/dev/null || true
        fi
        echo "    $name stopped"
    else
        echo "==> $name: pid $pid not alive, cleaning up"
    fi

    rm -f "$pid_file"
}

stop_one "server"
stop_one "web"

echo ""
echo "All services stopped."

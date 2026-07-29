#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT/.pids"

# Stop a process recorded in a pid file (if present and alive).
stop_one() {
    local name="$1" pid_file="$2"

    if [ ! -f "$pid_file" ]; then
        echo "==> $name: no pid file"
        return 0
    fi

    local pid
    pid=$(cat "$pid_file")

    if kill -0 "$pid" 2>/dev/null; then
        echo "==> Stopping $name (pid $pid) ..."
        kill "$pid" 2>/dev/null || true
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

# Kill anything still listening on a port — cleans up orphans without pid files
# (e.g. a `next dev` whose parent `npm run dev` already exited).
kill_port() {
    local name="$1" port="$2"
    local pids
    pids=$(ss -ltnp 2>/dev/null | grep ":$port " | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u)
    [ -z "$pids" ] && return 0
    echo "==> $name: leftover on :$port (pid $pids), killing ..."
    echo "$pids" | xargs -r kill 2>/dev/null || true
    sleep 1
    echo "$pids" | xargs -r kill -9 2>/dev/null || true
}

stop_one "server" "$PID_DIR/server.pid"
kill_port "server" 8000
stop_one "web" "$PID_DIR/web.pid"
kill_port "web" 3000

echo ""
echo "All services stopped."

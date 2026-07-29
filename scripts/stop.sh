#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT/.pids"
VENV="$ROOT/server/.venv/bin/python"

# Wait up to $3 seconds for pid to die, return 1 if still alive.
wait_dead() {
    local pid="$1" secs="${2:-3}" i
    for ((i = 0; i < secs * 10; i++)); do
        kill -0 "$pid" 2>/dev/null || return 0
        sleep 0.1
    done
    return 1
}

# Kill a pid and its entire child process tree.
kill_tree() {
    local pid="$1"
    # Kill children first (depth-first)
    local children
    children=$(pgrep -P "$pid" 2>/dev/null || true)
    for child in $children; do
        kill_tree "$child"
    done
    kill "$pid" 2>/dev/null || true
}

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
        kill_tree "$pid"
        if ! wait_dead "$pid" 3; then
            echo "    forcing kill ..."
            kill -9 "$pid" 2>/dev/null || true
            pkill -9 -P "$pid" 2>/dev/null || true
        fi
        echo "    $name stopped"
    else
        echo "==> $name: pid $pid not alive, cleaning up"
    fi

    rm -f "$pid_file"
}

# Kill anything still listening on a port (cleans up orphans without pid files).
kill_port() {
    local name="$1" port="$2"
    local pids
    pids=$(ss -ltnp 2>/dev/null | grep ":$port " | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u)
    [ -z "$pids" ] && return 0
    echo "==> $name: leftover on :$port (pid $pids), killing ..."
    echo "$pids" | xargs -r kill_tree 2>/dev/null || true
    sleep 0.5
    echo "$pids" | xargs -r kill -9 2>/dev/null || true
}

# Kill any remaining worker processes using the project venv (orphaned forks, etc.).
kill_venv_orphans() {
    local pids
    pids=$(pgrep -f "$VENV" 2>/dev/null || true)
    [ -z "$pids" ] && return 0
    echo "==> Cleaning up orphaned venv processes: $pids"
    echo "$pids" | xargs -r kill 2>/dev/null || true
    sleep 0.5
    echo "$pids" | xargs -r kill -9 2>/dev/null || true
}

stop_one "server" "$PID_DIR/server.pid"
kill_port "server" 8000
stop_one "web" "$PID_DIR/web.pid"
kill_port "web" 3000
kill_venv_orphans

echo ""
echo "All services stopped."

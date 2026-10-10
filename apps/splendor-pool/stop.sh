#!/usr/bin/env bash
# Stop Splendor Pool services
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ -f logs/worker.pid ]; then
    PID="$(cat logs/worker.pid)"
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping worker (PID: $PID)..."
        kill "$PID" 2>/dev/null || true
    fi
    rm -f logs/worker.pid
fi

if [ -f logs/web.pid ]; then
    PID="$(cat logs/web.pid)"
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping web service (PID: $PID)..."
        kill "$PID" 2>/dev/null || true
    fi
    rm -f logs/web.pid
fi

echo "Splendor Pool services stopped."

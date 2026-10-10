#!/usr/bin/env bash
# Start Splendor Pool Web and Worker daemon processes
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

mkdir -p logs

export PYTHONPATH="${DIR}:${PYTHONPATH:-}"

# Check and start web service
if [ -f logs/web.pid ] && kill -0 "$(cat logs/web.pid 2>/dev/null)" 2>/dev/null; then
    echo "Web service is already running (PID: $(cat logs/web.pid))"
else
    nohup python3 -u -m splendor_pool --config config.toml serve > logs/web.log 2>&1 </dev/null &
    WEB_PID=$!
    echo "$WEB_PID" > logs/web.pid
    disown "$WEB_PID" 2>/dev/null || true
    echo "Web service started (PID: $WEB_PID) -> http://127.0.0.1:8720/"
fi

# Check and start worker process
if [ -f logs/worker.pid ] && kill -0 "$(cat logs/worker.pid 2>/dev/null)" 2>/dev/null; then
    echo "Worker is already running (PID: $(cat logs/worker.pid))"
else
    nohup python3 -u -m splendor_pool --config config.toml worker > logs/worker.log 2>&1 </dev/null &
    WORKER_PID=$!
    echo "$WORKER_PID" > logs/worker.pid
    disown "$WORKER_PID" 2>/dev/null || true
    echo "Worker started (PID: $WORKER_PID)"
fi

echo "Splendor Pool services are online."

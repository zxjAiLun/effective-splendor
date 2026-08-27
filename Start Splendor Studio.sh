#!/usr/bin/env bash
# Start Splendor Studio (Linux): Studio Host + Replay Studio UI.
# - Starts the Rust Studio Host (port 43120) if not already running,
#   with the M36A experiment replay sources registry attached.
# - Starts the Replay Studio dev server (port 4173) if not already running.
# - Waits for readiness, then opens http://127.0.0.1:4173/experiments
# Usage: ./Start\ Splendor\ Studio.sh [--no-browser] [--open <path>]
set -u

cd "$(dirname "$0")"

REGISTRY="$PWD/benchmarks/studio-1v1.registry.json"
REVIEWERREGISTRY="$PWD/benchmarks/studio-reviewers.registry.json"
REPLAYSOURCES="$PWD/benchmarks/studio-replay-sources.registry.json"
LOGROOT="$PWD/local-artifacts/studio-host"
HOST_PORT=43120
UI_PORT=4173
OPEN_PATH="/experiments"
NO_BROWSER=0

while [ $# -gt 0 ]; do
  case "$1" in
    --no-browser) NO_BROWSER=1 ;;
    --open) shift; OPEN_PATH="$1" ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
  shift
done

if [ ! -f "$REGISTRY" ]; then
  echo "Missing Studio registry: $REGISTRY"
  exit 1
fi
if [ ! -f "$REVIEWERREGISTRY" ]; then
  echo "Missing reviewer registry: $REVIEWERREGISTRY"
  exit 1
fi
if [ ! -f "$REPLAYSOURCES" ]; then
  echo "Missing replay sources registry: $REPLAYSOURCES"
  exit 1
fi
mkdir -p "$LOGROOT"

http_ok() { curl -sf -o /dev/null --max-time 2 "$1"; }

# A healthy Host is not enough: it must be THIS stack's Host, i.e. one that
# actually loaded the M36A experiment replay sources registry. Probe the
# experiment replay index for its format/version and the expected experiment.
host_healthy() {
  http_ok "http://127.0.0.1:$HOST_PORT/health" || return 1
  curl -sf --max-time 2 "http://127.0.0.1:$HOST_PORT/health" | grep -q '"mode":"studio_host"' || return 1
  local index
  index="$(curl -sf --max-time 3 "http://127.0.0.1:$HOST_PORT/experiment-replays")" || return 1
  printf '%s' "$index" | grep -q '"format":"effective-splendor-experiment-replay-index"' || return 1
  printf '%s' "$index" | grep -q '"version":1' || return 1
  printf '%s' "$index" | grep -q '"id":"m35a"' || return 1
}

ui_healthy() { http_ok "http://127.0.0.1:$UI_PORT/play"; }

echo "Building splendor-cli…"
if ! cargo build -p splendor-cli; then
  echo "Rust build failed."
  exit 1
fi

if host_healthy; then
  echo "Studio Host (with experiment replays) already running on port $HOST_PORT."
else
  # A port that answers /health but not the experiment-replay probe is an
  # OLD Host without the M36A replay registry — refuse rather than reuse it.
  if http_ok "http://127.0.0.1:$HOST_PORT/health"; then
    echo "Port $HOST_PORT is held by a Host WITHOUT experiment replay sources."
    echo "Stop it first (see $LOGROOT/host.pid) and rerun this script."
    exit 1
  fi
  echo "Starting Studio Host on port $HOST_PORT…"
  nohup "$PWD/target/debug/splendor" studio-host \
    --registry "$REGISTRY" \
    --reviewer-registry "$REVIEWERREGISTRY" \
    --replay-sources "$REPLAYSOURCES" \
    --port "$HOST_PORT" \
    >> "$LOGROOT/host.stdout.log" 2>> "$LOGROOT/host.stderr.log" &
  echo $! > "$LOGROOT/host.pid"
fi

if [ ! -d "$PWD/apps/replay-studio/node_modules" ]; then
  echo "Installing frontend dependencies…"
  (cd "$PWD/apps/replay-studio" && npm install) || { echo "npm install failed."; exit 1; }
fi

if ui_healthy; then
  echo "Replay Studio UI already running on port $UI_PORT."
else
  echo "Starting Replay Studio UI on port $UI_PORT…"
  (cd "$PWD/apps/replay-studio" && nohup npm run dev -- --host 127.0.0.1 --port "$UI_PORT" \
    >> "$LOGROOT/ui.stdout.log" 2>> "$LOGROOT/ui.stderr.log" & echo $! > "$LOGROOT/ui.pid")
fi

echo "Waiting for readiness…"
READY=0
for _ in $(seq 1 120); do
  if host_healthy && ui_healthy; then
    READY=1
    break
  fi
  sleep 0.5
done

if [ "$READY" -ne 1 ]; then
  echo "Studio did not become ready. Inspect $LOGROOT (host.stdout.log / host.stderr.log / ui.*.log)."
  exit 1
fi

URL="http://127.0.0.1:$UI_PORT$OPEN_PATH"
echo "Studio ready: $URL"
if [ "$NO_BROWSER" -ne 1 ]; then
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 || true
  else
    echo "xdg-open not available; open $URL manually."
  fi
fi

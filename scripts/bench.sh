#!/usr/bin/env bash
# Benchmark the random self-play engine and write a baseline snapshot.
#
# Usage: scripts/bench.sh [games] [players] [seed]
#
# Writes one valid JSON snapshot to benchmarks/baseline.json capturing the
# environment and throughput. It does NOT store large self-play datasets or
# model weights (those belong in releases / object storage).

set -euo pipefail

GAMES="${1:-20000}"
PLAYERS="${2:-2}"
SEED="${3:-0}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RUST_VERSION="$(rustc --version | awk '{print $2}')"
OS="$(uname -srm 2>/dev/null || echo unknown)"
CPU="$(uname -m 2>/dev/null || echo unknown)"

# Run the bench and capture its machine-readable stdout.
OUT="$(cargo run --locked -q -r -p splendor-cli -- bench --games "$GAMES" --players "$PLAYERS" --seed "$SEED")"

GAMES_PER_S="$(echo "$OUT" | awk -F= '/^games_per_s=/{print $2}')"
ACTIONS_PER_S="$(echo "$OUT" | awk -F= '/^actions_per_s=/{print $2}')"
ACTIONS_PER_GAME="$(echo "$OUT" | awk -F= '/^avg_actions_per_game=/{print $2}')"
AVG_LEGAL_ACTIONS="$(echo "$OUT" | awk -F= '/^avg_legal_actions_per_decision=/{print $2}')"
MAX_LEGAL_ACTIONS="$(echo "$OUT" | awk -F= '/^max_legal_actions_seen=/{print $2}')"

RECORD="$(cat <<EOF
{
  "commit": "$(git rev-parse HEAD 2>/dev/null || echo unknown)",
  "rust_version": "$RUST_VERSION",
  "os": "$OS",
  "cpu": "$CPU",
  "players": $PLAYERS,
  "games": $GAMES,
  "invariants_enabled": true,
  "games_per_s": $GAMES_PER_S,
  "actions_per_s": $ACTIONS_PER_S,
  "actions_per_game": $ACTIONS_PER_GAME,
  "avg_legal_actions_per_decision": $AVG_LEGAL_ACTIONS,
  "max_legal_actions_seen": $MAX_LEGAL_ACTIONS
}
EOF
)"

mkdir -p benchmarks
printf '%s\n' "$RECORD" > benchmarks/baseline.json
echo "wrote baseline record:"
echo "$RECORD"

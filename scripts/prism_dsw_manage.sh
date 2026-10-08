#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$task_root/.venv/bin/python" -B "$task_root/scripts/prism_dsw_arena.py" "$@"

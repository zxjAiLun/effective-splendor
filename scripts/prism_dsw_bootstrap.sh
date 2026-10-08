#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -d "$task_root/.venv" ]]; then
  python3 -m venv "$task_root/.venv"
fi
task_system_version="$(python3 -c 'import sys; print(sys.version_info[:2])')"
task_venv_version="$("$task_root/.venv/bin/python" -c 'import sys; print(sys.version_info[:2])')"
if [[ "$task_system_version" != "$task_venv_version" ]]; then
  echo 'Python ABI changed. Preserve the old .venv, create a new one here, then rerun bootstrap.' >&2
  exit 1
fi
"$task_root/.venv/bin/python" -m pip install --disable-pip-version-check -r "$task_root/notebooks/requirements-prism-arena.txt"
exec bash "$task_root/scripts/prism_dsw_manage.sh" profile

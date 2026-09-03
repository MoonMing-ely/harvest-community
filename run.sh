#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$project_dir"

runtime_lock="$project_dir/requirements/runtime.lock"
lock_snapshot="$project_dir/.venv/.harvest-runtime.lock"
needs_install=0
if [[ ! -x .venv/bin/python ]] || [[ ! -f "$lock_snapshot" ]] || ! cmp -s "$runtime_lock" "$lock_snapshot"; then
  needs_install=1
fi

if [[ "$needs_install" == "1" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    python_command=python3
  elif command -v python >/dev/null 2>&1; then
    python_command=python
  else
    echo "未找到 Python 3.11 或更高版本。请先安装 Python。" >&2
    exit 1
  fi
  if ! "$python_command" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
    echo "Python 版本低于 3.11。请先升级 Python。" >&2
    exit 1
  fi
  if [[ -d "$project_dir/.venv" ]]; then
    rm -rf -- "$project_dir/.venv"
  fi
  "$python_command" -m venv .venv
  .venv/bin/python -m pip install -q --require-hashes -r "$runtime_lock"
  cp "$runtime_lock" "$lock_snapshot"
fi
export PYTHONPATH="$project_dir/src"
exec .venv/bin/python -m harvest "$@"

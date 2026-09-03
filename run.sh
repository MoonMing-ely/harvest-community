#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$project_dir"

needs_install=0
if [[ ! -x .venv/bin/python ]]; then
  if command -v python3 >/dev/null 2>&1; then
    python_command=python3
  elif command -v python >/dev/null 2>&1; then
    python_command=python
  else
    echo "未找到 Python 3.11 或更高版本。请先安装 Python。" >&2
    exit 1
  fi
  "$python_command" -m venv .venv
  needs_install=1
fi

if ! .venv/bin/python -c "import harvest" >/dev/null 2>&1; then
  needs_install=1
fi
if [[ "$needs_install" == "1" ]]; then
  .venv/bin/python -m pip install -q -e .
fi
exec .venv/bin/harvest "$@"

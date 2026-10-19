#!/usr/bin/env bash
# Create the Python environment exactly as locked. Usage: bash setup/install_py.sh  (then: source setup/.venv/bin/activate)
set -euo pipefail
cd "$(dirname "$0")"
uv sync --frozen
echo "python env ready: $(uv run python -c 'import duckdb,pyarrow;print(duckdb.__version__, pyarrow.__version__)')"

#!/usr/bin/env bash
# Selran Hub — P1 bootstrap (spec §9): venv + editable install.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"
"$PY" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" -q install --upgrade pip
"$ROOT/.venv/bin/pip" -q install -e "$ROOT"
echo "Selran Hub ready. Run: $ROOT/run_hub.sh  (or .venv/bin/selran-hub serve)"

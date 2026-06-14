#!/usr/bin/env bash
# Selran Hub — run the daemon (default port 11999; override with SELRAN_HUB_PORT).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m selran_hub serve

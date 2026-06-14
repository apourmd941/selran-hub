#!/usr/bin/env bash
#
# Build the Selran Hub MCP Bundle (.mcpb) — a one-click Desktop Extension that
# connects Claude Desktop to the local Selran Hub bridge.
#
#   scripts/build_mcpb.sh            # assemble + validate + pack -> dist/
#   scripts/build_mcpb.sh --sign     # also sign (needs a signing identity)
#
# The bundle ships server/main.py + server/mcp_bridge.py + server/lib/ (the
# bridge's deps for THIS platform: mcp, httpx, pydantic). The Hub daemon itself
# is installed separately (pipx / the signed app) — the bundle is just the
# bridge that talks to it.
#
# NOTE: server/lib carries native wheels (pydantic-core) for the build platform,
# so build on each target OS for a cross-platform release. Signing + notarization
# + directory submission are release steps (see docs/MCPB.md), gated on the
# Apple Developer ID.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY="python3"
MCPB="npx --yes @anthropic-ai/mcpb@latest"

VERSION="$("$PY" -c 'import re,sys; t=open("selran_hub/config.py").read(); print(re.search(r"VERSION\s*=\s*\"([^\"]+)\"", t).group(1))')"
echo "→ Selran Hub version: $VERSION"

BUILD="$(mktemp -d)/selran-hub-mcpb"
mkdir -p "$BUILD/server/lib"

# Manifest (version kept in lockstep with config.py)
"$PY" - "$VERSION" "$ROOT/mcpb/manifest.json" "$BUILD/manifest.json" <<'PY'
import json, sys
version, src, dst = sys.argv[1], sys.argv[2], sys.argv[3]
m = json.load(open(src))
m["version"] = version
json.dump(m, open(dst, "w"), indent=2)
PY

# Server: the entry shim + the self-contained bridge (no intra-package imports)
cp mcpb/server/main.py "$BUILD/server/main.py"
cp selran_hub/mcp_bridge.py "$BUILD/server/mcp_bridge.py"

# Bridge dependencies for this platform
echo "→ installing bridge deps into the bundle…"
"$PY" -m pip install --quiet --target "$BUILD/server/lib" "mcp>=1.0" "httpx" "pydantic>=2"
# Trim caches to keep the bundle small
find "$BUILD/server/lib" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "$BUILD/server/lib" -type d -name '*.dist-info' -prune -exec rm -rf {} + 2>/dev/null || true

mkdir -p dist
OUT="dist/selran-hub-${VERSION}.mcpb"

echo "→ validating manifest…"
$MCPB validate "$BUILD/manifest.json"
echo "→ packing…"
$MCPB pack "$BUILD" "$OUT"
echo "→ bundle info:"
$MCPB info "$OUT"

if [ "${1:-}" = "--sign" ]; then
  echo "→ signing…"
  # Self-signed by default; pass a real identity via MCPB_SIGN_ARGS for release.
  $MCPB sign "$OUT" ${MCPB_SIGN_ARGS:---self-signed}
  $MCPB verify "$OUT"
fi

echo "✓ built $OUT"

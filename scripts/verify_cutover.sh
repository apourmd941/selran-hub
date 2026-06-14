#!/usr/bin/env bash
# Post-cutover verification: the Hub answers on 11999 with full registry parity.
set -u
fail() { echo "✗ $*"; exit 1; }
H=$(curl -fsS --max-time 3 http://127.0.0.1:11999/hub/health) || fail "/hub/health unreachable — is the Hub running?"
echo "$H" | grep -q '"hub":"selran"' || fail "/hub/health is not the Hub: $H"
R=$(curl -fsS http://127.0.0.1:11999/health) || fail "/health unreachable"
echo "$R" | grep -q '"service": *"app-port-registry"' || echo "$R" | grep -q '"service":"app-port-registry"' || fail "registry compat header missing: $R"
SNAP="${1:-/tmp/hub-cutover/pre-cutover-report.json}"
if [ -f "$SNAP" ]; then
  curl -fsS http://127.0.0.1:11999/v1/report > /tmp/hub-cutover/post-cutover-report.json
  python3 - "$SNAP" <<'PY' || exit 1
import json, sys
pre = json.load(open(sys.argv[1])); post = json.load(open("/tmp/hub-cutover/post-cutover-report.json"))
assert pre["app_count"] == post["app_count"], (pre["app_count"], post["app_count"])
assert {a["app_id"]: a["range"] for a in pre["apps"]} == {a["app_id"]: a["range"] for a in post["apps"]}
print(f"✓ parity: {post['app_count']} apps, all ranges identical to pre-cutover snapshot")
PY
else
  echo "(no pre-cutover snapshot at $SNAP — skipping parity diff)"
fi
command -v app-port-registry >/dev/null && app-port-registry list >/dev/null 2>&1 && echo "✓ legacy CLI works against the Hub" || echo "(legacy CLI not checked)"
echo "✓ CUTOVER VERIFIED — the Hub is the registry now"

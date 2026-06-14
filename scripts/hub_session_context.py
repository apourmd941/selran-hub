#!/usr/bin/env python3
"""SessionStart hook — inject a one-line Selran Hub status as session context.

Probes the local Hub (loopback) and, if it's running, tells Claude what services
exist and whether any are down — so the assistant starts the session already
aware of the user's local state. Stdlib only (no deps); works for plugin installs
without selran-hub on the path.

Probe discipline (Hub spec §4.2): if the Hub isn't running we print NOTHING and
exit 0 — never nag the user about an absent optional component.
"""

import json
import os
import sys
import urllib.request
from collections import Counter

PORT = os.environ.get("SELRAN_HUB_PORT", "11999")
BASE = f"http://127.0.0.1:{PORT}"


def _get(path, timeout=0.4):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def build_context(health, services):
    """Pure: (health dict, services dict) -> context string, or None to stay
    silent. Kept side-effect-free so it is unit-testable."""
    if not health or health.get("hub") != "selran":
        return None
    svcs = (services or {}).get("services", [])
    if not svcs:
        return (
            f"Selran Hub is running locally on :{PORT} (no services registered yet). "
            "You can query the user's connected data sources through the Hub's MCP tools."
        )
    counts = Counter(s.get("state") for s in svcs)
    failed = [s.get("name") or s.get("id") for s in svcs if s.get("state") == "failed"]
    parts = [f"{counts.get('running', 0)} running"]
    if counts.get("stopped"):
        parts.append(f"{counts['stopped']} stopped")
    if counts.get("failed"):
        parts.append(f"{counts['failed']} failed")
    msg = f"Selran Hub is running locally on :{PORT}. Services: {len(svcs)} ({', '.join(parts)})."
    if failed:
        msg += (
            f" Down: {', '.join(failed)} — the recorded process is gone. You can inspect"
            " its leftover PIDs or restart it through the Hub."
        )
    return msg


def main():
    try:
        sys.stdin.read()
    except Exception:
        pass
    try:
        health = _get("/hub/health", timeout=0.25)
    except Exception:
        return  # Hub not running → stay silent
    try:
        services = _get("/v1/services", timeout=0.8)
    except Exception:
        services = {}
    ctx = build_context(health, services)
    # H6: append an update notice IF the Hub (opt-in) reports one. The Hub does
    # the GitHub check; the hook just relays it, so it stays self-contained.
    try:
        upd = _get("/v1/update", timeout=0.8)
        if upd.get("update_available") and upd.get("latest_tag"):
            ctx = (ctx or "") + f" A newer Selran Hub is available ({upd['latest_tag']}; you have {upd.get('current')})."
    except Exception:
        pass
    if ctx:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": ctx,
            }
        }))


if __name__ == "__main__":
    main()

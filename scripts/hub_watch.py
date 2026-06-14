#!/usr/bin/env python3
"""Background monitor — watches the local Selran Hub and emits a line (delivered
to Claude as a between-turns notification) when something noteworthy happens:

  * a registered service goes DOWN (transitions to "failed" — its process is
    gone without the Hub having stopped it: a crash);
  * the Hub itself becomes unreachable, or comes back.

Low-noise by construction: it establishes a SILENT baseline on the first poll
and only speaks on state TRANSITIONS — never a line per poll, never "all good".
Stdlib only; resilient to the Hub being absent (waits quietly and retries).

Claude Code runs this for the lifetime of the session (monitors/monitors.json).
"""

import json
import os
import sys
import time
import urllib.request

PORT = os.environ.get("SELRAN_HUB_PORT", "11999")
BASE = f"http://127.0.0.1:{PORT}"
INTERVAL = float(os.environ.get("SELRAN_HUB_WATCH_INTERVAL", "6"))


def _get(path, timeout=0.8):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def diff_events(prev, new, prev_reach, new_reach):
    """Pure transition logic → list of notification lines.

    prev/new map service_id -> {"state":..., "name":...}. `prev is None` means
    "first poll" → baseline, emit nothing. Side-effect-free for unit testing.
    """
    events = []
    if prev is None:
        return events  # silent baseline
    if prev_reach and not new_reach:
        return [f"Selran Hub became unreachable on :{PORT}."]
    if not prev_reach and new_reach:
        events.append(f"Selran Hub is reachable again on :{PORT}.")
    for sid, info in new.items():
        was = (prev.get(sid) or {}).get("state")
        now = info.get("state")
        name = info.get("name") or sid
        if now == "failed" and was != "failed":
            events.append(
                f"⚠ Selran service '{name}' is down — its process is gone (state: failed)."
            )
    return events


def snapshot():
    """(reachable, {service_id: {state, name}}). Never raises."""
    try:
        health = _get("/hub/health", timeout=0.5)
    except Exception:
        return False, {}
    if not (health and health.get("hub") == "selran"):
        return False, {}
    state = {}
    try:
        for s in _get("/v1/services").get("services", []):
            state[s["id"]] = {"state": s.get("state"), "name": s.get("name")}
    except Exception:
        pass
    return True, state


def main():
    prev_state = None
    prev_reach = True
    while True:
        reachable, state = snapshot()
        for line in diff_events(prev_state, state, prev_reach, reachable):
            print(line, flush=True)
        # Keep the pre-outage snapshot while unreachable so we can diff on return;
        # establish a non-None baseline even if we started while the Hub was down.
        if reachable:
            prev_state = state
        elif prev_state is None:
            prev_state = {}
        prev_reach = reachable
        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

"""Update checker (H6) — notify the user when a newer Hub release is published.

Local-first by design:
  * This is the ONLY outbound call the Hub makes. It sends NOTHING about the
    user — a plain GET of the public GitHub "latest release" for the repo.
  * The AUTOMATIC surface (the /v1/update endpoint the dashboard / SessionStart
    hook read) is OPT-IN: it does nothing unless SELRAN_HUB_UPDATE_CHECK is
    truthy. The explicit `selran-hub update-check` CLI is a user action and
    always runs.
  * The result is cached for a week, so we never hit the network more than once
    per ~7 days even with the automatic surface on.

Version comparison is tuple-of-ints (never string compare — "0.10.0" < "0.3.0"
lexicographically), parsing both "hub-v0.11.0" tags and bare "0.11.0".
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from typing import Any, Optional

from .config import VERSION, get_data_dir

REPO = os.environ.get("SELRAN_HUB_UPDATE_REPO", "apourmd941/selran-hub")
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
TTL_SECONDS = 7 * 24 * 3600


def _cache_file():
    return get_data_dir() / "update-check.json"


def parse_version(s: str) -> Optional[tuple[int, ...]]:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", s or "")
    return tuple(int(x) for x in m.groups()) if m else None


def auto_enabled() -> bool:
    """Whether the automatic/background update surface is opted in. A managed
    policy (H9) can force it off (no outbound calls in locked-down fleets)."""
    try:
        from . import policy
        if policy.update_check_disabled():
            return False
    except Exception:
        pass
    return os.environ.get("SELRAN_HUB_UPDATE_CHECK", "").strip().lower() in ("1", "true", "yes", "on")


def fetch_latest(timeout: float = 2.5) -> dict[str, Any]:
    req = urllib.request.Request(
        LATEST_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "selran-hub"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read() or b"{}")
    tag = d.get("tag_name") or ""
    return {"tag": tag, "version": parse_version(tag), "html_url": d.get("html_url"), "name": d.get("name")}


def _read_cache() -> dict:
    try:
        return json.loads(_cache_file().read_text())
    except Exception:
        return {}


def _write_cache(d: dict) -> None:
    try:
        p = _cache_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, indent=2))
    except Exception:
        pass


def check(force: bool = False, now: Optional[float] = None) -> dict[str, Any]:
    """Return {current, latest_tag, latest_version, update_available, html_url}.
    Uses the weekly cache unless force=True; on a network failure, falls back to
    the last cached result (and reports an error if there is none)."""
    try:  # H9: a managed policy can forbid update checks entirely (no egress),
        from . import policy  # including the explicit CLI — not just the auto surface.
        if policy.update_check_disabled():
            return {"current": VERSION, "update_available": False, "disabled_by_policy": True}
    except Exception:
        pass
    now = time.time() if now is None else now
    cache = _read_cache()
    fresh = (not force) and cache.get("checked_at") and (now - cache["checked_at"] < TTL_SECONDS)
    latest = cache.get("latest")
    if not fresh:
        try:
            latest = fetch_latest()
            _write_cache({"checked_at": now, "latest": latest})
        except Exception as exc:
            if not latest:
                return {"current": VERSION, "update_available": False, "error": str(exc)}
    cur = parse_version(VERSION)
    lat = (latest or {}).get("version")
    available = bool(cur and lat and tuple(lat) > tuple(cur))
    return {
        "current": VERSION,
        "latest_tag": (latest or {}).get("tag"),
        "latest_version": list(lat) if lat else None,
        "update_available": available,
        "html_url": (latest or {}).get("html_url"),
    }


def status_for_endpoint() -> dict[str, Any]:
    """What the /v1/update route returns — does nothing (no network) unless the
    automatic check is opted in."""
    if not auto_enabled():
        return {"enabled": False, "update_available": False, "current": VERSION}
    out = check()
    out["enabled"] = True
    return out

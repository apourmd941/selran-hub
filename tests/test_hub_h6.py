"""H6 tests — update checker.

Network is monkeypatched (no real GitHub call), the cache is isolated under a
temp HOME, and env is restored on teardown. A separate live smoke (run manually)
hits the real releases endpoint.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

_ORIG = {k: os.environ.get(k) for k in ("HOME", "XDG_CONFIG_HOME", "SELRAN_HUB_UPDATE_CHECK")}
_HOME = tempfile.mkdtemp(prefix="hub_h6_")
os.environ["HOME"] = _HOME
os.environ["XDG_CONFIG_HOME"] = str(Path(_HOME) / ".config")
os.environ.pop("SELRAN_HUB_UPDATE_CHECK", None)

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from selran_hub import updater  # noqa: E402


@pytest.fixture(autouse=True, scope="module")
def _restore_env():
    yield
    for k, v in _ORIG.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(autouse=True)
def _clear_cache():
    f = updater._cache_file()
    if f.exists():
        f.unlink()
    yield


def _fake_latest(version_tuple, tag=None):
    return lambda timeout=2.5: {"tag": tag or "hub-v%d.%d.%d" % version_tuple,
                                "version": version_tuple, "html_url": "https://example/r", "name": "x"}


# ----------------------------------------------------------- version parsing

def test_parse_version_handles_tag_and_bare():
    assert updater.parse_version("hub-v0.7.3") == (0, 7, 3)
    assert updater.parse_version("v1.2.10") == (1, 2, 10)
    assert updater.parse_version("0.11.0") == (0, 11, 0)
    assert updater.parse_version("not-a-version") is None


def test_compare_is_semver_not_lexicographic(monkeypatch):
    # current VERSION is 0.12.x; a 0.3.0 release must NOT read as newer even
    # though "0.3.0" > "0.12.0" as strings.
    monkeypatch.setattr(updater, "fetch_latest", _fake_latest((0, 3, 0)))
    assert updater.check(force=True)["update_available"] is False
    monkeypatch.setattr(updater, "fetch_latest", _fake_latest((9, 0, 0)))
    r = updater.check(force=True)
    assert r["update_available"] is True and r["latest_tag"] == "hub-v9.0.0"


# ----------------------------------------------------------- caching

def test_check_caches_weekly(monkeypatch):
    calls = {"n": 0}

    def counting(timeout=2.5):
        calls["n"] += 1
        return {"tag": "hub-v9.9.9", "version": (9, 9, 9), "html_url": "u", "name": "n"}

    monkeypatch.setattr(updater, "fetch_latest", counting)
    updater.check()           # fetches
    updater.check()           # cached → no new fetch
    assert calls["n"] == 1
    updater.check(force=True)  # forced → fetch again
    assert calls["n"] == 2


def test_network_failure_falls_back_to_no_update(monkeypatch):
    def boom(timeout=2.5):
        raise OSError("no network")
    monkeypatch.setattr(updater, "fetch_latest", boom)
    r = updater.check(force=True)
    assert r["update_available"] is False and "error" in r


# ----------------------------------------------------------- opt-in endpoint surface

def test_endpoint_status_is_opt_in(monkeypatch):
    # Should NOT touch the network when not opted in.
    def boom(timeout=2.5):
        raise AssertionError("network hit while opt-in disabled")
    monkeypatch.setattr(updater, "fetch_latest", boom)
    os.environ.pop("SELRAN_HUB_UPDATE_CHECK", None)
    s = updater.status_for_endpoint()
    assert s == {"enabled": False, "update_available": False, "current": updater.VERSION}
    # opted in → performs the check
    monkeypatch.setattr(updater, "fetch_latest", _fake_latest((9, 9, 9)))
    os.environ["SELRAN_HUB_UPDATE_CHECK"] = "1"
    s2 = updater.status_for_endpoint()
    assert s2["enabled"] is True and s2["update_available"] is True
    os.environ.pop("SELRAN_HUB_UPDATE_CHECK", None)


def test_update_route_default_off(monkeypatch):
    # The /v1/update route returns enabled:False by default (no network).
    # (It only calls updater.status_for_endpoint() — no registry/services, so we
    # don't touch SELRAN_HUB_REGISTRY_DB and can't contaminate other modules.)
    from fastapi.testclient import TestClient
    from selran_hub.app import app
    monkeypatch.setattr(updater, "fetch_latest", lambda timeout=2.5: (_ for _ in ()).throw(AssertionError("net")))
    c = TestClient(app, headers={"X-Selran-Local": "1"})
    body = c.get("/v1/update").json()
    assert body["enabled"] is False and body["update_available"] is False

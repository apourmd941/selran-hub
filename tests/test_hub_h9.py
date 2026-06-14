"""H9 tests — managed policy / MDM layer + enforcement.

A temp policy file (via SELRAN_HUB_POLICY_FILE) under a temp HOME; the policy is
read per-call (uncached), so each test writes/clears the file and the enforcement
points pick it up. Env is restored on teardown so other modules aren't affected.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

# NOTE: deliberately do NOT touch SELRAN_HUB_REGISTRY_DB — these tests don't use
# the registry, and restoring it on teardown would clobber a later module's
# value (the cross-module env-leak that broke earlier phases).
_ORIG = {k: os.environ.get(k) for k in
         ("HOME", "XDG_CONFIG_HOME", "SELRAN_HUB_POLICY_FILE",
          "SELRAN_HUB_SECRETS_BACKEND", "SELRAN_HUB_UPDATE_CHECK")}
_HOME = tempfile.mkdtemp(prefix="hub_h9_")
os.environ["HOME"] = _HOME
os.environ["XDG_CONFIG_HOME"] = str(Path(_HOME) / ".config")
_POLICY = Path(_HOME) / "managed-policy.json"
os.environ["SELRAN_HUB_POLICY_FILE"] = str(_POLICY)
os.environ["SELRAN_HUB_SECRETS_BACKEND"] = "file"

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from selran_hub import policy, updater, mcp_bridge as br  # noqa: E402


def _set(d):
    _POLICY.write_text(json.dumps(d))


def _clear():
    if _POLICY.exists():
        _POLICY.unlink()


@pytest.fixture(autouse=True)
def _reset_policy():
    _clear()
    yield
    _clear()


@pytest.fixture(autouse=True, scope="module")
def _restore_env():
    yield
    for k, v in _ORIG.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ----------------------------------------------------------- policy module

def test_unmanaged_by_default():
    assert policy.is_managed() is False
    eff = policy.effective()
    assert eff["managed"] is False
    assert eff["allow_remote_transport"] is True       # permissive defaults
    assert eff["allowed_source_types"] is None
    assert eff["require_auth"] is False


def test_accessors_reflect_the_file():
    _set({"allow_remote_transport": False, "allowed_source_types": ["folder", "SQLite"],
          "require_auth": True, "disable_update_check": True})
    assert policy.is_managed() is True
    assert policy.allow_remote_transport() is False
    assert policy.allowed_source_types() == {"folder", "sqlite"}   # normalized lower
    assert policy.require_auth() is True
    assert policy.update_check_disabled() is True


# ----------------------------------------------------------- enforcement: bridge

def test_policy_forbids_remote_transport_even_with_token():
    _set({"allow_remote_transport": False})
    with pytest.raises(ValueError):
        br.resolve_http_security("0.0.0.0", "a-token")   # refused despite a token
    # loopback still fine
    assert br.resolve_http_security("127.0.0.1", "") is False


def test_default_allows_remote_with_token():
    assert br.resolve_http_security("0.0.0.0", "tok") is True   # no policy → token rules apply


# ----------------------------------------------------------- enforcement: updater

def test_policy_disables_update_check_over_env_optin():
    os.environ["SELRAN_HUB_UPDATE_CHECK"] = "1"
    try:
        _set({"disable_update_check": True})
        assert updater.auto_enabled() is False            # policy wins over the env opt-in
        _clear()
        assert updater.auto_enabled() is True             # env opt-in honored again
    finally:
        os.environ.pop("SELRAN_HUB_UPDATE_CHECK", None)


# ----------------------------------------------------------- enforcement: HTTP API

def _client():
    from fastapi.testclient import TestClient
    from selran_hub.app import app
    return TestClient(app, headers={"X-Selran-Local": "1"})


def test_allowed_source_types_blocks_disallowed():
    _set({"allowed_source_types": ["folder"]})
    c = _client()
    folder = Path(_HOME) / "f"; folder.mkdir(exist_ok=True)
    r = c.post("/api/sources", json={"name": "api-src", "type": "api", "url": "http://127.0.0.1:9", "rules": {}})
    assert r.status_code == 403 and "not allowed by org policy" in r.text


def test_require_auth_locks_api_when_no_key():
    _set({"require_auth": True})
    c = _client()
    r = c.get("/api/sources")
    assert r.status_code == 503 and "requires API authentication" in r.text
    _clear()
    assert c.get("/api/sources").status_code == 200       # unlocked again


def test_import_respects_allowed_source_types():
    # The restriction must hold on the bulk-import path too, not just create().
    from selran_hub.source_manager import SourceManager
    _set({"allowed_source_types": ["folder"]})
    folder = Path(_HOME) / "imp"; folder.mkdir(exist_ok=True)
    mgr = SourceManager(Path(_HOME) / "imp-sources.json")
    res = mgr.import_config([
        {"name": "ok", "type": "folder", "path": str(folder)},
        {"name": "bad", "type": "api", "url": "http://127.0.0.1:9"},
    ])
    assert res["imported"] == 1
    assert any("not allowed by org policy" in e for e in res["errors"])
    assert "bad" not in {s["name"] for s in mgr._sources.values()}


def test_explicit_update_check_blocked_by_policy(monkeypatch):
    # disable_update_check must stop the EXPLICIT CLI path too (no egress) — not
    # just the auto surface. fetch_latest must never be called.
    _set({"disable_update_check": True})
    monkeypatch.setattr(updater, "fetch_latest",
                        lambda timeout=2.5: (_ for _ in ()).throw(AssertionError("network")))
    r = updater.check(force=True)
    assert r.get("disabled_by_policy") is True and r["update_available"] is False


def test_policy_endpoint_reports_effective():
    _set({"allow_remote_transport": False, "note": "locked"})
    c = _client()
    body = c.get("/v1/policy").json()
    assert body["managed"] is True and body["allow_remote_transport"] is False
    assert body["note"] == "locked"

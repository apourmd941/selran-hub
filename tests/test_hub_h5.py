"""H5 tests — OS-keychain secret storage.

Run against the FILE backend (SELRAN_HUB_SECRETS_BACKEND=file) under a temp HOME,
so they're deterministic and never touch the real OS keychain or data dir. The
file backend exercises the same set/get/delete + migration + stripping paths the
keychain backend uses; the keychain path itself can't be asserted portably in CI.
"""

import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

# Redirect the data dir to a temp HOME and force the file fallback BEFORE import.
# Save originals so we can fully un-contaminate the process for later test
# modules (this module shares the app's config singleton).
_ORIG_ENV = {k: os.environ.get(k) for k in ("HOME", "XDG_CONFIG_HOME", "SELRAN_HUB_SECRETS_BACKEND", "HUB_DATABASE_URL")}
_HOME = tempfile.mkdtemp(prefix="hub_h5_")
os.environ["HOME"] = _HOME
os.environ["XDG_CONFIG_HOME"] = str(Path(_HOME) / ".config")
os.environ["SELRAN_HUB_SECRETS_BACKEND"] = "file"
os.environ.pop("HUB_DATABASE_URL", None)  # ensure file path, not Postgres

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from selran_hub import secrets_store, config  # noqa: E402
from selran_hub.source_manager import SourceManager, _secret_key  # noqa: E402


@pytest.fixture(autouse=True, scope="module")
def _restore_global_state():
    """These tests enable API-key auth and redirect HOME on the shared config
    singleton. Disable auth and restore env afterwards so later test modules
    (which use the same app) aren't left behind an auth gate."""
    yield
    try:
        config.set_api_key(False)
    except Exception:
        pass
    for k, v in _ORIG_ENV.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


# ------------------------------------------------------------- secrets_store

def test_backend_is_file_and_roundtrips():
    assert secrets_store.backend() == "file"
    secrets_store.set_secret("k1", "v1")
    assert secrets_store.get_secret("k1") == "v1"
    secrets_store.set_json("k2", {"a": 1})
    assert secrets_store.get_json("k2") == {"a": 1}
    secrets_store.delete_secret("k1")
    assert secrets_store.get_secret("k1") is None


def test_fallback_file_is_0600():
    secrets_store.set_secret("perm", "x")
    p = secrets_store._fallback_file()
    assert p.exists() and _mode(p) == 0o600


# ------------------------------------------------------------- auth token

def test_api_key_not_written_in_plaintext():
    key = config.set_api_key(True)
    assert key and config.get_api_key() == key
    # auth.json holds only the enabled flag — never the key
    rec = json.loads(config.get_auth_file().read_text())
    assert rec == {"enabled": True}
    assert key not in config.get_auth_file().read_text()
    assert _mode(config.get_auth_file()) == 0o600
    # the secret itself is in the store
    assert secrets_store.get_secret("api-key") == key
    # disabling removes it everywhere
    config.set_api_key(False)
    assert config.get_api_key() is None
    assert secrets_store.get_secret("api-key") is None


def test_legacy_plaintext_key_is_migrated_and_scrubbed():
    secrets_store.delete_secret("api-key")
    # simulate an old auth.json that still has the key inline
    config.get_auth_file().write_text(json.dumps({"enabled": True, "api_key": "legacy-XYZ"}))
    assert config.get_api_key() == "legacy-XYZ"           # read works
    scrubbed = json.loads(config.get_auth_file().read_text())
    assert "api_key" not in scrubbed                       # plaintext scrubbed from disk
    assert secrets_store.get_secret("api-key") == "legacy-XYZ"  # moved to the store


# ------------------------------------------------------------- source headers

def _api_body(rules):
    return SimpleNamespace(name="MyAPI", type="api", path=None,
                           url="http://127.0.0.1:9", description="", rules=rules,
                           enabled=True)


def _rules_with_token(tok="Bearer sk-secret"):
    return {"read_only": True, "endpoints": [
        {"name": "users", "path": "/users", "method": "GET",
         "headers": {"Authorization": tok}},
    ]}


def test_source_headers_go_to_keychain_not_disk():
    mgr = SourceManager(Path(_HOME) / "sources.json")
    src = mgr.create(_api_body(_rules_with_token()))
    sid = src["id"]
    # the persisted file must NOT contain the token
    on_disk = (Path(_HOME) / "sources.json").read_text()
    assert "sk-secret" not in on_disk
    assert _mode(Path(_HOME) / "sources.json") == 0o600
    # the in-memory source + API response are stripped too
    assert mgr._sources[sid]["rules"]["endpoints"][0]["headers"] == {}
    assert "sk-secret" not in json.dumps(src)
    # but the secret is in the store, and gets injected for the connector
    assert secrets_store.get_json(_secret_key(sid))["users"]["Authorization"] == "Bearer sk-secret"
    injected = mgr._inject_secrets(mgr._sources[sid])
    assert injected["rules"]["endpoints"][0]["headers"]["Authorization"] == "Bearer sk-secret"


def test_export_does_not_leak_secrets():
    mgr = SourceManager(Path(_HOME) / "sources2.json")
    mgr.create(_api_body(_rules_with_token("Bearer top-secret")))
    assert "top-secret" not in json.dumps(mgr.export_config())


def test_update_without_resending_token_preserves_it():
    mgr = SourceManager(Path(_HOME) / "sources3.json")
    src = mgr.create(_api_body(_rules_with_token("Bearer keep-me")))
    sid = src["id"]
    # update rules WITHOUT headers (e.g. user edits the row, doesn't re-enter token)
    mgr.update(sid, SimpleNamespace(name=None, description="edited", path=None, url=None,
                                    rules={"read_only": True, "endpoints": [
                                        {"name": "users", "path": "/users", "method": "GET"}]},
                                    enabled=None))
    injected = mgr._inject_secrets(mgr._sources[sid])
    assert injected["rules"]["endpoints"][0]["headers"]["Authorization"] == "Bearer keep-me"


def test_delete_removes_the_secret():
    mgr = SourceManager(Path(_HOME) / "sources4.json")
    src = mgr.create(_api_body(_rules_with_token("Bearer gone-soon")))
    sid = src["id"]
    assert secrets_store.get_json(_secret_key(sid)) is not None
    mgr.delete(sid)
    assert secrets_store.get_json(_secret_key(sid)) is None


def test_loose_sources_file_is_retightened_on_load():
    f = Path(_HOME) / "loose.json"
    f.write_text("[]")
    os.chmod(f, 0o644)  # simulate a legacy world-readable file
    assert _mode(f) == 0o644
    SourceManager(f)  # _load re-tightens regardless of a pending write
    assert _mode(f) == 0o600


def test_update_prunes_removed_endpoint_secret():
    mgr = SourceManager(Path(_HOME) / "prune.json")
    rules = {"endpoints": [
        {"name": "alpha", "path": "/a", "headers": {"Authorization": "Bearer A"}},
        {"name": "beta", "path": "/b", "headers": {"Authorization": "Bearer B"}},
    ]}
    src = mgr.create(SimpleNamespace(name="P", type="api", path=None,
                                     url="http://127.0.0.1:9", description="", rules=rules, enabled=True))
    sid = src["id"]
    assert set(secrets_store.get_json(_secret_key(sid))) == {"alpha", "beta"}
    # update keeping only alpha (no headers re-sent) → beta's secret is pruned
    mgr.update(sid, SimpleNamespace(name=None, description=None, path=None, url=None,
                                    rules={"endpoints": [{"name": "alpha", "path": "/a"}]}, enabled=None))
    keychain = secrets_store.get_json(_secret_key(sid))
    assert "alpha" in keychain and "beta" not in keychain          # pruned
    assert mgr._inject_secrets(mgr._sources[sid])["rules"]["endpoints"][0]["headers"]["Authorization"] == "Bearer A"


def test_unnamed_endpoints_do_not_collide():
    mgr = SourceManager(Path(_HOME) / "unnamed.json")
    rules = {"endpoints": [
        {"method": "GET", "headers": {"Authorization": "Bearer first"}},
        {"method": "GET", "headers": {"Authorization": "Bearer second"}},
    ]}
    src = mgr.create(SimpleNamespace(name="U", type="api", path=None,
                                     url="http://127.0.0.1:9", description="", rules=rules, enabled=True))
    injected = mgr._inject_secrets(mgr._sources[src["id"]])
    eps = injected["rules"]["endpoints"]
    assert eps[0]["headers"]["Authorization"] == "Bearer first"
    assert eps[1]["headers"]["Authorization"] == "Bearer second"  # distinct, no overwrite


def test_migration_survives_keychain_write_failure(monkeypatch):
    # A keychain that errors on write must NOT crash SourceManager construction.
    f = Path(_HOME) / "fail.json"
    f.write_text(json.dumps([{
        "id": "f1", "name": "F", "type": "api", "url": "http://127.0.0.1:9",
        "rules": {"endpoints": [{"name": "x", "headers": {"Authorization": "Bearer boom"}}]},
        "enabled": True,
    }]))
    monkeypatch.setattr(secrets_store, "set_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("keychain down")))
    mgr = SourceManager(f)  # must not raise
    # the inline secret is left in place (not lost) to retry later
    assert mgr._sources["f1"]["rules"]["endpoints"][0]["headers"]["Authorization"] == "Bearer boom"


def test_legacy_inline_source_headers_are_migrated_on_load():
    # write a sources file with an inline secret (legacy plaintext), then load it
    f = Path(_HOME) / "sources5.json"
    f.write_text(json.dumps([{
        "id": "leg123", "name": "Legacy", "type": "api", "url": "http://127.0.0.1:9",
        "rules": {"endpoints": [{"name": "x", "path": "/x", "headers": {"Authorization": "Bearer legacy-inline"}}]},
        "enabled": True,
    }]))
    mgr = SourceManager(f)  # _load → _migrate_inline_secrets runs
    assert "legacy-inline" not in f.read_text()  # scrubbed from disk
    assert secrets_store.get_json(_secret_key("leg123"))["x"]["Authorization"] == "Bearer legacy-inline"

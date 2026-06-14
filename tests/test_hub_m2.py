"""M2 acceptance tests — service lifecycle with verified process identity.

Real processes are launched (short-lived python sleepers), so every test
cleans up after itself; a session fixture sweeps anything left.
"""

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_tmpdir = tempfile.mkdtemp(prefix="hub_m2_")
os.environ["SELRAN_HUB_REGISTRY_DB"] = str(Path(_tmpdir) / "registry.sqlite3")

from fastapi.testclient import TestClient  # noqa: E402
from selran_hub.app import app  # noqa: E402
from selran_hub import hub_router  # noqa: E402

client = TestClient(app, headers={"X-Selran-Local": "1"})

SLEEPER = 'python3 -c "import time; time.sleep(120)"'


@pytest.fixture(autouse=True, scope="session")
def sweep():
    yield
    # stop anything still running at session end
    for s in client.get("/v1/services").json().get("services", []):
        if s["state"] == "running":
            client.post(f"/v1/services/{s['id']}/stop")


def register(sid: str, cmd: str = SLEEPER, **kw) -> dict:
    body = {"id": sid, "cwd": _tmpdir, "start_cmd": cmd, **kw}
    r = client.post("/v1/services", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------- registration

def test_register_and_list():
    out = register("m2-reg")
    assert out["state"] == "registered"
    assert out["pid"] is None
    listed = client.get("/v1/services").json()
    assert any(s["id"] == "m2-reg" for s in listed["services"])


def test_register_validation():
    r = client.post("/v1/services", json={"id": "bad id!", "cwd": _tmpdir, "start_cmd": "x"})
    assert r.status_code == 400
    r = client.post("/v1/services", json={"id": "m2-nocwd", "cwd": "/does/not/exist", "start_cmd": "x"})
    assert r.status_code == 400
    r = client.post("/v1/services", json={"id": "m2-nocmd", "cwd": _tmpdir, "start_cmd": ""})
    assert r.status_code == 400


# ------------------------------------------------------------- lifecycle

def test_start_run_stop_cycle():
    register("m2-cycle")
    started = client.post("/v1/services/m2-cycle/start").json()
    assert started["state"] == "running", started
    assert isinstance(started["pid"], int)

    # double-start refused
    again = client.post("/v1/services/m2-cycle/start")
    assert again.status_code == 400

    stopped = client.post("/v1/services/m2-cycle/stop").json()
    assert stopped["state"] == "stopped"
    assert stopped["pid"] is None

    # stop is idempotent
    stopped2 = client.post("/v1/services/m2-cycle/stop").json()
    assert stopped2["state"] == "stopped"


def test_restart_changes_pid():
    register("m2-restart")
    p1 = client.post("/v1/services/m2-restart/start").json()["pid"]
    p2 = client.post("/v1/services/m2-restart/restart").json()["pid"]
    assert p1 != p2
    client.post("/v1/services/m2-restart/stop")


def test_failed_detection():
    # a service that exits on its own = failed (we started it, we didn't stop it)
    register("m2-flaky", cmd='python3 -c "import time; time.sleep(0.3)"')
    client.post("/v1/services/m2-flaky/start")
    time.sleep(1.2)
    d = client.get("/v1/services/m2-flaky").json()
    assert d["state"] == "failed", d


def test_unregister_requires_stopped():
    register("m2-unreg")
    client.post("/v1/services/m2-unreg/start")
    r = client.delete("/v1/services/m2-unreg")
    assert r.status_code == 400  # running → refused
    client.post("/v1/services/m2-unreg/stop")
    r2 = client.delete("/v1/services/m2-unreg")
    assert r2.status_code == 200
    assert client.get("/v1/services/m2-unreg").status_code == 400  # unknown now


# ------------------------------------------------------------- identity safety

def test_pid_reuse_is_never_killed():
    register("m2-reuse")
    started = client.post("/v1/services/m2-reuse/start").json()
    pid = started["pid"]
    # simulate PID reuse: corrupt the recorded identity so the live process
    # no longer matches what the hub thinks it launched (separate connection —
    # the manager's own connection lives on the app's event-loop thread)
    import sqlite3
    conn = sqlite3.connect(os.environ["SELRAN_HUB_REGISTRY_DB"], isolation_level=None)
    conn.execute(
        "UPDATE hub_service_runtime SET command_line = 'totally-different-cmd' WHERE service_id = 'm2-reuse'"
    )
    conn.close()
    r = client.post("/v1/services/m2-reuse/stop")
    assert r.status_code == 400
    assert "refusing to kill" in r.json()["message"]
    # the real process must still be alive — the hub refused to signal it
    os.kill(pid, 0)  # raises if dead
    os.kill(pid, 15)  # actual cleanup, outside the hub


# ------------------------------------------------------------- hub integration

def test_hub_health_includes_services():
    register("m2-health")
    h = client.get("/hub/health").json()
    assert tuple(int(p) for p in h["version"].split(".")) >= (0, 2, 0)  # services shipped in 0.2.0
    assert "services" in h["capabilities"]
    assert any(s["id"] == "m2-health" for s in h["services"])


def test_registry_link_and_health_probe():
    # allocate ports via the registry, link the service, serve real HTTP health
    rng = client.post("/v1/ensure", json={"app_id": "m2-linked", "path": _tmpdir}).json()["range"]
    port = rng[0]
    register(
        "m2-linked-svc",
        cmd=f'python3 -m http.server {port} --bind 127.0.0.1',
        registry_app_id="m2-linked",
        health_url=f"http://127.0.0.1:{port}/",
    )
    started = client.post("/v1/services/m2-linked-svc/start").json()
    assert started["state"] == "running"
    time.sleep(0.8)
    d = client.get("/v1/services/m2-linked-svc").json()
    assert d["registry_app_id"] == "m2-linked"
    assert d["health"] == "ok", d
    client.post("/v1/services/m2-linked-svc/stop")


def test_panel_serves():
    r = client.get("/hub/panel")
    assert r.status_code == 200
    assert "Selran Hub — Services" in r.text


def test_health_probe_rejects_non_http_schemes(monkeypatch):
    """A registered health_url must never make the Hub open file:// (or any
    non-http scheme) during a health probe (audit hardening)."""
    import urllib.request
    from selran_hub.service_manager import ServiceManager

    def boom(*a, **k):
        raise AssertionError("urlopen must not be called for a non-http scheme")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert ServiceManager._probe_health("file:///etc/passwd") == "unreachable"
    assert ServiceManager._probe_health("gopher://x/y") == "unreachable"
    assert ServiceManager._probe_health("") == "unreachable"

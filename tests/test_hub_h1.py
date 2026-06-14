"""H1 acceptance tests — orphan-PID reaper.

Exercises the safety guardrails the design's adversarial review demanded:
  * marker-verified processes are OWNED and stoppable;
  * an owner==me process on the app's ports is owned-unverified and needs force;
  * a foreign-owner / Hub-self / no-create_time process is NEVER stoppable;
  * the stop path refuses on an identity (create_time / command) mismatch — the
    PID-reuse guard;
  * "free" is distinguished from "blind" (occupied-but-not-visible) so the UI
    never shows a false all-clear;
  * startup reconcile marks a dead-but-recorded row stopped without signalling.

Real processes are launched, so every test cleans up after itself.
"""

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_tmpdir = tempfile.mkdtemp(prefix="hub_h0_")
os.environ["SELRAN_HUB_REGISTRY_DB"] = str(Path(_tmpdir) / "registry.sqlite3")

from fastapi.testclient import TestClient  # noqa: E402
from selran_hub.app import app  # noqa: E402
from selran_hub import hub_router, process_inspect as pi  # noqa: E402
from selran_hub.service_manager import ServiceManager  # noqa: E402

# Fresh singletons against our temp DB (other test files may have built them).
hub_router._services = None
hub_router._store = None

client = TestClient(app, headers={"X-Selran-Local": "1"})

SLEEPER = 'python3 -c "import time; time.sleep(120)"'
ME = pi.current_user()
_spawned: list[int] = []


@pytest.fixture(autouse=True, scope="session")
def sweep():
    yield
    for s in client.get("/v1/services").json().get("services", []):
        if s["state"] == "running":
            client.post(f"/v1/services/{s['id']}/stop")
    for pid in _spawned:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(pid, sig)
            except Exception:
                pass


def _register(sid, cmd=SLEEPER, **kw):
    r = client.post("/v1/services", json={"id": sid, "cwd": _tmpdir, "start_cmd": cmd, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _start(sid):
    r = client.post(f"/v1/services/{sid}/start").json()
    assert r["state"] == "running", r
    _spawned.append(r["pid"])
    return r


# ----------------------------------------------------------- classification (unit)

def _mgr():
    return hub_router.get_services()


def test_classify_foreign_owner_never_stoppable():
    info = {"command": "x", "owner": "__not_me__", "create_time": 123.0, "marker": None, "access_denied": False}
    r = _mgr()._classify_pid(98765432, info, [12001], {}, set(), set(), {"svc"}, set(), ME)
    assert r["classification"] == "foreign" and r["offer_stop"] is False


def test_classify_hub_self_never_stoppable():
    info = {"command": "python", "owner": ME, "create_time": 123.0, "marker": None, "access_denied": False}
    r = _mgr()._classify_pid(os.getpid(), info, [], {}, set(), set(), {"svc"}, {os.getpid()}, ME)
    assert r["classification"] == "foreign" and r["role"] == "self" and r["offer_stop"] is False


def test_classify_no_create_time_is_ambiguous_not_stoppable():
    info = {"command": "x", "owner": ME, "create_time": None, "marker": None, "access_denied": False}
    r = _mgr()._classify_pid(98765433, info, [12002], {}, set(), set(), {"svc"}, set(), ME)
    assert r["classification"] == "ambiguous" and r["offer_stop"] is False


def test_classify_marker_is_owned():
    info = {"command": "x", "owner": ME, "create_time": 123.0, "marker": "svc:abcdef", "access_denied": False}
    r = _mgr()._classify_pid(98765434, info, [], {}, set(), set(), {"svc"}, set(), ME)
    assert r["classification"] == "owned" and r["offer_stop"] is True


def test_classify_owner_on_port_is_owned_unverified():
    info = {"command": "x", "owner": ME, "create_time": 123.0, "marker": None, "access_denied": False}
    r = _mgr()._classify_pid(98765435, info, [12003], {}, set(), set(), {"svc"}, set(), ME)
    assert r["classification"] == "owned-unverified" and r["offer_stop"] is True and r["stop_mode"] == "single"


# ----------------------------------------------------------- free vs blind

def test_port_free_vs_blind_coverage():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))  # bound but NOT listening: lsof -sTCP:LISTEN can't see it
    port = s.getsockname()[1]
    try:
        assert pi.port_is_occupied(port) is True
        _pmap, invisible, coverage = pi.listeners_with_coverage([port])
        assert port in invisible and coverage == "partial"  # occupied but not attributable
    finally:
        s.close()
    # now genuinely free
    time.sleep(0.1)
    _pmap2, invisible2, coverage2 = pi.listeners_with_coverage([port])
    assert not invisible2 and coverage2 == "complete"


# ----------------------------------------------------------- scan + safe stop

def test_owned_pid_is_listed_and_stoppable():
    _register("h0-stop")
    st = _start("h0-stop")
    pid = st["pid"]
    scan = client.get("/v1/services/h0-stop/pids").json()
    assert scan["status"] == "ok"
    mine = [p for p in scan["pids"] if p["pid"] == pid]
    assert mine, scan
    assert mine[0]["classification"] == "owned" and mine[0]["offer_stop"] is True
    r = client.post(
        f"/v1/services/h0-stop/pids/{pid}/stop",
        json={"command": mine[0]["command"], "create_time": mine[0]["create_time"]},
    )
    assert r.json()["status"] == "ok", r.text
    time.sleep(0.5)
    assert not pi.pid_exists(pid)


def test_stop_refuses_identity_mismatch():
    _register("h0-mis")
    st = _start("h0-mis")
    pid = st["pid"]
    scan = client.get("/v1/services/h0-mis/pids").json()
    row = next(p for p in scan["pids"] if p["pid"] == pid)
    # wrong create_time => possible PID reuse => refuse
    r = client.post(
        f"/v1/services/h0-mis/pids/{pid}/stop",
        json={"command": row["command"], "create_time": (row["create_time"] or 0) + 5000.0},
    )
    assert r.status_code == 400 and "start time changed" in r.json()["message"]
    # the process must still be alive (we refused to signal)
    assert pi.pid_exists(pid)
    client.post(f"/v1/services/h0-mis/pids/{pid}/stop",
                json={"command": row["command"], "create_time": row["create_time"]})


def test_stop_refuses_hub_self():
    _register("h0-self")
    r = client.post(f"/v1/services/h0-self/pids/{os.getpid()}/stop", json={})
    assert r.status_code == 400
    msg = r.json()["message"].lower()
    assert "hub itself" in msg or "ancestor" in msg or "system" in msg


def test_unverified_pid_requires_force_and_single_signal():
    app_obj = client.post("/v1/ensure", json={"app_id": "h0unv", "path": _tmpdir}).json()
    port = app_obj["range"][0]
    proc = subprocess.Popen([
        sys.executable, "-c",
        f'import socket,time; s=socket.socket(); s.bind(("127.0.0.1",{port})); s.listen(5); time.sleep(120)',
    ])
    _spawned.append(proc.pid)
    time.sleep(0.7)
    _register("h0unv-svc", cmd="placeholder-not-started", registry_app_id="h0unv")
    scan = client.get("/v1/services/h0unv-svc/pids").json()
    row = next((p for p in scan["pids"] if p["pid"] == proc.pid), None)
    assert row is not None, scan
    assert row["classification"] == "owned-unverified" and row["offer_stop"] is True
    # without force => refused
    r = client.post(
        f"/v1/services/h0unv-svc/pids/{proc.pid}/stop",
        json={"command": row["command"], "create_time": row["create_time"]},
    )
    assert r.status_code == 400 and "force" in r.json()["message"].lower()
    # with force => stopped (single-PID signal, owner==me)
    r2 = client.post(
        f"/v1/services/h0unv-svc/pids/{proc.pid}/stop",
        json={"command": row["command"], "create_time": row["create_time"], "force": True},
    )
    assert r2.json()["status"] == "ok", r2.text
    time.sleep(0.5)
    assert not pi.pid_exists(proc.pid)


# ----------------------------------------------------------- reconcile

def test_reconcile_marks_dead_row_stopped_without_signalling():
    _register("h0-recon")
    st = _start("h0-recon")
    pid = st["pid"]
    # simulate a crash: kill the process group out from under the Hub
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        os.kill(pid, signal.SIGKILL)
    time.sleep(0.4)
    # a fresh manager on the same DB runs reconcile_on_startup() in __init__
    fresh = ServiceManager(Path(os.environ["SELRAN_HUB_REGISTRY_DB"]))
    assert fresh.describe("h0-recon")["state"] == "stopped"

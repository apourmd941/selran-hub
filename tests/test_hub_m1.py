"""M1 acceptance tests — Hub identity + absorbed registry surface.

In-process via TestClient (no bound ports, no leaked processes). Covers:
  - /hub/health detection contract (spec §4.1)
  - registry compatibility surface parity (spec §3.2), including the
    historical 400-on-unknown-app quirk
  - the chassis (/api/health) staying intact
  - the frontend catch-all not shadowing or swallowing API namespaces
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Point the registry at a throwaway DB BEFORE the app/store import chain runs.
_tmpdir = tempfile.mkdtemp(prefix="hub_m1_")
os.environ["SELRAN_HUB_REGISTRY_DB"] = str(Path(_tmpdir) / "registry.sqlite3")

from fastapi.testclient import TestClient  # noqa: E402
from selran_hub.app import app  # noqa: E402

client = TestClient(app, headers={"X-Selran-Local": "1"})


# ---------------------------------------------------------------- identity

def test_hub_health_contract():
    r = client.get("/hub/health")
    assert r.status_code == 200
    body = r.json()
    assert body["hub"] == "selran"
    assert body["api"] == 1
    assert set(body["capabilities"]) >= {"ports", "sources", "mcp"}
    assert isinstance(body["services"], list)


def test_registry_health_compat():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    # exact fields existing clients depend on
    assert body["status"] == "ok"
    assert body["service"] == "app-port-registry"
    # the hub marker distinguishes Hub from bare registry
    assert body["hub"] == "selran"


def test_chassis_api_health_intact():
    r = client.get("/api/health")
    assert r.status_code == 200


# ---------------------------------------------------------------- registry parity

def test_ensure_report_lookup_archive_flow():
    # ensure allocates an aligned 5-port block
    r = client.post("/v1/ensure", json={"app_id": "m1-test-app", "path": "/tmp/m1-test-app"})
    assert r.status_code == 200, r.text
    first = r.json()
    rng = first["range"]  # contract: [start, end] list
    assert rng[1] - rng[0] == 4
    assert 12000 <= rng[0] <= 14000
    assert first["backend_port"] == rng[0]
    assert first["frontend_port"] == rng[0] + 1

    # idempotent: same app+path → same range
    r2 = client.post("/v1/ensure", json={"app_id": "m1-test-app", "path": "/tmp/m1-test-app"})
    assert r2.json()["range"] == rng

    # report and per-app fetch agree
    report = client.get("/v1/report").json()
    assert any(a["app_id"] == "m1-test-app" for a in report["apps"])
    got = client.get("/v1/apps/m1-test-app").json()
    assert got["range"] == rng

    # lookup by path
    looked = client.get("/v1/lookup", params={"path": "/tmp/m1-test-app"}).json()
    assert looked["app_id"] == "m1-test-app"

    # archive, then it appears in archived and leaves the active report
    arch = client.post("/v1/archive", json={"app_id": "m1-test-app", "reason": "m1 test"})
    assert arch.status_code == 200, arch.text
    archived = client.get("/v1/archived").json()
    assert any(a["app_id"] == "m1-test-app" for a in archived["apps"])
    report2 = client.get("/v1/report").json()
    assert not any(a["app_id"] == "m1-test-app" for a in report2["apps"])


def test_unknown_app_is_400_parity_quirk():
    r = client.get("/v1/apps/does-not-exist")
    assert r.status_code == 400  # historical contract: 400, not 404
    assert r.json()["status"] == "error"


def test_second_app_gets_disjoint_block():
    a = client.post("/v1/ensure", json={"app_id": "m1-app-a", "path": "/tmp/m1-a"}).json()["range"]
    b = client.post("/v1/ensure", json={"app_id": "m1-app-b", "path": "/tmp/m1-b"}).json()["range"]
    assert a[0] != b[0]
    overlap = set(range(a[0], a[1] + 1)) & set(range(b[0], b[1] + 1))
    assert not overlap


def test_validate_endpoint():
    r = client.get("/v1/validate")
    assert r.status_code == 200


def test_bad_json_body_is_400():
    r = client.post("/v1/ensure", json=["not", "an", "object"])
    assert r.status_code == 400
    assert r.json()["status"] == "error"


# ---------------------------------------------------------------- catch-all hygiene

def test_unknown_api_namespaces_404_not_html():
    for path in ("/v1/nope", "/hub/nope", "/api/nope"):
        r = client.get(path)
        assert r.status_code == 404, f"{path} → {r.status_code}"
        assert "text/html" not in r.headers.get("content-type", ""), f"{path} served HTML"

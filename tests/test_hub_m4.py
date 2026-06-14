"""M4 acceptance tests — the Greenloop live audit panel."""

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

os.environ.setdefault(
    "SELRAN_HUB_REGISTRY_DB", str(Path(tempfile.mkdtemp(prefix="hub_m4_")) / "registry.sqlite3")
)

from fastapi.testclient import TestClient  # noqa: E402
from selran_hub.app import app  # noqa: E402

client = TestClient(app, headers={"X-Selran-Local": "1"})


def create(title="Audit — selran-devloop", repo="selran-devloop", scope=None) -> dict:
    r = client.post("/v1/audit/runs", json={"title": title, "repo": repo, "scope": scope or ["1", "3", "10"]})
    assert r.status_code == 200, r.text
    return r.json()


def post_events(rid: str, events: list, expect=200):
    r = client.post(f"/v1/audit/runs/{rid}/events", json={"events": events})
    assert r.status_code == expect, r.text
    return r.json()


def test_capability_and_version():
    h = client.get("/hub/health").json()
    assert tuple(int(p) for p in h["version"].split(".")) >= (0, 4, 0)  # audit panel shipped in 0.4.0
    assert "audit" in h["capabilities"]


def test_run_create_and_page():
    run = create()
    assert run["url"].endswith(f"/audit/{run['id']}")
    page = client.get(f"/audit/{run['id']}")
    assert page.status_code == 200
    assert "Greenloop live panel" in page.text
    assert run["id"] in page.text  # polling wired to this run


def test_event_stream_derives_state():
    run = create()
    rid = run["id"]
    post_events(rid, [
        {"type": "phase", "phase": "Phase 0 — Baseline"},
        {"type": "note", "text": "pre-commit clean"},
        {"type": "phase", "phase": "Phase 3 — Execute"},
        {"type": "item", "category": "Cat 3 Security", "item": "tokens never logged"},
        {"type": "finding", "severity": "High", "title": "token in error log",
         "location": "auth/refresh.rs:88", "category": "3"},
        {"type": "item", "category": "Cat 3 Security", "item": "PII not in URLs"},
        {"type": "finding", "severity": "medium", "title": "missing pagination",
         "location": "api/list.rs:14", "category": "6"},
    ])
    st = client.get(f"/v1/audit/runs/{rid}").json()
    assert st["run_status"] == "running"
    assert st["phase"] == "Phase 3 — Execute"
    assert st["items_checked"] == 2
    assert st["current_item"] == "Cat 3 Security: PII not in URLs"
    assert st["severity_counts"]["high"] == 1 and st["severity_counts"]["medium"] == 1
    assert st["findings"][0]["severity"] == "high"  # normalized lowercase

    # fix progress (audit-fix side of the panel)
    post_events(rid, [
        {"type": "fix", "title": "token in error log", "status": "fixed", "location": "auth/refresh.rs:88"},
        {"type": "fix", "title": "missing pagination", "status": "deferred"},
        {"type": "complete", "summary": "1 fixed, 1 deferred"},
    ])
    st2 = client.get(f"/v1/audit/runs/{rid}").json()
    assert st2["run_status"] == "completed"
    assert st2["summary"] == "1 fixed, 1 deferred"
    assert [f["status"] for f in st2["fixes"]] == ["fixed", "deferred"]


def test_since_versioning():
    run = create()
    rid = run["id"]
    post_events(rid, [{"type": "phase", "phase": "P1"}])
    v = client.get(f"/v1/audit/runs/{rid}").json()["version"]
    assert client.get(f"/v1/audit/runs/{rid}", params={"since": v}).json()["status"] == "unchanged"
    post_events(rid, [{"type": "note", "text": "x"}])
    assert client.get(f"/v1/audit/runs/{rid}", params={"since": v}).json()["status"] == "ok"


def test_validation_and_404():
    assert client.get("/audit/nope").status_code == 404
    assert client.get("/v1/audit/runs/nope").status_code == 404
    run = create()
    post_events(run["id"], [{"type": "finding", "severity": "catastrophic", "title": "x"}], expect=400)
    post_events(run["id"], [{"type": "fix", "title": "x", "status": "wishful"}], expect=400)
    post_events(run["id"], [{"type": "mystery"}], expect=400)
    r = client.post("/v1/audit/runs", json={"title": "  "})
    assert r.status_code == 400


def test_bare_list_body_accepted():
    run = create()
    r = client.post(f"/v1/audit/runs/{run['id']}/events", json=[{"type": "note", "text": "bare list ok"}])
    assert r.status_code == 200

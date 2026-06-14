"""M3 acceptance tests — the design studio: interactive choice over localhost.

This is the mechanism Design Director's capability-ladder rung 0 consumes:
post HTML → serve page → user clicks data-choice → skill polls the answer.
"""

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

os.environ.setdefault(
    "SELRAN_HUB_REGISTRY_DB", str(Path(tempfile.mkdtemp(prefix="hub_m3_")) / "registry.sqlite3")
)

from fastapi.testclient import TestClient  # noqa: E402
from selran_hub.app import app  # noqa: E402

client = TestClient(app, headers={"X-Selran-Local": "1"})

PICKER_HTML = """
<div class="card" data-choice="1: Warm &amp; human"><h2>Warm &amp; human</h2></div>
<div class="card" data-choice="2: Sharp &amp; technical"><h2>Sharp &amp; technical</h2></div>
"""


def create(title="Pick a direction", html=PICKER_HTML) -> dict:
    r = client.post("/v1/studio/sessions", json={"title": title, "html": html})
    assert r.status_code == 200, r.text
    return r.json()


def test_capability_advertised():
    h = client.get("/hub/health").json()
    assert tuple(int(p) for p in h["version"].split(".")) >= (0, 3, 0)  # studio shipped in 0.3.0
    assert "studio" in h["capabilities"]


def test_session_create_and_page_serves():
    s = create()
    assert s["id"] and s["url"].endswith(f"/studio/{s['id']}")
    page = client.get(f"/studio/{s['id']}")
    assert page.status_code == 200
    assert "Selran Studio" in page.text          # wrapper bar present
    assert 'sandbox="allow-scripts"' in page.text  # skill HTML rendered sandboxed
    assert "Warm" in page.text                   # skill HTML carried (JSON-encoded into the frame)
    assert "/v1/studio/sessions/" in page.text   # choice wiring present


def test_choice_roundtrip():
    s = create()
    # pending before any click
    pend = client.get(f"/v1/studio/sessions/{s['id']}/choice").json()
    assert pend["status"] == "pending"
    # the page's JS posts the clicked value
    r = client.post(f"/v1/studio/sessions/{s['id']}/choice", json={"choice": "2: Sharp & technical"})
    assert r.status_code == 200
    # the skill polls it back
    got = client.get(f"/v1/studio/sessions/{s['id']}/choice").json()
    assert got["status"] == "ok"
    assert got["choice"] == "2: Sharp & technical"


def test_live_update_bumps_version_and_clears_stale_choice():
    s = create()
    client.post(f"/v1/studio/sessions/{s['id']}/choice", json={"choice": "1: Warm & human"})
    upd = client.post(
        f"/v1/studio/sessions/{s['id']}/update",
        json={"html": '<div data-choice="A: tighter">tighter</div>'},
    ).json()
    assert upd["version"] == 2
    # a new render invalidates the unconsumed previous answer
    assert client.get(f"/v1/studio/sessions/{s['id']}/choice").json()["status"] == "pending"
    # the open page's poll sees the new content
    c = client.get(f"/v1/studio/sessions/{s['id']}/content", params={"since": 1}).json()
    assert c["status"] == "ok" and "tighter" in c["html"]
    # and reports unchanged once caught up
    assert client.get(
        f"/v1/studio/sessions/{s['id']}/content", params={"since": 2}
    ).json()["status"] == "unchanged"


def test_unknown_session_is_404():
    assert client.get("/studio/nope").status_code == 404
    assert client.get("/v1/studio/sessions/nope/choice").status_code == 404
    assert client.post("/v1/studio/sessions/nope/choice", json={"choice": "x"}).status_code == 404


def test_validation():
    r = client.post("/v1/studio/sessions", json={"title": "t", "html": "  "})
    assert r.status_code == 400
    s = create()
    r = client.post(f"/v1/studio/sessions/{s['id']}/choice", json={"choice": ""})
    assert r.status_code == 400


def test_session_eviction_cap():
    ids = [create(title=f"s{i}")["id"] for i in range(55)]
    # oldest evicted, newest alive (cap is 50)
    alive = [i for i in ids if client.get(f"/studio/{i}").status_code == 200]
    assert len(alive) <= 50
    assert ids[-1] in alive

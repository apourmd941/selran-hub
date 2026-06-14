"""Security regression tests — CSRF/origin guard (fail-closed), CORS lockdown,
studio sandbox, and frontend path-traversal containment.

Locks in the fix for the drive-by-RCE and arbitrary-file-read findings.
"""

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault(
    "SELRAN_HUB_REGISTRY_DB", str(Path(tempfile.mkdtemp(prefix="hub_sec_")) / "registry.sqlite3")
)

from fastapi.testclient import TestClient  # noqa: E402
from selran_hub.app import app  # noqa: E402

# No default headers — every test sets exactly what it means to send.
client = TestClient(app)

LOCAL = {"X-Selran-Local": "1"}                       # a local tool / the Hub's own pages
EVIL = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
EVIL_SIMPLE = {"Origin": "https://evil.example", "Content-Type": "text/plain"}


def test_cross_origin_service_register_blocked():
    r = client.post("/v1/services", json={"id": "evil", "cwd": "/tmp", "start_cmd": "touch /tmp/pwned"}, headers=EVIL)
    assert r.status_code == 403
    r2 = client.post("/v1/services", json={"id": "evil2", "cwd": "/tmp", "start_cmd": "x"}, headers=EVIL_SIMPLE)
    assert r2.status_code == 403
    listed = client.get("/v1/services", headers=LOCAL).json()["services"]
    assert not any(s["id"].startswith("evil") for s in listed)


def test_headerless_request_to_local_surface_is_blocked():
    """The fail-closed fix: a request carrying NO Origin and NO Sec-Fetch-Site
    (the gap a prior version allowed) must STILL be refused on /v1, because it
    lacks the X-Selran-Local header a browser cannot send cross-origin."""
    r = client.post("/v1/services", json={"id": "headerless", "cwd": "/tmp", "start_cmd": "touch /tmp/pwned2"})
    assert r.status_code == 403
    assert "x-selran-local" in r.json()["error"]["message"].lower()
    # nothing registered, nothing executed
    listed = client.get("/v1/services", headers=LOCAL).json()["services"]
    assert not any(s["id"] == "headerless" for s in listed)
    assert not Path("/tmp/pwned2").exists()


def test_cross_origin_blocks_all_mutating_surfaces():
    for method, path in [
        ("POST", "/v1/ensure"),
        ("POST", "/v1/studio/sessions"),
        ("POST", "/v1/audit/runs"),
        ("POST", "/v1/entitlements/install"),
        ("DELETE", "/v1/entitlements/anything"),
    ]:
        assert client.request(method, path, json={}, headers=EVIL).status_code == 403, f"{method} {path}"
        # and header-less (no local proof) is refused too
        assert client.request(method, path, json={}).status_code == 403, f"{method} {path} headerless"


def test_local_tools_with_proof_header_work():
    r = client.post("/v1/services", json={"id": "local-ok", "cwd": "/tmp",
                                          "start_cmd": 'python3 -c "import time;time.sleep(60)"'}, headers=LOCAL)
    assert r.status_code == 200, r.text
    client.delete("/v1/services/local-ok", headers=LOCAL)


def test_same_origin_dashboard_request_allowed():
    port = int(os.environ.get("SELRAN_HUB_PORT", "11999"))
    headers = {"Origin": f"http://127.0.0.1:{port}", "Sec-Fetch-Site": "same-origin", **LOCAL}
    r = client.post("/v1/ensure", json={"app_id": "same-origin-app", "path": "/tmp/so"}, headers=headers)
    assert r.status_code == 200, r.text


def test_safe_get_requests_not_blocked():
    assert client.get("/hub/health", headers=EVIL).status_code == 200  # GET, not state-changing


def test_frontend_path_traversal_contained():
    # a non-normalizing client must not escape the frontend dir; file-specific
    # markers (not generic substrings that legit CSS could contain)
    cases = [
        ("../../../../../../etc/passwd", "root:x:0:0"),
        ("..%2f..%2f..%2fetc%2fpasswd", "root:x:0:0"),
        ("../pyproject.toml", "requires-python"),
        ("../selran_hub/app.py", "request_middleware"),
    ]
    for evil, marker in cases:
        body = client.get(f"/{evil}").text
        assert marker not in body, f"leaked {evil} (found {marker!r})"


def test_studio_html_is_sandboxed():
    s = client.post("/v1/studio/sessions",
                    json={"title": "t", "html": '<img src=x onerror="alert(1)"><div data-choice="1">A</div>'},
                    headers=LOCAL).json()
    page = client.get(f"/studio/{s['id']}").text
    assert 'sandbox="allow-scripts"' in page
    assert "allow-same-origin" not in page
    assert '<img src=x onerror="alert(1)">' not in page


def test_cors_not_wildcard():
    r = client.get("/hub/health", headers={"Origin": "https://evil.example"})
    assert r.headers.get("access-control-allow-origin") not in ("*", "https://evil.example")

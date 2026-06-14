"""M6 acceptance tests — entitlements: offline license verification.

Uses an ephemeral test keypair (env-injected public key) so tests never
touch the real Selran signing authority.
"""

import json
import os
import secrets
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_tmp = Path(tempfile.mkdtemp(prefix="hub_m6_"))
os.environ.setdefault("SELRAN_HUB_REGISTRY_DB", str(_tmp / "registry.sqlite3"))
os.environ["SELRAN_HUB_LICENSES_DIR"] = str(_tmp / "licenses")

# test signing authority
_PRIV = Ed25519PrivateKey.generate()
_PUB_HEX = _PRIV.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw
).hex()
os.environ["SELRAN_HUB_LICENSE_PUBKEY"] = _PUB_HEX

from fastapi.testclient import TestClient  # noqa: E402
from selran_hub.app import app  # noqa: E402

client = TestClient(app, headers={"X-Selran-Local": "1"})


def issue(product="pack-fintech", tier="commercial", licensee="Test User <t@example.com>",
          expires_at=None, tamper=False) -> dict:
    lic = {
        "id": f"lic_{secrets.token_urlsafe(6)}",
        "product": product,
        "licensee": licensee,
        "tier": tier,
        "issued_at": "2026-06-10T00:00:00Z",
        "expires_at": expires_at,
    }
    canonical = json.dumps(lic, sort_keys=True, separators=(",", ":")).encode()
    sig = _PRIV.sign(canonical).hex()
    if tamper:
        lic["tier"] = "enterprise"  # modify after signing
    return {"license": lic, "signature": sig}


def test_capability_advertised():
    h = client.get("/hub/health").json()
    assert tuple(int(p) for p in h["version"].split(".")) >= (0, 6, 0)
    assert "entitlements" in h["capabilities"]


def test_install_and_check():
    r = client.post("/v1/entitlements/install", json=issue())
    assert r.status_code == 200, r.text
    assert r.json()["entitlement"]["valid"] is True

    chk = client.get("/v1/entitlements/check", params={"product": "pack-fintech"}).json()
    assert chk["entitled"] is True
    assert chk["tier"] == "commercial"

    miss = client.get("/v1/entitlements/check", params={"product": "pack-luxury"}).json()
    assert miss["entitled"] is False


def test_tampered_license_rejected():
    r = client.post("/v1/entitlements/install", json=issue(tamper=True))
    assert r.status_code == 400
    assert "signature" in r.json()["message"].lower()


def test_expired_license_rejected():
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    r = client.post("/v1/entitlements/install", json=issue(expires_at=past))
    assert r.status_code == 400
    assert "expired" in r.json()["message"]


def test_garbage_rejected():
    assert client.post("/v1/entitlements/install", json={"hello": "world"}).status_code == 400


def test_packs_all_covers_everything():
    client.post("/v1/entitlements/install", json=issue(product="packs-all", tier="enterprise"))
    chk = client.get("/v1/entitlements/check", params={"product": "pack-luxury"}).json()
    assert chk["entitled"] is True and chk["tier"] == "enterprise"


def test_remove_license():
    doc = issue(product="pack-edtech")
    client.post("/v1/entitlements/install", json=doc)
    lid = doc["license"]["id"]
    assert client.delete(f"/v1/entitlements/{lid}").status_code == 200
    listed = client.get("/v1/entitlements").json()["entitlements"]
    assert not any(e["id"] == lid for e in listed)


def test_pack_catalog_reflects_entitlements():
    cat = client.get("/v1/packs").json()
    assert cat["status"] == "ok" and len(cat["packs"]) >= 20
    fintech = next(p for p in cat["packs"] if p["product"] == "pack-fintech")
    assert fintech["entitled"] is True  # installed in test_install_and_check
    assert all(p["entitled"] for p in cat["packs"])  # packs-all covers the rest
    assert fintech["purchase_url"].startswith("https://selran.com/packs/")


def test_packs_page_serves():
    r = client.get("/hub/packs")
    assert r.status_code == 200
    assert "Design Director packs" in r.text


def test_issuer_tool_roundtrip(tmp_path):
    """The owner-side tool's output must verify against its own key."""
    import subprocess
    key = tmp_path / "k.pem"
    key.write_bytes(_PRIV.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    out = tmp_path / "lic.json"
    r = subprocess.run(
        [sys.executable, str(REPO / "tools" / "issue_license.py"),
         "--product", "pack-saas-b2b", "--licensee", "Round Trip <rt@example.com>",
         "--tier", "personal", "--key", str(key), "-o", str(out)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    doc = json.loads(out.read_text())
    inst = client.post("/v1/entitlements/install", json=doc)
    assert inst.status_code == 200, inst.text

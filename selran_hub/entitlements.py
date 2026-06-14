"""Selran Hub entitlements (spec §10, M6) — offline-verified pack licenses.

A license is a JSON document signed with Selran's Ed25519 key. The Hub ships
only the PUBLIC key and verifies entirely offline (spec §2.2: no egress, no
license server, no phone-home). Installed licenses live as plain files the
user can inspect: ~/.selran/hub/licenses/<id>.json.

License file shape:
  {
    "license": {
      "id": "lic_<token>",
      "product": "pack-fintech" | "packs-all" | "<entitlement key>",
      "licensee": "name <email>",
      "tier": "personal" | "commercial" | "enterprise",
      "issued_at": "2026-06-10T00:00:00Z",
      "expires_at": null | "2027-06-10T00:00:00Z"
    },
    "signature": "<hex ed25519 over canonical-JSON of the license object>"
  }

Canonical JSON: json.dumps(license, sort_keys=True, separators=(",", ":")).

Honesty note (documented, not hidden): offline licensing keeps honest users
honest and gives businesses a compliance artifact. It is not DRM — the code
is on the user's machine. That is the accepted trade-off of local-first.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# The Selran license authority (Ed25519 public key, hex). The private half
# lives only with Selran (Aidin Eslampour) and never ships.
SELRAN_LICENSE_PUBKEY_HEX = "d48078d5aea3ef73d2708476483cab25ae19a0624b6e92a8292da0d881b3d4d4"

LICENSES_DIR = Path.home() / ".selran" / "hub" / "licenses"

REQUIRED_FIELDS = ("id", "product", "licensee", "tier", "issued_at")
TIERS = ("personal", "commercial", "enterprise")


def _pubkey() -> Ed25519PublicKey:
    hexkey = os.environ.get("SELRAN_HUB_LICENSE_PUBKEY", SELRAN_LICENSE_PUBKEY_HEX)
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(hexkey))


def canonical(license_obj: dict[str, Any]) -> bytes:
    return json.dumps(license_obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


class LicenseError(Exception):
    pass


def verify_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Validate shape + signature + expiry. Returns the license object.
    Raises LicenseError with a human-readable reason."""
    if not isinstance(doc, dict) or "license" not in doc or "signature" not in doc:
        raise LicenseError("not a license file (need 'license' and 'signature')")
    lic = doc["license"]
    if not isinstance(lic, dict):
        raise LicenseError("'license' must be an object")
    for f in REQUIRED_FIELDS:
        if not str(lic.get(f, "")).strip():
            raise LicenseError(f"license field '{f}' is missing")
    if lic["tier"] not in TIERS:
        raise LicenseError(f"unknown tier {lic['tier']!r} (expected one of {TIERS})")
    try:
        _pubkey().verify(bytes.fromhex(str(doc["signature"])), canonical(lic))
    except (InvalidSignature, ValueError):
        raise LicenseError("signature verification failed — file is not a genuine Selran license (or was modified)")
    exp = lic.get("expires_at")
    if exp:
        try:
            expires = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
        except ValueError:
            raise LicenseError(f"unparseable expires_at: {exp!r}")
        if expires < datetime.now(timezone.utc):
            raise LicenseError(f"license expired on {exp}")
    return lic


class EntitlementManager:
    def __init__(self, licenses_dir: Path | None = None):
        self.dir = licenses_dir or Path(
            os.environ.get("SELRAN_HUB_LICENSES_DIR", str(LICENSES_DIR))
        )

    def install(self, doc: dict[str, Any]) -> dict[str, Any]:
        lic = verify_document(doc)  # refuse to store anything invalid
        self.dir.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(c for c in lic["id"] if c.isalnum() or c in "-_")
        path = self.dir / f"{safe_id}.json"
        path.write_text(json.dumps(doc, indent=2, sort_keys=True))
        return self._summary(lic, valid=True, reason="installed")

    def remove(self, license_id: str) -> bool:
        safe_id = "".join(c for c in license_id if c.isalnum() or c in "-_")
        path = self.dir / f"{safe_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def list_entitlements(self) -> list[dict[str, Any]]:
        out = []
        if not self.dir.is_dir():
            return out
        for f in sorted(self.dir.glob("*.json")):
            try:
                doc = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                out.append({"id": f.stem, "valid": False, "reason": "unreadable file"})
                continue
            try:
                lic = verify_document(doc)
                out.append(self._summary(lic, valid=True, reason="ok"))
            except LicenseError as exc:
                lic = doc.get("license", {}) if isinstance(doc, dict) else {}
                out.append({
                    "id": str(lic.get("id", f.stem)),
                    "product": str(lic.get("product", "")),
                    "valid": False,
                    "reason": str(exc),
                })
        return out

    def check(self, product: str) -> dict[str, Any]:
        """The API design-director's pack flow queries (spec §10)."""
        product = (product or "").strip()
        if not product:
            return {"entitled": False, "reason": "no product given"}
        best: dict[str, Any] | None = None
        for ent in self.list_entitlements():
            if not ent.get("valid"):
                continue
            if ent["product"] == product or ent["product"] in ("packs-all", "all"):
                if best is None or TIERS.index(ent["tier"]) > TIERS.index(best["tier"]):
                    best = ent
        if best:
            return {
                "entitled": True,
                "product": product,
                "tier": best["tier"],
                "licensee": best["licensee"],
                "license_id": best["id"],
                "expires_at": best.get("expires_at"),
            }
        return {
            "entitled": False,
            "product": product,
            "reason": "no valid license covers this product",
        }

    @staticmethod
    def _summary(lic: dict[str, Any], valid: bool, reason: str) -> dict[str, Any]:
        return {
            "id": lic["id"],
            "product": lic["product"],
            "licensee": lic["licensee"],
            "tier": lic["tier"],
            "issued_at": lic["issued_at"],
            "expires_at": lic.get("expires_at"),
            "valid": valid,
            "reason": reason,
        }

#!/usr/bin/env python3
"""Selran license issuer — OWNER-SIDE tool (requires the private signing key).

Usage:
  python3 tools/issue_license.py --product pack-fintech \
      --licensee "Jane Dev <jane@example.com>" --tier commercial \
      [--expires 2027-06-10] [--key ~/.selran/keys/selran-signing.key] [-o out.json]

The output file is what a customer installs:
  selran-hub: POST /v1/entitlements/install with the file's JSON body
  (or drop it into ~/.selran/hub/licenses/).
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True, help="entitlement key, e.g. pack-fintech or packs-all")
    ap.add_argument("--licensee", required=True)
    ap.add_argument("--tier", choices=["personal", "commercial", "enterprise"], required=True)
    ap.add_argument("--expires", default=None, help="YYYY-MM-DD (omit for perpetual)")
    ap.add_argument("--key", default=str(Path.home() / ".selran" / "keys" / "selran-signing.key"))
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args()

    key_path = Path(args.key).expanduser()
    if not key_path.exists():
        print(f"signing key not found: {key_path}", file=sys.stderr)
        return 1
    priv = serialization.load_pem_private_key(key_path.read_bytes(), password=None)

    lic = {
        "id": f"lic_{secrets.token_urlsafe(9)}",
        "product": args.product,
        "licensee": args.licensee,
        "tier": args.tier,
        "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "expires_at": (args.expires + "T00:00:00Z") if args.expires else None,
    }
    canonical = json.dumps(lic, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = priv.sign(canonical).hex()
    doc = {"license": lic, "signature": sig}

    out = Path(args.out) if args.out else Path(f"{lic['id']}.json")
    out.write_text(json.dumps(doc, indent=2, sort_keys=True))
    print(f"issued {lic['id']} → {out}")
    print(f"  product: {lic['product']} | tier: {lic['tier']} | licensee: {lic['licensee']}")
    print(f"  expires: {lic['expires_at'] or 'never'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

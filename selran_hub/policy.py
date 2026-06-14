"""Managed policy / MDM layer (H9).

An admin-deployed, read-only policy file an organization installs via MDM /
configuration management to lock down a Hub on a managed machine. The Hub READS
it (never writes it) and ENFORCES it; a normal user can't override it because it
lives in a system-managed, root-owned location.

This is the LOCAL-FIRST equivalent of Claude Code's managed-settings.json. It is
deliberately NOT a cloud fleet-management / multi-tenant / RBAC control plane —
the Hub has no backend and stays single-machine; org-wide rollout is the admin's
existing MDM pushing this one file to each managed Mac/PC.

Policy file (JSON, every key optional):
  {
    "allow_remote_transport": false,        // the bridge refuses any non-loopback bind
    "allowed_source_types": ["sqlite","duckdb","folder"],  // block e.g. "api" (egress)
    "require_auth": true,                    // /api stays locked until an API key is set
    "disable_update_check": true,           // force the opt-in update check off
    "require_keyring": true,                 // secrets must use the OS keychain (surfaced)
    "note": "free-form admin note"
  }

Override the location with SELRAN_HUB_POLICY_FILE (testing / non-standard deploy).
"""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Optional

ENV_OVERRIDE = "SELRAN_HUB_POLICY_FILE"


def policy_path() -> Path:
    env = os.environ.get(ENV_OVERRIDE)
    if env:
        return Path(env)
    system = platform.system()
    if system == "Darwin":
        return Path("/Library/Application Support/Selran Hub/managed-policy.json")
    if system == "Windows":
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return Path(base) / "Selran Hub" / "managed-policy.json"
    return Path("/etc/selran-hub/policy.json")


def load_policy() -> dict:
    """The raw policy dict (empty when no managed policy is deployed). Not cached
    so a redeploy / a test takes effect immediately; the file is tiny."""
    p = policy_path()
    try:
        if p.is_file():
            data = json.loads(p.read_text())
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def is_managed() -> bool:
    return bool(load_policy())


# ----------------------------------------------------------- typed accessors

def allow_remote_transport() -> bool:
    return bool(load_policy().get("allow_remote_transport", True))


def allowed_source_types() -> Optional[set]:
    v = load_policy().get("allowed_source_types")
    if isinstance(v, list) and v:
        return {str(x).lower() for x in v}
    return None  # None = all source types allowed


def require_auth() -> bool:
    return bool(load_policy().get("require_auth", False))


def update_check_disabled() -> bool:
    return bool(load_policy().get("disable_update_check", False))


def require_keyring() -> bool:
    return bool(load_policy().get("require_keyring", False))


def effective() -> dict:
    """The resolved, enforced policy — what GET /v1/policy returns (read-only)."""
    src_types = allowed_source_types()
    return {
        "managed": is_managed(),
        "source": str(policy_path()) if is_managed() else None,
        "allow_remote_transport": allow_remote_transport(),
        "allowed_source_types": sorted(src_types) if src_types else None,
        "require_auth": require_auth(),
        "disable_update_check": update_check_disabled(),
        "require_keyring": require_keyring(),
        "note": load_policy().get("note"),
    }

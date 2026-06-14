"""Cross-platform secret storage for the Hub (H5).

Secrets — the API-key auth token and data-source credentials (API endpoint
headers / bearer tokens) — live in the OS keychain: macOS Keychain, Windows
Credential Manager, or the Linux Secret Service, via the `keyring` library.
When no OS keychain backend is available (common on headless Linux/servers), it
falls back to a single owner-only (mode 0600) JSON file under the Hub's data
dir. Either way, secrets leave the old world-readable plaintext.

  service name : "selran-hub"
  keys         : short strings, e.g. "api-key", "source-headers:<source_id>"
  values       : strings; the *_json helpers (de)serialize dicts.

Set SELRAN_HUB_SECRETS_BACKEND=file to force the file fallback (tests, or a
deliberate no-keychain deployment).
"""

from __future__ import annotations

import json
import os
import stat as _stat
import tempfile
from pathlib import Path
from typing import Any, Optional

SERVICE = "selran-hub"

try:
    import keyring  # type: ignore
    _HAVE_KEYRING = True
except Exception:  # pragma: no cover - exercised only without the dep
    keyring = None  # type: ignore
    _HAVE_KEYRING = False

_backend_cache: Optional[str] = None  # "keyring" | "file"


def _fallback_file() -> Path:
    from .config import get_data_dir
    return get_data_dir() / "secrets.json"


def _usable_keyring() -> bool:
    if not _HAVE_KEYRING:
        return False
    try:
        kr = keyring.get_keyring()
        # The fail backend has priority < 0; real OS backends are > 0.
        if getattr(kr, "priority", 0) <= 0:
            return False
    except Exception:
        return False
    # Prove a real round-trip before trusting it (some backends import but error
    # on use, e.g. a locked/absent Secret Service). Always clean up the probe.
    did_set = False
    try:
        keyring.set_password(SERVICE, "__probe__", "ok")
        did_set = True
        return keyring.get_password(SERVICE, "__probe__") == "ok"
    except Exception:
        return False
    finally:
        if did_set:
            try:
                keyring.delete_password(SERVICE, "__probe__")
            except Exception:
                pass


def backend() -> str:
    """'keyring' if a usable OS keychain is present, else 'file'. Cached."""
    global _backend_cache
    forced = os.environ.get("SELRAN_HUB_SECRETS_BACKEND")
    if forced == "file":
        return "file"
    if forced == "keyring" and _HAVE_KEYRING:
        return "keyring"  # explicit opt-in; honored only if the lib is present
    if _backend_cache is None:
        _backend_cache = "keyring" if _usable_keyring() else "file"
    return _backend_cache


# ----------------------------------------------------------------- file backend

def _tighten(path: Path) -> None:
    """Re-assert owner-only (0600) on an existing file — covers a file left
    world-readable by an older Hub or a migrated-from-plaintext file."""
    try:
        if _stat.S_IMODE(os.stat(path).st_mode) != 0o600:
            os.chmod(path, 0o600)
    except Exception:
        pass


def _read_file() -> dict[str, str]:
    p = _fallback_file()
    if not p.exists():
        return {}
    _tighten(p)
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _write_file(data: dict[str, str]) -> None:
    p = _fallback_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    # Atomic + owner-only: write a 0600 temp file in the same dir, fsync, then
    # os.replace — so a crash mid-write can't truncate/lose the whole store.
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".secrets-", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
        try:
            os.chmod(p, 0o600)
        except Exception:
            pass
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except Exception:
                pass


# ----------------------------------------------------------------- public API

def set_secret(key: str, value: Optional[str]) -> None:
    if value is None:
        delete_secret(key)
        return
    if backend() == "keyring":
        keyring.set_password(SERVICE, key, value)
        return
    data = _read_file()
    data[key] = value
    _write_file(data)


def get_secret(key: str) -> Optional[str]:
    if backend() == "keyring":
        try:
            return keyring.get_password(SERVICE, key)
        except Exception:
            return None
    return _read_file().get(key)


def delete_secret(key: str) -> None:
    if backend() == "keyring":
        try:
            keyring.delete_password(SERVICE, key)
        except Exception:
            pass
        return
    data = _read_file()
    if key in data:
        del data[key]
        _write_file(data)


def set_json(key: str, obj: Any) -> None:
    set_secret(key, json.dumps(obj))


def get_json(key: str) -> Optional[Any]:
    raw = get_secret(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None

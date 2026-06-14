"""
Cross-platform data directory and configuration for Selran Hub.

User data (sources.json, logs, auth) is stored in the OS-standard location:
  macOS:   ~/Library/Application Support/Selran Hub/
  Linux:   ~/.config/Selran Hub/
  Windows: %APPDATA%/Selran Hub/

(The port registry, service registry, and licenses live separately under
~/.config and ~/.selran.) The repo/code directory stays clean — no user data.
"""

from __future__ import annotations

import json
import os
import platform
import secrets
from pathlib import Path

# Single source of truth for the Hub version. hub_router re-exports this as
# HUB_VERSION and __init__ as __version__; keep pyproject.toml in sync manually.
APP_NAME = "Selran Hub"
VERSION = "0.15.1"


def get_data_dir() -> Path:
    """Return the OS-standard directory for storing user data."""
    system = platform.system()

    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:  # Linux and others
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

    data_dir = base / APP_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_sources_file() -> Path:
    """Path to sources.json (registered data sources)."""
    return get_data_dir() / "sources.json"


def get_log_dir() -> Path:
    """Path to log directory."""
    log_dir = get_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_log_file() -> Path:
    """Path to the main application log file."""
    return get_log_dir() / "selran-hub.log"


def get_request_log_file() -> Path:
    """Path to the API request log file."""
    return get_log_dir() / "requests.log"


# ---------------------------------------------------------------------------
# Auth — optional API key stored in data dir
# ---------------------------------------------------------------------------

def get_auth_file() -> Path:
    return get_data_dir() / "auth.json"


def _read_auth_record() -> dict:
    """The auth record holds only the non-secret `enabled` flag now. (Legacy
    records may still carry a plaintext `api_key` — get_api_key migrates it.)"""
    from .pg_store import backend_active, load_auth
    if backend_active():
        try:
            return load_auth() or {}
        except Exception:
            return {}
    auth_file = get_auth_file()
    if not auth_file.exists():
        return {}
    try:  # re-tighten a legacy/loose file (may still hold a plaintext key)
        import stat as _stat
        if _stat.S_IMODE(os.stat(auth_file).st_mode) != 0o600:
            os.chmod(auth_file, 0o600)
    except Exception:
        pass
    try:
        return json.loads(auth_file.read_text())
    except Exception:
        return {}


def _write_auth_record(enabled: bool) -> None:
    """Persist ONLY {enabled: bool} — never the key. File is mode 0600."""
    from .pg_store import backend_active, save_auth
    if backend_active():
        save_auth({"enabled": enabled})
        return
    auth_file = get_auth_file()
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(auth_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"enabled": enabled}, f, indent=2)
    try:
        os.chmod(auth_file, 0o600)
    except Exception:
        pass


def get_api_key() -> str | None:
    """Return the API key if auth is enabled, else None.

    The key lives in the OS keychain (secrets_store). A legacy plaintext
    `api_key` left in auth.json / Postgres is migrated into the keychain on
    first read and scrubbed from disk."""
    from . import secrets_store
    rec = _read_auth_record()
    legacy = rec.get("api_key")
    if legacy:  # migrate old plaintext → keychain, then scrub the record
        secrets_store.set_secret("api-key", legacy)
        _write_auth_record(bool(rec.get("enabled", False)))
    if not rec.get("enabled", False):
        return None
    return secrets_store.get_secret("api-key")


def set_api_key(enabled: bool, key: str | None = None) -> str:
    """Enable or disable API key auth. The key is stored in the OS keychain;
    only the enabled flag is persisted to disk. Returns the key."""
    from . import secrets_store
    if enabled and not key:
        key = secrets.token_urlsafe(32)
    if enabled and key:
        secrets_store.set_secret("api-key", key)
    else:
        secrets_store.delete_secret("api-key")
    _write_auth_record(enabled)
    return key or ""


# ---------------------------------------------------------------------------
# Headless detection
# ---------------------------------------------------------------------------

def is_headless() -> bool:
    """Detect if running without a GUI (headless service)."""
    system = platform.system()

    if system == "Darwin":
        # Check if we have a window server connection
        display = os.environ.get("DISPLAY")
        session = os.environ.get("TERM_SESSION_ID") or os.environ.get("TERM_PROGRAM")
        # LaunchAgent runs without these typically
        has_gui = bool(session) or bool(os.environ.get("Apple_PubSub_Socket_Render"))
        return not has_gui

    elif system == "Linux":
        return not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")

    elif system == "Windows":
        try:
            import ctypes
            hdesktop = ctypes.windll.user32.OpenDesktopW("default", 0, False, 0x0100)
            if hdesktop:
                ctypes.windll.user32.CloseDesktop(hdesktop)
                return False
            return True
        except Exception:
            return False

    return False

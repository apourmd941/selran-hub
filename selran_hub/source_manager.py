"""
SourceManager — handles CRUD, health checks, import/export, and
config generation for all registered data sources.
"""

from __future__ import annotations

import copy
import json
import os
import stat as _stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _secret_key(source_id: str) -> str:
    return f"source-headers:{source_id}"


def _endpoint_key(ep: dict, idx: int = 0) -> str:
    # name → path → positional fallback, so two unnamed endpoints can't collide
    # on an empty key.
    return ep.get("name") or ep.get("path") or f"#{idx}"

from pydantic import BaseModel

from .connectors.base import BaseConnector
from .connectors.folder_connector import FolderConnector
from .connectors.duckdb_connector import DuckDBConnector
from .connectors.sqlite_connector import SQLiteConnector
from .connectors.api_connector import APIConnector


CONNECTOR_MAP: dict[str, type[BaseConnector]] = {
    "folder": FolderConnector,
    "duckdb": DuckDBConnector,
    "sqlite": SQLiteConnector,
    "api": APIConnector,
}


class SourceManager:
    def __init__(self, sources_file: Path):
        self.sources_file = sources_file
        self._sources: dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self):
        # When HUB_DATABASE_URL is set in the environment, route the registry
        # through Postgres instead of the JSON file. Runs without it keep using
        # the file (no setup required).
        from .pg_store import backend_active, load_sources
        if backend_active():
            try:
                data = load_sources()
            except Exception:
                data = []
            self._sources = {s["id"]: s for s in data if s.get("id")}
        elif self.sources_file.exists():
            try:  # re-tighten a legacy/loose file regardless of a pending write
                if _stat.S_IMODE(os.stat(self.sources_file).st_mode) != 0o600:
                    os.chmod(self.sources_file, 0o600)
            except Exception:
                pass
            try:
                data = json.loads(self.sources_file.read_text())
                self._sources = {s["id"]: s for s in data}
            except Exception:
                self._sources = {}
        self._migrate_inline_secrets()

    def _save(self):
        # Persist with secrets stripped — credentials live in the OS keychain
        # (secrets_store), never in sources.json / Postgres.
        payload = []
        for s in self._sources.values():
            c = copy.deepcopy(s)
            self._strip_secrets(c)
            payload.append(c)
        from .pg_store import backend_active, save_sources
        if backend_active():
            save_sources(payload)
            return
        self.sources_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.sources_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
        try:
            os.chmod(self.sources_file, 0o600)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Secret handling (H5) — endpoint credentials live in the OS keychain
    #
    # The credential channel is the endpoint `headers` map (e.g.
    # Authorization: Bearer …): those are moved to the keychain and stripped from
    # disk / API responses. An endpoint's `params` (query string) and `body`
    # (POST body) are treated as NON-secret request config and stay in the source
    # — do NOT put tokens there; put them in `headers`.
    # ------------------------------------------------------------------

    def _persist_secrets(self, src: dict, reconcile: bool = False) -> None:
        """Move an api source's non-empty endpoint headers into the keychain.

        Default merge keeps a token an edit didn't re-send. With reconcile=True
        (used on update) it ALSO drops keychain entries for endpoints that are no
        longer present, so a renamed/removed endpoint can't orphan a credential."""
        if src.get("type") != "api":
            return
        from . import secrets_store
        eps = (src.get("rules") or {}).get("endpoints") or []
        new = {}
        for i, ep in enumerate(eps):
            if ep.get("headers"):
                new[_endpoint_key(ep, i)] = ep["headers"]
        key = _secret_key(src["id"])
        if reconcile:
            present = {_endpoint_key(ep, i) for i, ep in enumerate(eps)}
            kept = {k: v for k, v in (secrets_store.get_json(key) or {}).items() if k in present}
            kept.update(new)
            if kept:
                secrets_store.set_json(key, kept)
            else:
                secrets_store.delete_secret(key)
            return
        if not new:
            return
        existing = secrets_store.get_json(key) or {}
        existing.update(new)
        secrets_store.set_json(key, existing)

    def _strip_secrets(self, src: dict) -> None:
        """Remove endpoint headers from a source dict in place."""
        for ep in (src.get("rules") or {}).get("endpoints") or []:
            if ep.get("headers"):
                ep["headers"] = {}

    def _inject_secrets(self, src: dict) -> dict:
        """Deep copy of an api source with endpoint headers restored from the
        keychain — used only to build a connector, never persisted."""
        if src.get("type") != "api":
            return src
        from . import secrets_store
        headers_map = secrets_store.get_json(_secret_key(src["id"])) or {}
        if not headers_map:
            return src
        s = copy.deepcopy(src)
        for i, ep in enumerate((s.get("rules") or {}).get("endpoints") or []):
            key = _endpoint_key(ep, i)
            if key in headers_map and not ep.get("headers"):
                ep["headers"] = headers_map[key]
        return s

    def _delete_secrets(self, source_id: str) -> None:
        from . import secrets_store
        secrets_store.delete_secret(_secret_key(source_id))

    def _migrate_inline_secrets(self) -> None:
        """One-time: move any headers found inline (legacy plaintext sources)
        into the keychain and rewrite without them."""
        dirty = False
        for src in self._sources.values():
            if src.get("type") != "api":
                continue
            if any(ep.get("headers") for ep in (src.get("rules") or {}).get("endpoints") or []):
                try:
                    self._persist_secrets(src)
                    self._strip_secrets(src)
                    dirty = True
                except Exception:
                    # Keychain transiently unavailable — leave the inline secret
                    # in place to retry on a later load; NEVER crash construction
                    # (this runs at import time via the app's manager singleton).
                    pass
        if dirty:
            try:
                self._save()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Connector factory
    # ------------------------------------------------------------------

    def _get_connector(self, source: dict) -> Optional[BaseConnector]:
        cls = CONNECTOR_MAP.get(source["type"])
        if not cls:
            return None
        # Inject keychain-held credentials into a transient copy for the
        # connector; self._sources stays stripped.
        return cls(self._inject_secrets(source))

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list_all(self) -> list[dict]:
        results = []
        for src in self._sources.values():
            conn = self._get_connector(src)
            if conn and src.get("enabled", True):
                try:
                    ok, err = conn.health_check()
                    src["status"] = "online" if ok else "error"
                    src["error"] = err
                except Exception as e:
                    src["status"] = "error"
                    src["error"] = str(e)
            elif not src.get("enabled", True):
                src["status"] = "offline"
            src["last_checked"] = _now()
            results.append(src)
        self._save()
        return results

    def get(self, source_id: str) -> Optional[dict]:
        src = self._sources.get(source_id)
        if not src:
            return None
        conn = self._get_connector(src)
        if conn and src.get("enabled", True):
            try:
                ok, err = conn.health_check()
                src["status"] = "online" if ok else "error"
                src["error"] = err
                src["stats"] = conn.get_stats()
            except Exception as e:
                src["status"] = "error"
                src["error"] = str(e)
        src["last_checked"] = _now()
        self._save()
        return src

    def create(self, body) -> dict:
        source_id = str(uuid.uuid4())[:8]
        src = {
            "id": source_id,
            "name": body.name,
            "type": body.type,
            "path": body.path,
            "url": body.url,
            "description": body.description,
            "rules": body.rules,
            "enabled": True,
            "status": "offline",
            "error": None,
            "created_at": _now(),
            "last_checked": None,
            "stats": {},
        }
        # Move any credentials to the keychain before the source is stored.
        self._persist_secrets(src)
        # Initial health check (connector gets credentials via _get_connector).
        conn = self._get_connector(src)
        if conn:
            try:
                ok, err = conn.health_check()
                src["status"] = "online" if ok else "error"
                src["error"] = err
                src["stats"] = conn.get_stats()
            except Exception as e:
                src["status"] = "error"
                src["error"] = str(e)
        src["last_checked"] = _now()
        self._strip_secrets(src)
        self._sources[source_id] = src
        self._save()
        return src

    def update(self, source_id: str, body) -> Optional[dict]:
        src = self._sources.get(source_id)
        if not src:
            return None
        if body.name is not None:
            src["name"] = body.name
        if body.description is not None:
            src["description"] = body.description
        if body.path is not None:
            src["path"] = body.path
        if body.url is not None:
            src["url"] = body.url
        if body.rules is not None:
            src["rules"] = body.rules
            self._persist_secrets(src, reconcile=True)  # add new, prune removed/renamed
            self._strip_secrets(src)    # keep self._sources free of secrets
        if body.enabled is not None:
            src["enabled"] = body.enabled
            src["status"] = "offline" if not body.enabled else src["status"]

        # Re-check health after a path / url / credentials change
        if body.path is not None or body.url is not None or body.rules is not None:
            conn = self._get_connector(src)
            if conn and src.get("enabled", True):
                try:
                    ok, err = conn.health_check()
                    src["status"] = "online" if ok else "error"
                    src["error"] = err
                    src["stats"] = conn.get_stats()
                except Exception as e:
                    src["status"] = "error"
                    src["error"] = str(e)
                src["last_checked"] = _now()

        self._save()
        return src

    def delete(self, source_id: str) -> bool:
        if source_id not in self._sources:
            return False
        del self._sources[source_id]
        self._delete_secrets(source_id)
        self._save()
        return True

    def toggle(self, source_id: str) -> Optional[dict]:
        src = self._sources.get(source_id)
        if not src:
            return None
        src["enabled"] = not src.get("enabled", True)
        if not src["enabled"]:
            src["status"] = "offline"
        self._save()
        return src

    def check(self, source_id: str) -> Optional[dict]:
        src = self._sources.get(source_id)
        if not src:
            return None
        conn = self._get_connector(src)
        if conn:
            try:
                ok, err = conn.health_check()
                src["status"] = "online" if ok else "error"
                src["error"] = err
                src["stats"] = conn.get_stats()
            except Exception as e:
                src["status"] = "error"
                src["error"] = str(e)
        src["last_checked"] = _now()
        self._save()
        return src

    # ------------------------------------------------------------------
    # Data exploration
    # ------------------------------------------------------------------

    def list_tables(self, source_id: str) -> Optional[list]:
        src = self._sources.get(source_id)
        if not src:
            return None
        conn = self._get_connector(src)
        if not conn:
            return []
        return conn.list_tables()

    def preview(self, source_id: str, table_name: str, limit: int = 20) -> Optional[dict]:
        src = self._sources.get(source_id)
        if not src:
            return None
        conn = self._get_connector(src)
        if not conn:
            return None
        return conn.preview(table_name, limit)

    def query(self, source_id: str, sql: str, limit: int = 1000) -> Optional[dict]:
        src = self._sources.get(source_id)
        if not src:
            return None
        conn = self._get_connector(src)
        if not conn:
            return {"error": "No connector for this source type"}
        if not hasattr(conn, "query"):
            return {"error": f"Source type '{src['type']}' does not support SQL queries"}
        return conn.query(sql, limit)

    def describe(self, source_id: str, table_name: str) -> Optional[dict]:
        src = self._sources.get(source_id)
        if not src:
            return None
        conn = self._get_connector(src)
        if not conn:
            return {"error": "No connector for this source type"}
        if not hasattr(conn, "describe"):
            return {"error": f"Source type '{src['type']}' does not support describe"}
        return conn.describe(table_name)

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------

    def export_config(self) -> dict:
        """Export all source configurations (without runtime status)."""
        sources = []
        for src in self._sources.values():
            exported = {
                "name": src["name"],
                "type": src["type"],
                "path": src.get("path"),
                "url": src.get("url"),
                "description": src.get("description", ""),
                "rules": src.get("rules", {}),
                "enabled": src.get("enabled", True),
            }
            sources.append(exported)
        return {
            "version": "1.0",
            "exported_at": _now(),
            "source_count": len(sources),
            "sources": sources,
        }

    def import_config(self, sources: list[dict]) -> dict:
        """Import source configurations. Skips duplicates by name."""
        imported = 0
        skipped = 0
        errors = []
        existing_names = {s["name"].lower() for s in self._sources.values()}
        from . import policy
        allowed_types = policy.allowed_source_types()  # H9: same restriction as create()

        for src_data in sources:
            name = src_data.get("name", "")
            if not name:
                errors.append("Source missing name — skipped")
                continue
            if name.lower() in existing_names:
                skipped += 1
                continue
            stype = str(src_data.get("type", "folder")).lower()
            if allowed_types is not None and stype not in allowed_types:
                errors.append(f"Source '{name}' type '{stype}' not allowed by org policy — skipped")
                continue
            try:
                source_id = str(uuid.uuid4())[:8]
                src = {
                    "id": source_id,
                    "name": name,
                    "type": src_data.get("type", "folder"),
                    "path": src_data.get("path"),
                    "url": src_data.get("url"),
                    "description": src_data.get("description", ""),
                    "rules": src_data.get("rules", {"read_only": True, "row_limit": 1000}),
                    "enabled": src_data.get("enabled", True),
                    "status": "offline",
                    "error": None,
                    "created_at": _now(),
                    "last_checked": None,
                    "stats": {},
                }
                self._persist_secrets(src)  # any imported credentials → keychain
                self._strip_secrets(src)
                self._sources[source_id] = src
                existing_names.add(name.lower())
                imported += 1
            except Exception as e:
                errors.append(f"Error importing '{name}': {e}")

        self._save()
        return {"imported": imported, "skipped": skipped, "errors": errors}

    # ------------------------------------------------------------------
    # MCP config generation
    # ------------------------------------------------------------------

    def generate_mcp_config(self, format: str = "claude", transport: str = "stdio") -> dict:
        """Generate MCP server configuration for AI clients.

        Args:
            format: Config format — "claude" or "generic".
            transport: Transport mode — "stdio" (default) or "sse".
                       SSE mode generates a URL-based config for remote access.
        """
        import sys
        bridge_path = str(Path(__file__).resolve().parent / "mcp_bridge.py")
        python_path = sys.executable

        if format == "claude":
            if transport == "sse":
                return {
                    "mcpServers": {
                        "selran-hub": {
                            "url": "http://127.0.0.1:8421/sse",
                        }
                    }
                }
            return {
                "mcpServers": {
                    "selran-hub": {
                        "command": python_path,
                        "args": [bridge_path],
                    }
                }
            }
        elif format == "generic":
            if transport == "sse":
                return {
                    "servers": [{
                        "name": "MCP Server",
                        "transport": "sse",
                        "url": "http://127.0.0.1:8421/sse",
                    }]
                }
            return {
                "servers": [{
                    "name": "MCP Server",
                    "transport": "stdio",
                    "command": f"{python_path} {bridge_path}",
                }]
            }
        return {"error": f"Unknown format: {format}"}

    def install_mcp_config(self, format: str = "claude") -> dict:
        """Write config to the standard location."""
        config = self.generate_mcp_config(format)

        if format == "claude":
            home = Path.home()
            config_path = home / ".claude" / "mcp-settings.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)

            existing = {}
            if config_path.exists():
                try:
                    existing = json.loads(config_path.read_text())
                except Exception:
                    pass

            existing.setdefault("mcpServers", {})
            existing["mcpServers"].update(config.get("mcpServers", {}))
            config_path.write_text(json.dumps(existing, indent=2))

            return {
                "installed": True,
                "path": str(config_path),
                "servers_added": len(config.get("mcpServers", {})),
            }

        return {"installed": False, "error": f"Install not supported for format: {format}"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

DEFAULT_DB = Path.home() / ".config" / "app-port-registry.sqlite3"  # portable; same location on every machine
LEGACY_JSON = Path.home() / ".config" / "app-ports.json"  # one-time migration source; portable
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 11999
RANGE_MIN = 12000
RANGE_MAX = 14000
BLOCK_SIZE = 5
APP_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PORT_KILL_GRACE_SECONDS = 1.5
PORT_KILL_FORCE_SECONDS = 0.75


class RegistryError(Exception):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def canonical_path(value: str) -> str:
    return str(Path(value).expanduser().resolve())


def block_is_aligned(start_port: int) -> bool:
    return (start_port - RANGE_MIN) % BLOCK_SIZE == 0


def ports_for_range(start_port: int, end_port: int) -> list[int]:
    return list(range(start_port, end_port + 1))


def default_registry_json() -> dict[str, Any]:
    return {
        "_description": "Port registry for all dev apps. Each app gets a 5-port range in 12000-14000. Managed by app-port-registry service.",
        "_format": "app-id -> { range: [start, end], path: absolute path, description: human label }",
        "_rules": [
            "Range 12000-14000 only. Each app gets exactly 5 consecutive ports.",
            "Within the 5 ports: first port = backend, second port = frontend, rest = reserved.",
            "To claim the next slot: use the first available 5-port block in range, reusing reclaimed blocks when present.",
            "Do not delete entries directly; archive through the registry service so it can reclaim the assigned ports safely.",
            "App-id must be lowercase-kebab-case.",
            "Do not edit the registry store directly; use app-port-registry on port 11999 or the CLI.",
        ],
        "apps": {},
        "next_available": RANGE_MIN,
    }


def validate_app_id(app_id: str) -> str:
    app_id = app_id.strip()
    if not APP_ID_RE.match(app_id):
        raise RegistryError(
            "app_id must be lowercase-kebab-case, for example 'mars-rover' or 'neutron-ui'"
        )
    return app_id


def connect_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=FULL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS apps (
          app_id TEXT PRIMARY KEY,
          start_port INTEGER NOT NULL UNIQUE,
          end_port INTEGER NOT NULL,
          path TEXT NOT NULL UNIQUE,
          description TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit (
          audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT NOT NULL,
          action TEXT NOT NULL,
          app_id TEXT,
          path TEXT,
          details_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS archived_apps (
          archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
          app_id TEXT NOT NULL,
          start_port INTEGER NOT NULL,
          end_port INTEGER NOT NULL,
          path TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          archived_at TEXT NOT NULL,
          archive_reason TEXT NOT NULL DEFAULT ''
        )
        """
    )
    cur = conn.execute("SELECT value FROM metadata WHERE key = 'next_available'")
    row = cur.fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO metadata (key, value) VALUES ('next_available', ?)",
            (str(RANGE_MIN),),
        )


def backup_legacy_json(path: Path) -> Path:
    target = path.with_name(f".{path.name}.legacy-{stamp()}.bak")
    shutil.move(str(path), str(target))
    return target


def import_legacy_json_if_needed(conn: sqlite3.Connection, db_path: Path) -> dict[str, Any] | None:
    cur = conn.execute("SELECT COUNT(*) AS count FROM apps")
    row = cur.fetchone()
    if row and int(row["count"]) > 0:
        return None
    if not LEGACY_JSON.exists():
        return None

    payload = json.loads(LEGACY_JSON.read_text(encoding="utf-8"))
    apps = payload.get("apps", {})
    next_available = int(payload.get("next_available", RANGE_MIN))
    if not isinstance(apps, dict):
        raise RegistryError("Legacy registry is invalid: apps must be an object")

    now = utc_now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for app_id, entry in apps.items():
            app_id = validate_app_id(app_id)
            if not isinstance(entry, dict):
                raise RegistryError(f"Legacy entry for {app_id} is invalid")
            rng = entry.get("range")
            if (
                not isinstance(rng, list)
                or len(rng) != 2
                or not all(isinstance(x, int) for x in rng)
            ):
                raise RegistryError(f"Legacy entry for {app_id} has invalid range")
            start_port, end_port = rng
            if end_port - start_port != BLOCK_SIZE - 1:
                raise RegistryError(f"Legacy entry for {app_id} does not use exactly 5 ports")
            path = canonical_path(str(entry.get("path", "")))
            description = str(entry.get("description", "")).strip()
            conn.execute(
                """
                INSERT INTO apps (app_id, start_port, end_port, path, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (app_id, start_port, end_port, path, description, now, now),
            )
        conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('next_available', ?)",
            (str(next_available),),
        )
        conn.execute(
            """
            INSERT INTO audit (created_at, action, app_id, path, details_json)
            VALUES (?, 'migrate-legacy-json', NULL, NULL, ?)
            """,
            (
                now,
                json.dumps(
                    {
                        "legacy_json": str(LEGACY_JSON),
                        "app_count": len(apps),
                        "next_available": next_available,
                    },
                    sort_keys=True,
                ),
            ),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    backup = backup_legacy_json(LEGACY_JSON)
    return {
        "legacy_json_backup": str(backup),
        "imported_app_count": len(apps),
        "next_available": next_available,
    }


class RegistryStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn = connect_db(db_path)
        ensure_schema(self._conn)
        self.migration_info = import_legacy_json_if_needed(self._conn, db_path)

    def _next_available(self) -> int:
        row = self._conn.execute(
            "SELECT value FROM metadata WHERE key = 'next_available'"
        ).fetchone()
        if row is None:
            raise RegistryError("Registry metadata is missing next_available")
        return int(row["value"])

    def _set_next_available(self, value: int) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('next_available', ?)",
            (str(value),),
        )

    def _compute_next_available(self) -> int:
        rows = self._conn.execute(
            "SELECT start_port, end_port FROM apps ORDER BY start_port ASC"
        ).fetchall()
        occupied_ports: set[int] = set()
        for row in rows:
            start = int(row["start_port"])
            end = int(row["end_port"])
            occupied_ports.update(range(start, end + 1))

        for start in range(RANGE_MIN, RANGE_MAX + 1, BLOCK_SIZE):
            end = start + BLOCK_SIZE - 1
            if end > RANGE_MAX:
                break
            if all(port not in occupied_ports for port in range(start, end + 1)):
                return start
        return RANGE_MAX + 1

    def _sync_next_available(self) -> int:
        next_available = self._compute_next_available()
        self._set_next_available(next_available)
        return next_available

    def _find_active_row(
        self,
        *,
        app_id: str | None = None,
        path: str | None = None,
    ) -> sqlite3.Row:
        if app_id:
            validated = validate_app_id(app_id)
            row = self._conn.execute(
                "SELECT * FROM apps WHERE app_id = ?", (validated,)
            ).fetchone()
            if row is not None:
                return row
        if path:
            normalized = canonical_path(path)
            row = self._conn.execute(
                "SELECT * FROM apps WHERE path = ?", (normalized,)
            ).fetchone()
            if row is not None:
                return row
        identity = app_id or (canonical_path(path) if path else "<unspecified>")
        raise RegistryError(f"No active registry entry found for: {identity}")

    def _find_latest_archived_row(
        self,
        *,
        app_id: str | None = None,
        path: str | None = None,
    ) -> sqlite3.Row | None:
        if app_id:
            validated = validate_app_id(app_id)
            row = self._conn.execute(
                """
                SELECT * FROM archived_apps
                WHERE app_id = ?
                ORDER BY archive_id DESC
                LIMIT 1
                """,
                (validated,),
            ).fetchone()
            if row is not None:
                return row
        if path:
            normalized = canonical_path(path)
            return self._conn.execute(
                """
                SELECT * FROM archived_apps
                WHERE path = ?
                ORDER BY archive_id DESC
                LIMIT 1
                """,
                (normalized,),
            ).fetchone()
        return None

    def _row_to_payload(self, row: sqlite3.Row, status: str) -> dict[str, Any]:
        start = int(row["start_port"])
        end = int(row["end_port"])
        payload = {
            "status": status,
            "app_id": row["app_id"],
            "path": row["path"],
            "description": row["description"],
            "range": [start, end],
            "backend_port": start,
            "frontend_port": start + 1,
            "reserved_ports": [start + 2, start + 3, start + 4],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if "archived_at" in row.keys():
            payload["archived_at"] = row["archived_at"]
            payload["archive_reason"] = row["archive_reason"]
        return payload

    def _insert_audit(
        self,
        *,
        action: str,
        app_id: str | None,
        path: str | None,
        details: dict[str, Any],
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO audit (created_at, action, app_id, path, details_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (utc_now(), action, app_id, path, json.dumps(details, sort_keys=True)),
        )

    def list_apps(self) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT * FROM apps ORDER BY start_port ASC"
        ).fetchall()
        return {
            "status": "listed",
            "next_available": self._compute_next_available(),
            "app_count": len(rows),
            "apps": [self._row_to_payload(row, status="listed") for row in rows],
        }

    def list_archived_apps(self) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT * FROM archived_apps ORDER BY archived_at DESC, archive_id DESC"
        ).fetchall()
        return {
            "status": "listed-archived",
            "next_available": self._compute_next_available(),
            "app_count": len(rows),
            "apps": [self._row_to_payload(row, status="listed-archived") for row in rows],
        }

    def get_app(self, app_id: str) -> dict[str, Any]:
        app_id = validate_app_id(app_id)
        row = self._conn.execute(
            "SELECT * FROM apps WHERE app_id = ?", (app_id,)
        ).fetchone()
        if row is None:
            raise RegistryError(f"Unknown app id: {app_id}")
        return self._row_to_payload(row, status="existing-app-id")

    def lookup_path(self, path: str) -> dict[str, Any]:
        normalized = canonical_path(path)
        row = self._conn.execute(
            "SELECT * FROM apps WHERE path = ?", (normalized,)
        ).fetchone()
        if row is None:
            raise RegistryError(f"No registry entry found for path: {normalized}")
        return self._row_to_payload(row, status="existing-path")

    def ensure_app(self, app_id: str, path: str, description: str = "") -> dict[str, Any]:
        app_id = validate_app_id(app_id)
        normalized = canonical_path(path)
        description = description.strip()
        now = utc_now()

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            existing_by_id = self._conn.execute(
                "SELECT * FROM apps WHERE app_id = ?", (app_id,)
            ).fetchone()
            if existing_by_id is not None:
                payload = self._row_to_payload(existing_by_id, status="existing-app-id")
                self._insert_audit(
                    action="ensure-existing-app-id",
                    app_id=app_id,
                    path=normalized,
                    details=payload,
                )
                self._conn.execute("COMMIT")
                return payload

            existing_by_path = self._conn.execute(
                "SELECT * FROM apps WHERE path = ?", (normalized,)
            ).fetchone()
            if existing_by_path is not None:
                payload = self._row_to_payload(existing_by_path, status="existing-path")
                self._insert_audit(
                    action="ensure-existing-path",
                    app_id=app_id,
                    path=normalized,
                    details=payload,
                )
                self._conn.execute("COMMIT")
                return payload

            start = self._compute_next_available()
            end = start + BLOCK_SIZE - 1
            if start < RANGE_MIN or end > RANGE_MAX:
                raise RegistryError("No free 5-port blocks remain in the allowed range")

            self._conn.execute(
                """
                INSERT INTO apps (app_id, start_port, end_port, path, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (app_id, start, end, normalized, description, now, now),
            )
            next_available = self._sync_next_available()
            row = self._conn.execute(
                "SELECT * FROM apps WHERE app_id = ?", (app_id,)
            ).fetchone()
            assert row is not None
            payload = self._row_to_payload(row, status="created")
            self._insert_audit(
                action="ensure-created",
                app_id=app_id,
                path=normalized,
                details=payload | {"next_available": next_available},
            )
            payload["next_available"] = next_available
            self._conn.execute("COMMIT")
            return payload
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def reclaim_ports(
        self,
        *,
        app_id: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        row = self._find_active_row(app_id=app_id, path=path)
        payload = self._row_to_payload(row, status="reclaimed")
        port_report = reclaim_listeners_for_ports(
            ports_for_range(payload["range"][0], payload["range"][1])
        )
        payload["port_reclaim"] = port_report
        self._insert_audit(
            action="reclaim-ports",
            app_id=payload["app_id"],
            path=payload["path"],
            details=payload,
        )
        return payload

    def archive_app(
        self,
        *,
        app_id: str | None = None,
        path: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        archive_reason = reason.strip()
        if not archive_reason:
            archive_reason = "archived-via-registry"

        try:
            self._find_active_row(app_id=app_id, path=path)
        except RegistryError:
            archived_row = self._find_latest_archived_row(app_id=app_id, path=path)
            if archived_row is not None:
                payload = self._row_to_payload(archived_row, status="already-archived")
                payload["next_available"] = self._compute_next_available()
                return payload
            raise

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._find_active_row(app_id=app_id, path=path)
            payload = self._row_to_payload(row, status="archived")
            archived_at = utc_now()
            port_report = reclaim_listeners_for_ports(
                ports_for_range(payload["range"][0], payload["range"][1])
            )
            self._conn.execute(
                """
                INSERT INTO archived_apps (
                  app_id,
                  start_port,
                  end_port,
                  path,
                  description,
                  created_at,
                  updated_at,
                  archived_at,
                  archive_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["app_id"],
                    row["start_port"],
                    row["end_port"],
                    row["path"],
                    row["description"],
                    row["created_at"],
                    row["updated_at"],
                    archived_at,
                    archive_reason,
                ),
            )
            self._conn.execute("DELETE FROM apps WHERE app_id = ?", (row["app_id"],))
            next_available = self._sync_next_available()
            payload["archived_at"] = archived_at
            payload["archive_reason"] = archive_reason
            payload["next_available"] = next_available
            payload["port_reclaim"] = port_report
            self._insert_audit(
                action="archive-app",
                app_id=payload["app_id"],
                path=payload["path"],
                details=payload,
            )
            self._conn.execute("COMMIT")
            return payload
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def validate(self) -> dict[str, Any]:
        rows = self._conn.execute("SELECT * FROM apps ORDER BY start_port ASC").fetchall()
        seen_paths: set[str] = set()
        previous_end: int | None = None
        for row in rows:
            app_id = row["app_id"]
            validate_app_id(app_id)
            start = int(row["start_port"])
            end = int(row["end_port"])
            if end - start != BLOCK_SIZE - 1:
                raise RegistryError(f"{app_id} does not use exactly 5 ports")
            if start < RANGE_MIN or end > RANGE_MAX:
                raise RegistryError(f"{app_id} is outside allowed port range")
            if not block_is_aligned(start):
                raise RegistryError(f"{app_id} does not start on a valid registry block boundary")
            if previous_end is not None and start <= previous_end:
                raise RegistryError(f"{app_id} overlaps a previously assigned port range")
            previous_end = end
            path = row["path"]
            if path in seen_paths:
                raise RegistryError(f"Duplicate path detected for {app_id}")
            seen_paths.add(path)

        archived_rows = self._conn.execute(
            "SELECT * FROM archived_apps ORDER BY archive_id ASC"
        ).fetchall()
        for row in archived_rows:
            start = int(row["start_port"])
            end = int(row["end_port"])
            if end - start != BLOCK_SIZE - 1:
                raise RegistryError(f"Archived {row['app_id']} does not use exactly 5 ports")
            if start < RANGE_MIN or end > RANGE_MAX:
                raise RegistryError(f"Archived {row['app_id']} is outside allowed port range")
            if not block_is_aligned(start):
                raise RegistryError(
                    f"Archived {row['app_id']} does not start on a valid registry block boundary"
                )

        next_available = self._compute_next_available()
        return {
            "status": "valid",
            "app_count": len(rows),
            "archived_app_count": len(archived_rows),
            "next_available": next_available,
            "migration_info": self.migration_info,
        }


def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_command(pid: int) -> str:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def listening_pids_for_port(port: int) -> list[int]:
    lsof_path = shutil.which("lsof")
    if not lsof_path:
        raise RegistryError("lsof is required for registry-managed port reclamation")
    result = subprocess.run(
        [lsof_path, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        stderr = result.stderr.strip() or "unknown lsof error"
        raise RegistryError(f"Could not inspect listeners on port {port}: {stderr}")
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pids.add(int(line))
        except ValueError:
            continue
    return sorted(pids)


def listeners_for_ports(ports: list[int]) -> dict[int, list[int]]:
    port_map: dict[int, list[int]] = {}
    for port in ports:
        pids = listening_pids_for_port(port)
        if pids:
            port_map[port] = pids
    return port_map


def wait_for_ports_to_clear(ports: list[int], timeout_seconds: float) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not listeners_for_ports(ports):
            return True
        time.sleep(0.1)
    return not listeners_for_ports(ports)


def reclaim_listeners_for_ports(ports: list[int]) -> dict[str, Any]:
    sorted_ports = sorted(int(port) for port in ports)
    phase_reports: list[dict[str, Any]] = []
    for sig, phase_name, timeout_seconds in (
        (signal.SIGTERM, "terminate", PORT_KILL_GRACE_SECONDS),
        (signal.SIGKILL, "kill", PORT_KILL_FORCE_SECONDS),
    ):
        port_map = listeners_for_ports(sorted_ports)
        if not port_map:
            break

        pid_reports: list[dict[str, Any]] = []
        all_pids = sorted({pid for pids in port_map.values() for pid in pids})
        for pid in all_pids:
            pid_ports = sorted(port for port, pids in port_map.items() if pid in pids)
            command = process_command(pid)
            try:
                os.kill(pid, sig)
                signal_name = signal.Signals(sig).name
            except ProcessLookupError:
                signal_name = "ALREADY_EXITED"
            pid_reports.append(
                {
                    "pid": pid,
                    "ports": pid_ports,
                    "signal": signal_name,
                    "command": command,
                }
            )
        phase_reports.append({"phase": phase_name, "processes": pid_reports})
        if wait_for_ports_to_clear(sorted_ports, timeout_seconds):
            break

    remaining = listeners_for_ports(sorted_ports)
    if remaining:
        remaining_report = {
            str(port): [
                {"pid": pid, "command": process_command(pid)}
                for pid in pids
                if pid_exists(pid)
            ]
            for port, pids in remaining.items()
        }
        raise RegistryError(
            f"Registry could not reclaim all requested ports: {json.dumps(remaining_report, sort_keys=True)}"
        )

    return {
        "ports": sorted_ports,
        "phases": phase_reports,
        "cleared": True,
    }


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


class RegistryHandler(BaseHTTPRequestHandler):
    server_version = "AppPortRegistry/1.1"

    @property
    def store(self) -> RegistryStore:
        return self.server.store  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RegistryError(f"Invalid JSON body: {exc}") from exc
        if not isinstance(data, dict):
            raise RegistryError("JSON body must be an object")
        return data

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                return json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "service": "app-port-registry",
                        "port": self.server.server_port,  # type: ignore[attr-defined]
                    },
                )
            if parsed.path == "/v1/report":
                return json_response(self, HTTPStatus.OK, self.store.list_apps())
            if parsed.path == "/v1/apps":
                return json_response(self, HTTPStatus.OK, self.store.list_apps())
            if parsed.path.startswith("/v1/apps/"):
                app_id = parsed.path.removeprefix("/v1/apps/")
                return json_response(self, HTTPStatus.OK, self.store.get_app(app_id))
            if parsed.path == "/v1/lookup":
                query = parse_qs(parsed.query)
                path = (query.get("path") or [""])[0]
                return json_response(self, HTTPStatus.OK, self.store.lookup_path(path))
            if parsed.path == "/v1/validate":
                return json_response(self, HTTPStatus.OK, self.store.validate())
            if parsed.path == "/v1/archived":
                return json_response(self, HTTPStatus.OK, self.store.list_archived_apps())
            return json_response(
                self,
                HTTPStatus.NOT_FOUND,
                {"status": "error", "message": f"Unknown route: {parsed.path}"},
            )
        except RegistryError as exc:
            return json_response(
                self,
                HTTPStatus.BAD_REQUEST,
                {"status": "error", "message": str(exc)},
            )

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            body = self._read_json()
            if parsed.path == "/v1/ensure":
                app_id = str(body.get("app_id", ""))
                path = str(body.get("path", ""))
                description = str(body.get("description", ""))
                payload = self.store.ensure_app(app_id, path, description)
                return json_response(self, HTTPStatus.OK, payload)
            if parsed.path == "/v1/reclaim":
                payload = self.store.reclaim_ports(
                    app_id=str(body.get("app_id", "") or "") or None,
                    path=str(body.get("path", "") or "") or None,
                )
                return json_response(self, HTTPStatus.OK, payload)
            if parsed.path == "/v1/archive":
                payload = self.store.archive_app(
                    app_id=str(body.get("app_id", "") or "") or None,
                    path=str(body.get("path", "") or "") or None,
                    reason=str(body.get("reason", "")),
                )
                return json_response(self, HTTPStatus.OK, payload)
            return json_response(
                self,
                HTTPStatus.NOT_FOUND,
                {"status": "error", "message": f"Unknown route: {parsed.path}"},
            )
        except RegistryError as exc:
            return json_response(
                self,
                HTTPStatus.BAD_REQUEST,
                {"status": "error", "message": str(exc)},
            )


def run_server(host: str, port: int, db_path: Path) -> int:
    store = RegistryStore(db_path)
    server = HTTPServer((host, port), RegistryHandler)
    server.store = store  # type: ignore[attr-defined]
    print(f"app-port-registry listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down app-port-registry")
    finally:
        server.server_close()
    return 0


def print_payload(payload: Any, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if isinstance(payload, dict) and "apps" in payload and isinstance(payload["apps"], list):
        print(f"next_available: {payload.get('next_available')}")
        for item in payload["apps"]:
            rng = item["range"]
            print(
                f"{item['app_id']}\t{rng[0]}-{rng[1]}\t{item['path']}\t{item.get('description', '')}"
            )
        return 0
    rng = payload["range"]
    print(f"status: {payload['status']}")
    print(f"app_id: {payload['app_id']}")
    print(f"path: {payload['path']}")
    print(f"description: {payload.get('description', '')}")
    print(f"range: {rng[0]}-{rng[1]}")
    print(f"backend_port: {payload['backend_port']}")
    print(f"frontend_port: {payload['frontend_port']}")
    print(f"reserved_ports: {','.join(str(p) for p in payload['reserved_ports'])}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    store = RegistryStore(args.db)
    return print_payload(store.list_apps(), args.json)


def cmd_get(args: argparse.Namespace) -> int:
    store = RegistryStore(args.db)
    return print_payload(store.get_app(args.app_id), args.json)


def cmd_lookup(args: argparse.Namespace) -> int:
    store = RegistryStore(args.db)
    return print_payload(store.lookup_path(args.path), args.json)


def cmd_ensure(args: argparse.Namespace) -> int:
    store = RegistryStore(args.db)
    return print_payload(store.ensure_app(args.app_id, args.path, args.description), args.json)


def cmd_validate(args: argparse.Namespace) -> int:
    store = RegistryStore(args.db)
    payload = store.validate()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"valid: apps={payload['app_count']} next_available={payload['next_available']}")
    return 0


def cmd_archived(args: argparse.Namespace) -> int:
    store = RegistryStore(args.db)
    return print_payload(store.list_archived_apps(), args.json)


def cmd_reclaim(args: argparse.Namespace) -> int:
    store = RegistryStore(args.db)
    return print_payload(store.reclaim_ports(app_id=args.app_id), args.json)


def cmd_archive(args: argparse.Namespace) -> int:
    store = RegistryStore(args.db)
    return print_payload(store.archive_app(app_id=args.app_id, reason=args.reason), args.json)


def cmd_serve(args: argparse.Namespace) -> int:
    return run_server(args.host, args.port, args.db)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app-port-registry",
        description="SQLite-backed single-writer registry CLI and localhost service.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help="Internal registry storage override",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output")

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List all registered apps")
    list_parser.add_argument("--json", action="store_true", help="Emit JSON output")
    list_parser.set_defaults(func=cmd_list)

    get_parser = subparsers.add_parser("get", help="Get a registered app by app_id")
    get_parser.add_argument("app_id")
    get_parser.add_argument("--json", action="store_true", help="Emit JSON output")
    get_parser.set_defaults(func=cmd_get)

    lookup_parser = subparsers.add_parser("lookup", help="Find a registered app by canonical path")
    lookup_parser.add_argument("path")
    lookup_parser.add_argument("--json", action="store_true", help="Emit JSON output")
    lookup_parser.set_defaults(func=cmd_lookup)

    ensure_parser = subparsers.add_parser(
        "ensure",
        aliases=["register"],
        help="Return existing assignment or create a new one safely",
    )
    ensure_parser.add_argument("app_id")
    ensure_parser.add_argument("path")
    ensure_parser.add_argument("--description", default="")
    ensure_parser.add_argument("--json", action="store_true", help="Emit JSON output")
    ensure_parser.set_defaults(func=cmd_ensure)

    validate_parser = subparsers.add_parser("validate", help="Validate registry structure")
    validate_parser.add_argument("--json", action="store_true", help="Emit JSON output")
    validate_parser.set_defaults(func=cmd_validate)

    archived_parser = subparsers.add_parser("archived", help="List archived registry entries")
    archived_parser.add_argument("--json", action="store_true", help="Emit JSON output")
    archived_parser.set_defaults(func=cmd_archived)

    reclaim_parser = subparsers.add_parser(
        "reclaim",
        help="Ask the registry to kill listeners on an app's assigned ports",
    )
    reclaim_parser.add_argument("app_id")
    reclaim_parser.add_argument("--json", action="store_true", help="Emit JSON output")
    reclaim_parser.set_defaults(func=cmd_reclaim)

    archive_parser = subparsers.add_parser(
        "archive",
        help="Archive an app entry and reclaim its assigned ports through the registry",
    )
    archive_parser.add_argument("app_id")
    archive_parser.add_argument("--reason", default="")
    archive_parser.add_argument("--json", action="store_true", help="Emit JSON output")
    archive_parser.set_defaults(func=cmd_archive)

    serve_parser = subparsers.add_parser("serve", help="Run localhost registry service")
    serve_parser.add_argument("--host", default=DEFAULT_HOST)
    serve_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve_parser.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

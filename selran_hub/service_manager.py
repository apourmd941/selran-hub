"""Selran Hub service lifecycle (spec §3.3, §6) — the app-startup brain as an API.

Hard rules carried over from the app-startup skill:
  - NEVER kill by port alone. Identity is verified before any signal: the
    process at the recorded PID must still match the command line captured
    at start time. A reused PID is never killed.
  - Processes are launched in their own session (process group) so a start
    script that spawns children (backend + frontend) is stopped as a group.

State is COMPUTED on read, never trusted from storage:
  registered  — known, never started (or unregistered runtime)
  running     — recorded PID alive and identity matches
  stopped     — stopped by the Hub (clean)
  failed      — runtime says we started it, but the process is gone without
                the Hub having stopped it
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import sqlite3
import subprocess
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import process_inspect as pi
from .port_registry_core import RegistryError, pid_exists, process_command

SERVICE_LOG_DIR = Path.home() / ".selran" / "hub" / "service-logs"

STOP_GRACE_SECONDS = 8.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_service_id(service_id: str) -> str:
    sid = (service_id or "").strip()
    if not sid or len(sid) > 64 or not all(c.isalnum() or c in "-_." for c in sid):
        raise RegistryError(
            "service id must be 1-64 chars of letters, digits, '-', '_', '.'"
        )
    return sid


class ServiceManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, timeout=30, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()
        # H0: clear stale runtime rows so a dead-but-recorded service no longer
        # masquerades. NEVER signals anything — pure bookkeeping.
        try:
            self.reconcile_on_startup()
        except Exception:
            pass

    def _ensure_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS hub_services (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                cwd TEXT NOT NULL,
                start_cmd TEXT NOT NULL,
                health_url TEXT NOT NULL DEFAULT '',
                registry_app_id TEXT NOT NULL DEFAULT '',
                env_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS hub_service_runtime (
                service_id TEXT PRIMARY KEY,
                pid INTEGER,
                pgid INTEGER,
                command_line TEXT NOT NULL DEFAULT '',
                started_at TEXT,
                stopped_by_hub INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            """
        )
        # H0 migration: add the reuse-proof anchor (create_time) and the launch
        # marker to existing runtime rows. Legacy rows get NULL create_time / ''
        # marker, which the stop path treats as 'cannot prove identity'.
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(hub_service_runtime)")}
        if "marker" not in cols:
            self._conn.execute(
                "ALTER TABLE hub_service_runtime ADD COLUMN marker TEXT NOT NULL DEFAULT ''"
            )
        if "create_time" not in cols:
            self._conn.execute(
                "ALTER TABLE hub_service_runtime ADD COLUMN create_time REAL"
            )

    # ----------------------------------------------------------- registration

    def register(
        self,
        service_id: str,
        cwd: str,
        start_cmd: str,
        name: str = "",
        health_url: str = "",
        registry_app_id: str = "",
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        sid = validate_service_id(service_id)
        if not start_cmd.strip():
            raise RegistryError("start_cmd is required")
        cwd_path = Path(cwd).expanduser()
        if not cwd_path.is_dir():
            raise RegistryError(f"cwd is not a directory: {cwd}")
        now = utc_now()
        self._conn.execute(
            """
            INSERT INTO hub_services (id, name, cwd, start_cmd, health_url,
                registry_app_id, env_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, cwd=excluded.cwd, start_cmd=excluded.start_cmd,
                health_url=excluded.health_url, registry_app_id=excluded.registry_app_id,
                env_json=excluded.env_json, updated_at=excluded.updated_at
            """,
            (
                sid, name or sid, str(cwd_path), start_cmd, health_url,
                registry_app_id, json.dumps(env or {}), now, now,
            ),
        )
        return self.describe(sid)

    def unregister(self, service_id: str) -> dict[str, Any]:
        sid = validate_service_id(service_id)
        desc = self.describe(sid)
        if desc["state"] == "running":
            raise RegistryError(f"service '{sid}' is running; stop it before unregistering")
        self._conn.execute("DELETE FROM hub_service_runtime WHERE service_id = ?", (sid,))
        self._conn.execute("DELETE FROM hub_services WHERE id = ?", (sid,))
        return {"status": "unregistered", "id": sid}

    # ----------------------------------------------------------- state

    def _row(self, service_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM hub_services WHERE id = ?", (service_id,)
        ).fetchone()
        if row is None:
            raise RegistryError(f"Unknown service: {service_id}")
        return row

    def _runtime(self, service_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM hub_service_runtime WHERE service_id = ?", (service_id,)
        ).fetchone()

    def _identity_alive(self, rt: sqlite3.Row | None) -> bool:
        if rt is None or not rt["pid"]:
            return False
        pid = int(rt["pid"])
        if not pid_exists(pid):
            return False
        current = process_command(pid)
        recorded = rt["command_line"]
        if not (recorded and current == recorded):
            return False
        # H0: if we recorded a start time, a live PID whose start time has moved
        # is a reused PID, not our service. (Tolerance here only widens the
        # "not alive" decision; the kill path requires an EXACT match.)
        rec_ct = self._rt_create_time(rt)
        if rec_ct is not None:
            ct = pi.proc_create_time(pid)
            if ct is not None and abs(ct - rec_ct) > 2.0:
                return False
        return True

    @staticmethod
    def _rt_create_time(rt: sqlite3.Row | None) -> float | None:
        if rt is None:
            return None
        try:
            val = rt["create_time"]
        except (IndexError, KeyError):
            return None
        return float(val) if val is not None else None

    def _state(self, rt: sqlite3.Row | None) -> str:
        if rt is None or rt["started_at"] is None:
            return "registered"
        if self._identity_alive(rt):
            return "running"
        if int(rt["stopped_by_hub"] or 0):
            return "stopped"
        return "failed"  # we started it; it's gone; we didn't stop it

    def describe(self, service_id: str) -> dict[str, Any]:
        sid = validate_service_id(service_id)
        row = self._row(sid)
        rt = self._runtime(sid)
        state = self._state(rt)
        out: dict[str, Any] = {
            "status": "ok",
            "id": row["id"],
            "name": row["name"],
            "cwd": row["cwd"],
            "start_cmd": row["start_cmd"],
            "health_url": row["health_url"] or None,
            "registry_app_id": row["registry_app_id"] or None,
            "state": state,
            "pid": int(rt["pid"]) if rt and rt["pid"] and state == "running" else None,
            "started_at": rt["started_at"] if rt else None,
            "note": rt["note"] if rt else "",
        }
        if state == "running" and row["health_url"]:
            out["health"] = self._probe_health(row["health_url"])
        return out

    def list_services(self) -> dict[str, Any]:
        rows = self._conn.execute("SELECT id FROM hub_services ORDER BY id").fetchall()
        services = [self.describe(r["id"]) for r in rows]
        return {"status": "ok", "service_count": len(services), "services": services}

    def summary(self) -> list[dict[str, Any]]:
        """Compact entries for /hub/health (spec §4.1)."""
        out = []
        for r in self._conn.execute("SELECT id FROM hub_services ORDER BY id").fetchall():
            d = self.describe(r["id"])
            out.append({"id": d["id"], "state": d["state"]})
        return out

    @staticmethod
    def _probe_health(url: str, timeout: float = 0.8) -> str:
        # Only probe http(s): a registered health_url must never make the Hub
        # open file:// (or another local scheme) during a health check.
        if not str(url).lower().startswith(("http://", "https://")):
            return "unreachable"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (scheme gated above)
                return "ok" if 200 <= resp.status < 300 else f"http-{resp.status}"
        except Exception:
            return "unreachable"

    # ----------------------------------------------------------- lifecycle

    def start(self, service_id: str) -> dict[str, Any]:
        sid = validate_service_id(service_id)
        row = self._row(sid)
        rt = self._runtime(sid)
        if self._state(rt) == "running":
            raise RegistryError(f"service '{sid}' is already running (pid {rt['pid']})")

        SERVICE_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = SERVICE_LOG_DIR / f"{sid}.log"
        # H0: stamp a per-launch marker into the child's environment. It is
        # inherited by every child/grandchild, so an orphan from a *previous*
        # launch is later provably ours (prefix == service id) — the strongest,
        # unforgeable OWNED signal. "<service_id>:<launch_uuid>".
        marker = f"{sid}:{uuid.uuid4().hex}"
        env = {**os.environ, **json.loads(row["env_json"] or "{}"), pi.MARKER_ENV: marker}
        log_file = open(log_path, "ab")
        try:
            # shell=True is intentional: this is a local process supervisor and a
            # start_cmd is a shell line the user registered (pipes, &&, env interp —
            # like systemd ExecStart / pm2). The trust boundary is REGISTRATION,
            # which the app.py CSRF/origin guard restricts to same-origin/local
            # callers — a remote web page cannot register or start a service.
            proc = subprocess.Popen(
                row["start_cmd"],
                shell=True,
                cwd=row["cwd"],
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # own process group → group stop
            )
        finally:
            log_file.close()
        # capture identity; give the shell a beat to exec the real command
        time.sleep(0.15)
        cmdline = process_command(proc.pid)
        create_time = pi.proc_create_time(proc.pid)
        now = utc_now()
        self._conn.execute(
            """
            INSERT INTO hub_service_runtime
                (service_id, pid, pgid, command_line, started_at, stopped_by_hub,
                 note, updated_at, marker, create_time)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
            ON CONFLICT(service_id) DO UPDATE SET
                pid=excluded.pid, pgid=excluded.pgid, command_line=excluded.command_line,
                started_at=excluded.started_at, stopped_by_hub=0,
                note=excluded.note, updated_at=excluded.updated_at,
                marker=excluded.marker, create_time=excluded.create_time
            """,
            (sid, proc.pid, os.getpgid(proc.pid), cmdline, now,
             f"started by hub (log: {log_path})", now, marker, create_time),
        )
        return self.describe(sid)

    def stop(self, service_id: str) -> dict[str, Any]:
        sid = validate_service_id(service_id)
        self._row(sid)
        rt = self._runtime(sid)
        state = self._state(rt)
        if state != "running":
            # idempotent stop, but record honesty about identity mismatches
            if rt is not None and rt["pid"] and pid_exists(int(rt["pid"])) and not self._identity_alive(rt):
                self._mark_stopped(sid, "PID reused by another process; refused to signal it")
                raise RegistryError(
                    f"service '{sid}': pid {rt['pid']} no longer matches the launched "
                    "command line — refusing to kill a reused PID. Marked stopped."
                )
            self._mark_stopped(sid, f"stop requested while {state}")
            return self.describe(sid)

        pid = int(rt["pid"])
        pgid = int(rt["pgid"] or pid)
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + STOP_GRACE_SECONDS
        while time.monotonic() < deadline:
            if not pid_exists(pid):
                break
            time.sleep(0.2)
        if pid_exists(pid) and self._identity_alive(rt):
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            time.sleep(0.2)
        self._mark_stopped(sid, "stopped by hub")
        return self.describe(sid)

    def restart(self, service_id: str) -> dict[str, Any]:
        sid = validate_service_id(service_id)
        rt = self._runtime(sid)
        if self._state(rt) == "running":
            self.stop(sid)
        return self.start(sid)

    def _mark_stopped(self, sid: str, note: str) -> None:
        self._conn.execute(
            """
            UPDATE hub_service_runtime
            SET stopped_by_hub = 1, note = ?, updated_at = ?
            WHERE service_id = ?
            """,
            (note, utc_now(), sid),
        )

    # ----------------------------------------------------------- H0: PID reaper

    def reconcile_on_startup(self) -> None:
        """Mark any recorded-but-no-longer-alive runtime row as stopped, so a
        stale row cannot masquerade as running or block a restart after a Hub
        crash. NEVER sends a signal — a still-alive orphan is left for the user
        to stop explicitly via stop_pid()."""
        rows = self._conn.execute(
            "SELECT * FROM hub_service_runtime "
            "WHERE started_at IS NOT NULL AND stopped_by_hub = 0"
        ).fetchall()
        for rt in rows:
            if not self._identity_alive(rt):
                self._mark_stopped(
                    rt["service_id"],
                    "reconciled at startup: process gone or identity changed",
                )

    def _runtime_rows_for(
        self, service_id: str | None = None, registry_app_id: str | None = None
    ) -> list[sqlite3.Row]:
        if service_id:
            rt = self._runtime(service_id)
            return [rt] if rt is not None else []
        if registry_app_id:
            return list(
                self._conn.execute(
                    "SELECT rt.* FROM hub_service_runtime rt "
                    "JOIN hub_services s ON s.id = rt.service_id "
                    "WHERE s.registry_app_id = ?",
                    (registry_app_id,),
                ).fetchall()
            )
        return []

    def scan_pids(
        self,
        ports: list[int],
        service_id: str | None = None,
        registry_app_id: str | None = None,
    ) -> dict[str, Any]:
        """Read-only: every PID associated with an app — Source A (listeners on
        its port range) ∪ Source B (the Hub's recorded launches: recorded pid,
        process-group members, command-line matches, and launch-marker matches).
        Each PID is classified owned / owned-unverified / ambiguous / foreign.
        Sends no signals."""
        ports = [int(p) for p in (ports or [])]
        rt_rows = self._runtime_rows_for(service_id=service_id, registry_app_id=registry_app_id)
        scan_sids = {rt["service_id"] for rt in rt_rows}
        expected_by_pid = {int(rt["pid"]): rt for rt in rt_rows if rt["pid"]}
        recorded_cmds = {rt["command_line"] for rt in rt_rows if rt["command_line"]}
        current_leaders = {int(rt["pid"]) for rt in rt_rows if self._identity_alive(rt)}

        # Source A — port listeners + free-vs-blind coverage.
        port_map, occupied_invisible, coverage = pi.listeners_with_coverage(ports)
        pid_ports: dict[int, list[int]] = {}
        for port, pids in port_map.items():
            for pid in pids:
                pid_ports.setdefault(int(pid), []).append(int(port))

        # Source B — Hub-recorded identity.
        candidates: set[int] = set(pid_ports) | set(expected_by_pid)
        for rt in rt_rows:
            if rt["pgid"]:
                for pid in pi.pids_in_group(int(rt["pgid"])):
                    candidates.add(int(pid))
        if recorded_cmds:
            for pid, cmd in pi.ps_command_map().items():
                # over-inclusive discovery; classification re-checks exactly
                if any(cmd == rc or cmd.startswith(rc) or rc.startswith(cmd) for rc in recorded_cmds):
                    candidates.add(int(pid))
        for pid in pi.pids_with_marker_prefix(scan_sids):
            candidates.add(int(pid))

        self_pids = pi.hub_self_pids()
        me = pi.current_user()
        out: list[dict[str, Any]] = []
        for pid in sorted(candidates):
            info = pi.proc_info(pid)
            if info is None:
                continue
            out.append(
                self._classify_pid(
                    pid, info, pid_ports.get(pid, []),
                    expected_by_pid, recorded_cmds, current_leaders,
                    scan_sids, self_pids, me,
                )
            )
        return {
            "status": "ok",
            "ports": ports,
            "coverage": coverage,
            "occupied_owner_not_visible": occupied_invisible,
            "stop_supported": pi.stop_supported(),
            "psutil": pi.HAVE_PSUTIL,
            "pid_count": len(out),
            "pids": out,
        }

    def _classify_pid(
        self, pid, info, ports, expected_by_pid, recorded_cmds,
        current_leaders, scan_sids, self_pids, me,
    ) -> dict[str, Any]:
        cmd = info.get("command") or ""
        owner = info.get("owner")
        ct = info.get("create_time")
        marker = info.get("marker")
        base: dict[str, Any] = {
            "pid": pid, "command": cmd, "owner": owner,
            "create_time": ct, "ports": sorted(ports),
            "marker_present": bool(marker),
        }

        def out(classification, offer_stop, stop_mode, role, *reasons):
            base.update({
                "classification": classification, "offer_stop": offer_stop,
                "stop_mode": stop_mode, "role": role, "reasons": list(reasons),
            })
            return base

        # Never-touch set — checked before anything else.
        if pid <= 1:
            return out("foreign", False, None, "system", "system / low pid")
        if pid in self_pids:
            return out("foreign", False, None, "self", "this is the Hub or one of its ancestors — never stopped")
        if owner and me and owner != me:
            return out("foreign", False, None, "unknown", f"owned by another user ({owner})")
        if info.get("access_denied"):
            return out("foreign", False, None, "unknown", "cannot read this process's identity (different owner or sandboxed)")

        is_ours_marker = bool(marker and scan_sids and marker.split(":", 1)[0] in scan_sids)
        cmd_match = bool(cmd and (cmd in recorded_cmds or
                                  (pid in expected_by_pid and cmd == expected_by_pid[pid]["command_line"])))
        if pid in current_leaders:
            role = "current"
        elif is_ours_marker or cmd_match or pid in expected_by_pid:
            role = "orphan"
        else:
            role = "unknown"

        if not pi.stop_supported():
            cls = "owned" if (is_ours_marker or cmd_match) else "ambiguous"
            return out(cls, False, None, role, "stopping is not supported on this platform in this release")
        if ct is None:
            return out("ambiguous", False, None, role, "cannot read start time — shown only, not stoppable")

        if is_ours_marker:
            # The Hub launched this for this service. Group-stop is safe only for
            # a recorded leader (its own process group); otherwise single PID.
            mode = "group" if pid in expected_by_pid else "single"
            return out("owned", True, mode, role, "verified: carries this Hub's launch marker")
        if owner == me and (cmd_match or ports):
            why = ("matches the app's recorded launch command" if cmd_match
                   else f"your process holding the app's port(s) {sorted(ports)}")
            return out("owned-unverified", True, "single", role,
                       "force-stop: the Hub did not verify it launched this — " + why)
        return out("ambiguous", False, None, role,
                   "on the app's ports but identity does not match a recorded launch — shown only")

    def stop_pid(
        self, pid: int, service_id: str | None = None,
        expected_command: str = "", expected_create_time: float | None = None,
        force: bool = False, ports: list[int] | None = None,
    ) -> dict[str, Any]:
        """Identity-gated single/group stop. Preserves 'NEVER kill by port
        alone; verify identity before any signal', adding a reuse-proof
        (pid, create_time, command) re-check immediately before EACH signal."""
        pid = int(pid)
        if not pi.stop_supported():
            raise RegistryError("stopping PIDs is not supported on this platform in this release")
        info = pi.proc_info(pid)
        if info is None:
            return {"status": "ok", "result": "already-gone", "pid": pid}

        self_pids = pi.hub_self_pids()
        me = pi.current_user()
        owner = info.get("owner")
        ct = info.get("create_time")
        cmd = info.get("command") or ""
        marker = info.get("marker")

        # Never-touch.
        if pid <= 1 or pid in self_pids:
            raise RegistryError("refusing to signal the Hub itself, an ancestor, or a system process")
        if owner and me and owner != me:
            raise RegistryError(f"refusing to signal a process owned by another user ({owner})")
        if ct is None:
            raise RegistryError("cannot read the process start time — refusing to signal (identity unprovable)")

        # PID-reuse guard: the live identity must EXACTLY match what the caller
        # saw (and below, again immediately before SIGKILL).
        if expected_create_time is not None and abs(float(ct) - float(expected_create_time)) > 0.001:
            raise RegistryError("process start time changed since you looked — refusing to signal a possibly reused PID")
        if expected_command and cmd != expected_command:
            raise RegistryError("process command changed since you looked — refusing to signal a possibly reused PID")

        rt_rows = self._runtime_rows_for(service_id=service_id) if service_id else []
        scan_sids = {service_id} if service_id else set()
        is_ours_marker = bool(marker and scan_sids and marker.split(":", 1)[0] in scan_sids)
        cmd_match = any(cmd == r["command_line"] for r in rt_rows) if rt_rows else False

        # Authorisation. Marker-verified → one-click. Otherwise require force,
        # owner==me, AND association (recorded command OR currently on the app's
        # ports) so this endpoint can never stop an arbitrary unrelated process.
        if not is_ours_marker:
            on_app_port = False
            if ports:
                pmap, _, _ = pi.listeners_with_coverage([int(p) for p in ports])
                on_app_port = any(pid in pids for pids in pmap.values())
            if not (cmd_match or on_app_port):
                raise RegistryError("this PID is not associated with the app (not on its ports, no command match) — refusing")
            if not force:
                raise RegistryError("unverified process — re-send with force=true to stop it explicitly")
            if owner and me and owner != me:  # redundant guard, kept explicit
                raise RegistryError("refusing: not owned by you")

        # Group stop ONLY for a marker-verified recorded leader, and never our
        # own group. Everything else is a single-PID signal (no blast radius).
        use_group = False
        target_pgid: int | None = None
        if is_ours_marker and pid in {int(r["pid"]) for r in rt_rows if r["pid"]}:
            try:
                live_pgid = os.getpgid(pid)
                if live_pgid != os.getpgid(0):
                    use_group, target_pgid = True, live_pgid
            except (ProcessLookupError, PermissionError):
                use_group = False

        def _send(sig) -> None:
            try:
                if use_group and target_pgid is not None:
                    os.killpg(target_pgid, sig)
                else:
                    os.kill(pid, sig)
            except ProcessLookupError:
                pass

        _send(signal.SIGTERM)
        deadline = time.monotonic() + STOP_GRACE_SECONDS
        while time.monotonic() < deadline:
            if pi.effectively_gone(pid):
                break
            time.sleep(0.2)

        if not pi.effectively_gone(pid):
            # Re-verify identity atomically before escalating — a PID recycled
            # during the grace window must NOT be SIGKILLed.
            again = pi.proc_info(pid)
            same = (
                again is not None
                and again.get("create_time") is not None
                and abs(float(again["create_time"]) - float(ct)) <= 0.001
                and (again.get("command") or "") == cmd
            )
            if same:
                _send(signal.SIGKILL)
                time.sleep(0.2)

        # Reap if it became one of our own children (else it lingers as a
        # zombie and reads as "still alive"). A non-child raises and is ignored.
        try:
            os.waitpid(pid, os.WNOHANG)
        except Exception:
            pass

        gone = pi.effectively_gone(pid)
        if service_id:
            rt = self._runtime(service_id)
            if rt is not None and rt["pid"] and int(rt["pid"]) == pid:
                self._mark_stopped(service_id, f"stopped pid {pid}" + (" (group)" if use_group else ""))
        return {
            "status": "ok",
            "result": "stopped" if gone else "signalled",
            "pid": pid,
            "mode": "group" if use_group else "single",
            "still_alive": (not gone),
        }

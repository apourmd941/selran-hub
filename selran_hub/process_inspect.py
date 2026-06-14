"""Cross-platform process & port inspection for the orphan-PID reaper (H0).

Safety-critical: this module's output authorizes a "stop this process" action,
so it is conservative by construction.

  * Identity is a reuse-proof tuple (pid, create_time, command_line) plus an
    optional Hub launch marker read from the target's environment. create_time
    is EXACT-match to authorize a kill; tolerance is used ONLY to refuse.
  * It distinguishes a port being FREE from the scanner being BLIND (unable to
    see a listener it lacks privilege for) and never reports "free" when it
    cannot prove it.
  * Anything whose identity cannot be read, or that is owned by another user or
    the system, is FOREIGN and is never stoppable.

psutil is the preferred engine (uniform create_time / environ / owner across
macOS, Linux, Windows). When it is absent the module still ENUMERATES via the
existing lsof / ps path for display, but a stop is refused (fail closed) because
the reuse-proof create_time anchor is unavailable.
"""

from __future__ import annotations

import errno
import getpass
import os
import platform
import shutil
import socket
import subprocess

from .port_registry_core import (
    RegistryError,
    listeners_for_ports,
    pid_exists,
    process_command,
)

# Marker stamped into every Hub-launched child's environment. Value is
# "<service_id>:<launch_uuid>" so an orphan from a *previous* launch of the same
# service is still recognisably ours (prefix match) even after a Hub restart.
MARKER_ENV = "SELRAN_HUB_INSTANCE"

IS_WINDOWS = platform.system() == "Windows"
IS_POSIX = os.name == "posix"

try:  # psutil is a declared dependency; guard so source-only runs still import.
    import psutil  # type: ignore

    HAVE_PSUTIL = True
except Exception:  # pragma: no cover - exercised only without the dep installed
    psutil = None  # type: ignore
    HAVE_PSUTIL = False


def current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        try:
            return str(os.getuid())  # type: ignore[attr-defined]
        except Exception:
            return ""


def stop_supported() -> bool:
    """Stopping is POSIX-only in this release (uses os.kill / os.killpg) and
    requires psutil for a reuse-proof create_time anchor. Windows enumeration is
    display-only; the routes hard-gate the stop path."""
    return IS_POSIX and HAVE_PSUTIL


# --------------------------------------------------------------------------- identity

def proc_create_time(pid: int) -> float | None:
    """Process start time as a float, or None if it cannot be read.

    None means 'identity unprovable' — callers must refuse to kill, never guess.
    """
    if HAVE_PSUTIL:
        try:
            return float(psutil.Process(pid).create_time())
        except Exception:
            return None
    return None


def _read_marker(p) -> str | None:
    try:
        return (p.environ() or {}).get(MARKER_ENV)
    except Exception:
        return None


def proc_info(pid: int) -> dict | None:
    """Best-effort identity snapshot for a live pid, or None if it is gone.

    Keys: pid, create_time (float|None), command (str), owner (str|None),
    marker (str|None), access_denied (bool). command is captured with the SAME
    extractor (ps -o command=) used when the launch was recorded, so equality
    comparisons are extractor-consistent.
    """
    pid = int(pid)
    if HAVE_PSUTIL:
        try:
            p = psutil.Process(pid)
            with p.oneshot():
                owner = None
                try:
                    owner = p.username()
                except Exception:
                    owner = None
                return {
                    "pid": pid,
                    "create_time": float(p.create_time()),
                    "command": process_command(pid),
                    "owner": owner,
                    "marker": _read_marker(p),
                    "access_denied": False,
                }
        except psutil.NoSuchProcess:  # type: ignore[union-attr]
            return None
        except psutil.AccessDenied:  # type: ignore[union-attr]
            # Exists but we cannot read its identity (foreign owner / sandboxed).
            # Surface it (so it is never silently dropped) but mark it unreadable.
            if not pid_exists(pid):
                return None
            return {
                "pid": pid,
                "create_time": None,
                "command": process_command(pid),
                "owner": None,
                "marker": None,
                "access_denied": True,
            }
        except Exception:
            return None
    # No psutil: enumerate for display only, never killable (no create_time).
    if not pid_exists(pid):
        return None
    return {
        "pid": pid,
        "create_time": None,
        "command": process_command(pid),
        "owner": _ps_owner(pid),
        "marker": None,
        "access_denied": False,
    }


def _ps_owner(pid: int) -> str | None:
    if not IS_POSIX:
        return None
    try:
        r = subprocess.run(
            ["ps", "-p", str(pid), "-o", "user="],
            capture_output=True, text=True, check=False,
        )
        return r.stdout.strip() or None
    except Exception:
        return None


def is_zombie(pid: int) -> bool:
    """A defunct process awaiting reap is effectively dead even though
    os.kill(pid, 0) still succeeds for it."""
    if not HAVE_PSUTIL:
        return False
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except Exception:
        return False


def effectively_gone(pid: int) -> bool:
    """True when the pid no longer exists OR is a zombie (defunct)."""
    return (not pid_exists(pid)) or is_zombie(pid)


def hub_self_pids() -> set[int]:
    """The Hub's own pid plus its ancestor chain — never to be signalled."""
    out: set[int] = set()
    try:
        out.add(os.getpid())
    except Exception:
        pass
    if HAVE_PSUTIL:
        try:
            for anc in psutil.Process(os.getpid()).parents():
                out.add(anc.pid)
        except Exception:
            pass
    return out


# --------------------------------------------------------------------------- sweeps

def ps_command_map() -> dict[int, str]:
    """One `ps` call → {pid: command}. Used only for over-inclusive candidate
    discovery; the authoritative comparison re-reads via process_command()."""
    if not IS_POSIX:
        return {}
    try:
        r = subprocess.run(
            ["ps", "-axww", "-o", "pid=,command="],
            capture_output=True, text=True, check=False,
        )
    except Exception:
        return {}
    out: dict[int, str] = {}
    for line in r.stdout.splitlines():
        s = line.strip()
        if not s:
            continue
        pid_str, _, cmd = s.partition(" ")
        try:
            out[int(pid_str)] = cmd.strip()
        except ValueError:
            continue
    return out


def pids_in_group(pgid: int) -> list[int]:
    """Live pids whose process group == pgid (recovers re-parented children)."""
    if not IS_POSIX:
        return []
    found: list[int] = []
    if HAVE_PSUTIL:
        for p in psutil.process_iter(["pid"]):
            pid = p.info["pid"]
            try:
                if os.getpgid(pid) == pgid:
                    found.append(pid)
            except (ProcessLookupError, PermissionError):
                continue
            except Exception:
                continue
    else:
        try:
            r = subprocess.run(
                ["ps", "-axo", "pid=,pgid="],
                capture_output=True, text=True, check=False,
            )
            for line in r.stdout.split("\n"):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        if int(parts[1]) == pgid:
                            found.append(int(parts[0]))
                    except ValueError:
                        continue
        except Exception:
            pass
    return found


def pids_with_marker_prefix(prefixes: set[str]) -> list[int]:
    """Live pids carrying a SELRAN_HUB_INSTANCE marker whose service-id prefix is
    in `prefixes` — i.e. processes this Hub launched for one of these services,
    including orphans from a previous launch (different launch uuid)."""
    if not (HAVE_PSUTIL and prefixes):
        return []
    found: list[int] = []
    for p in psutil.process_iter(["pid"]):
        try:
            env = p.environ()
        except Exception:
            continue
        m = (env or {}).get(MARKER_ENV)
        if m and m.split(":", 1)[0] in prefixes:
            found.append(p.info["pid"])
    return found


# --------------------------------------------------------------------------- ports

def port_is_occupied(port: int) -> bool | None:
    """True if 127.0.0.1:port is held, False if provably free, None if unknown.

    Binds WITHOUT SO_REUSEADDR so a TIME_WAIT or an existing listener yields
    EADDRINUSE rather than a false 'free'. This is what lets us tell a genuinely
    free port from one held by a process we lack privilege to see in lsof."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", int(port)))
        return False
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, errno.EACCES, errno.EADDRNOTAVAIL):
            return True
        return None
    finally:
        try:
            s.close()
        except Exception:
            pass


def listeners_with_coverage(ports: list[int]) -> tuple[dict[int, list[int]], list[int], str]:
    """Return (port_to_pids, occupied_owner_not_visible, coverage).

    coverage is 'complete' when every occupied port was attributable to a pid,
    or 'partial' when a port is occupied (proved via bind probe) but no pid was
    visible — the macOS-non-root / foreign-owner case. Callers must surface
    'partial' loudly and never imply 'all clear' from an empty pid list.
    """
    ports = [int(p) for p in (ports or [])]
    if not ports:
        return {}, [], "complete"
    port_map: dict[int, list[int]] = {}
    lsof_ok = shutil.which("lsof") is not None
    if lsof_ok:
        try:
            port_map = listeners_for_ports(ports)
        except RegistryError:
            lsof_ok = False
    occupied_invisible: list[int] = []
    for port in ports:
        if port in port_map:
            continue
        if port_is_occupied(port) is True:
            occupied_invisible.append(port)
    coverage = "partial" if (occupied_invisible or not lsof_ok) else "complete"
    return port_map, sorted(occupied_invisible), coverage

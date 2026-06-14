"""selran-hub CLI (spec §5.4) — serve, status, logs, and per-OS autostart.

P2 distribution surface: after `pipx install`, `selran-hub serve` runs the
daemon and `selran-hub autostart install` makes it start on login —
LaunchAgent on macOS, systemd user unit on Linux, Scheduled Task on Windows.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

DEFAULT_PORT = 11999
LABEL = "com.selran.hub"
LOG_PATH = Path.home() / ".selran" / "hub" / "hub.log"


def _hub_exe() -> list[str]:
    """The command autostart should run: the console script if on PATH,
    else `<this python> -m selran_hub`."""
    exe = shutil.which("selran-hub")
    if exe:
        return [exe, "serve"]
    return [sys.executable, "-m", "selran_hub", "serve"]


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    port = args.port or int(os.environ.get("SELRAN_HUB_PORT", DEFAULT_PORT))
    uvicorn.run("selran_hub.app:app", host="127.0.0.1", port=port, log_level="info")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    port = args.port or int(os.environ.get("SELRAN_HUB_PORT", DEFAULT_PORT))
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/hub/health", timeout=2) as r:
            body = json.load(r)
        print(f"Selran Hub {body.get('version')} — running on 127.0.0.1:{port}")
        print(f"capabilities: {', '.join(body.get('capabilities', []))}")
        services = body.get("services", [])
        if services:
            for s in services:
                print(f"  service {s['id']}: {s['state']}")
        return 0
    except Exception:
        print(f"Selran Hub is NOT running on 127.0.0.1:{port}")
        return 1


def cmd_logs(args: argparse.Namespace) -> int:
    candidates = [LOG_PATH, Path.home() / "Library" / "Logs" / "selran-hub.log"]
    try:
        from .config import get_log_file  # the app's own structured log
        candidates.append(get_log_file())
    except Exception:
        pass
    for p in candidates:
        if p.exists():
            subprocess.run(["tail", "-n", str(args.lines), str(p)] if os.name != "nt"
                           else ["powershell", "-Command", f"Get-Content -Tail {args.lines} '{p}'"])
            return 0
    print(f"no log file found (looked at: {', '.join(str(c) for c in candidates)})")
    return 1


# ----------------------------------------------------------------- autostart

def _autostart_install() -> int:
    system = platform.system()
    cmd = _hub_exe()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    if system == "Darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        args_xml = "\n".join(f"    <string>{c}</string>" for c in cmd)
        plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
{args_xml}
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{LOG_PATH}</string>
  <key>StandardErrorPath</key><string>{LOG_PATH}</string>
</dict>
</plist>
""")
        uid = os.getuid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
        r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"launchctl bootstrap failed: {r.stderr.strip()}")
            return 1
        print(f"installed LaunchAgent {LABEL} (starts on login, running now)")
        return 0

    if system == "Linux":
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit = unit_dir / "selran-hub.service"
        unit.write_text(f"""[Unit]
Description=Selran Hub — local runtime for the Selran ecosystem

[Service]
ExecStart={" ".join(cmd)}
Restart=on-failure
StandardOutput=append:{LOG_PATH}
StandardError=append:{LOG_PATH}

[Install]
WantedBy=default.target
""")
        for c in (["systemctl", "--user", "daemon-reload"],
                  ["systemctl", "--user", "enable", "--now", "selran-hub.service"]):
            r = subprocess.run(c, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"{' '.join(c)} failed: {r.stderr.strip()}")
                return 1
        print("installed systemd user unit selran-hub.service (starts on login, running now)")
        return 0

    if system == "Windows":
        task_cmd = " ".join(f'"{c}"' for c in cmd)
        r = subprocess.run(
            ["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", "SelranHub", "/TR", task_cmd],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"schtasks failed: {r.stderr.strip()}")
            return 1
        subprocess.run(["schtasks", "/Run", "/TN", "SelranHub"], capture_output=True)
        print("installed Scheduled Task 'SelranHub' (starts on logon, started now)")
        return 0

    print(f"unsupported platform: {system}")
    return 1


def _autostart_remove() -> int:
    system = platform.system()
    if system == "Darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
        if plist.exists():
            plist.unlink()
        print(f"removed LaunchAgent {LABEL}")
        return 0
    if system == "Linux":
        subprocess.run(["systemctl", "--user", "disable", "--now", "selran-hub.service"], capture_output=True)
        unit = Path.home() / ".config" / "systemd" / "user" / "selran-hub.service"
        if unit.exists():
            unit.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        print("removed systemd user unit selran-hub.service")
        return 0
    if system == "Windows":
        subprocess.run(["schtasks", "/End", "/TN", "SelranHub"], capture_output=True)
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", "SelranHub"], capture_output=True)
        print("removed Scheduled Task 'SelranHub'")
        return 0
    print(f"unsupported platform: {system}")
    return 1


def cmd_autostart(args: argparse.Namespace) -> int:
    return _autostart_install() if args.action == "install" else _autostart_remove()


def cmd_mcp(args: argparse.Namespace) -> int:
    """Run the MCP stdio bridge (what the Claude Code plugin launches)."""
    import sys

    from . import mcp_bridge

    # The bridge owns its own argparse; clear our subcommand from argv so it
    # parses clean defaults (stdio transport against the local daemon).
    sys.argv = [sys.argv[0]]
    mcp_bridge.main()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="selran-hub", description="Selran Hub — local runtime for the Selran ecosystem")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("serve", help="run the Hub daemon (foreground)")
    sp.add_argument("--port", type=int, default=None, help=f"port (default {DEFAULT_PORT} or $SELRAN_HUB_PORT)")
    sp.set_defaults(fn=cmd_serve)

    sp = sub.add_parser("status", help="check whether the Hub is running")
    sp.add_argument("--port", type=int, default=None)
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("logs", help="show recent Hub log lines")
    sp.add_argument("-n", "--lines", type=int, default=50)
    sp.set_defaults(fn=cmd_logs)

    sp = sub.add_parser("tray", help="run the menu-bar app (macOS)")
    sp.add_argument("--port", type=int, default=None)
    sp.set_defaults(fn=lambda a: __import__("selran_hub.tray", fromlist=["run_tray"]).run_tray(
        a.port or int(os.environ.get("SELRAN_HUB_PORT", DEFAULT_PORT))))

    sp = sub.add_parser("autostart", help="install or remove start-on-login")
    sp.add_argument("action", choices=["install", "remove"])
    sp.set_defaults(fn=cmd_autostart)

    sp = sub.add_parser("mcp", help="run the MCP stdio bridge (for AI clients / the Claude Code plugin)")
    sp.set_defaults(fn=cmd_mcp)

    sp = sub.add_parser("update-check", help="check GitHub for a newer Hub release")
    sp.set_defaults(fn=cmd_update_check)

    args = p.parse_args(argv)
    return args.fn(args)


def cmd_update_check(args) -> int:
    """Explicit user action → always checks (ignores the opt-in gate)."""
    from . import updater
    r = updater.check(force=True)
    if r.get("disabled_by_policy"):
        print("Update checks are disabled by org policy (managed-policy.json).")
        return 0
    if r.get("error"):
        print(f"Could not check for updates: {r['error']}")
        return 1
    if r.get("update_available"):
        print(f"Update available: {r['latest_tag']} (you have {r['current']})")
        if r.get("html_url"):
            print(f"  {r['html_url']}")
    else:
        print(f"You're up to date (Selran Hub {r['current']}; latest release {r.get('latest_tag') or '?'}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

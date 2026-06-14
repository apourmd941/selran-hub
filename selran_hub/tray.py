"""Selran Hub tray app (spec §9.3 — P3): the menu-bar face of the Hub.

Behavior:
  - On launch, probe 127.0.0.1:<port>/hub/health. If a Hub is already
    running (LaunchAgent, CLI, another tray), attach as a monitor — never
    start a second daemon on the same port.
  - Otherwise, run the daemon in-process (uvicorn in a background thread).
  - Menu: live status line, Open Dashboard / Services / Packs, Quit.

macOS-first (rumps). On other platforms `selran-hub tray` explains and
falls back to `serve`.
"""

from __future__ import annotations

import json
import os
import platform
import threading
import urllib.request
import webbrowser

DEFAULT_PORT = int(os.environ.get("SELRAN_HUB_PORT", "11999"))


def _probe(port: int) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/hub/health", timeout=0.5) as r:
            return json.load(r)
    except Exception:
        return None


def _start_inprocess(port: int) -> None:
    import uvicorn

    config = uvicorn.Config("selran_hub.app:app", host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, name="selran-hub-server", daemon=True)
    t.start()


def run_tray(port: int = DEFAULT_PORT) -> int:
    if platform.system() != "Darwin":
        print("The tray UI ships for macOS first; on this platform run: selran-hub serve")
        return 1

    import rumps

    owns_server = _probe(port) is None
    if owns_server:
        _start_inprocess(port)

    class HubTray(rumps.App):
        def __init__(self) -> None:
            super().__init__("⬢", quit_button=None)
            self.status_item = rumps.MenuItem("starting…")
            self.menu = [
                self.status_item,
                None,
                rumps.MenuItem("Open Dashboard", callback=self._open("/")),
                rumps.MenuItem("Open Services", callback=self._open("/hub/panel")),
                rumps.MenuItem("Open Packs", callback=self._open("/hub/packs")),
                None,
                rumps.MenuItem("Quit Selran Hub", callback=self._quit),
            ]

        @staticmethod
        def _open(path: str):
            def cb(_):
                webbrowser.open(f"http://127.0.0.1:{port}{path}")
            return cb

        def _quit(self, _) -> None:
            rumps.quit_application()

        @rumps.timer(4)
        def refresh(self, _) -> None:
            health = _probe(port)
            if health:
                services = health.get("services", [])
                running = sum(1 for s in services if s.get("state") == "running")
                suffix = f" · {running}/{len(services)} services" if services else ""
                self.status_item.title = f"● running — v{health.get('version', '?')} on :{port}{suffix}"
                self.title = "⬢"
            else:
                self.status_item.title = f"○ not responding on :{port}"
                self.title = "⬡"

    HubTray().run()
    return 0

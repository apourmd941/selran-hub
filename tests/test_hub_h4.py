"""H4 tests — event push (SessionStart hook + background monitor).

The scripts live under scripts/ (not a package); we load them by path. We test
the PURE transition/summary logic — the part that decides what (if anything) the
user is told. Whether Claude Code actually fires the hook / runs the monitor in
a live session is a platform behavior that can't be exercised headlessly.
"""

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load(name):
    path = REPO / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"selran_h4_{name}", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


watch = _load("hub_watch")
sctx = _load("hub_session_context")


# ----------------------------------------------------------- monitor: diff_events

def test_first_poll_is_a_silent_baseline():
    assert watch.diff_events(None, {"s": {"state": "running", "name": "s"}}, True, True) == []


def test_no_events_when_nothing_changes():
    state = {"s": {"state": "running", "name": "Svc"}}
    assert watch.diff_events(state, state, True, True) == []


def test_service_crash_emits_one_line():
    prev = {"s": {"state": "running", "name": "Svc"}}
    new = {"s": {"state": "failed", "name": "Svc"}}
    events = watch.diff_events(prev, new, True, True)
    assert len(events) == 1 and "Svc" in events[0] and "down" in events[0].lower()


def test_failed_state_not_re_announced():
    failed = {"s": {"state": "failed", "name": "Svc"}}
    assert watch.diff_events(failed, failed, True, True) == []  # already failed → quiet


def test_intentional_stop_is_not_a_crash_alert():
    prev = {"s": {"state": "running", "name": "Svc"}}
    new = {"s": {"state": "stopped", "name": "Svc"}}
    assert watch.diff_events(prev, new, True, True) == []  # only "failed" is the down signal


def test_hub_unreachable_then_back():
    down = watch.diff_events({}, {}, True, False)
    assert len(down) == 1 and "unreachable" in down[0].lower()
    up = watch.diff_events({}, {}, False, True)
    assert any("reachable again" in e.lower() for e in up)


# ----------------------------------------------------------- hook: build_context

def test_context_silent_when_hub_absent():
    assert sctx.build_context(None, None) is None
    assert sctx.build_context({"hub": "something-else"}, {}) is None


def test_context_summarizes_services_and_flags_failures():
    health = {"hub": "selran"}
    services = {"services": [
        {"id": "a", "name": "API", "state": "running"},
        {"id": "b", "name": "Worker", "state": "failed"},
    ]}
    ctx = sctx.build_context(health, services)
    assert ctx and "Selran Hub is running" in ctx
    assert "Worker" in ctx and "1 failed" in ctx


def test_context_handles_no_services():
    ctx = sctx.build_context({"hub": "selran"}, {"services": []})
    assert ctx and "no services registered" in ctx


# ----------------------------------------------------------- plugin component files

def test_plugin_component_files_are_valid_json():
    hooks = json.loads((REPO / "hooks" / "hooks.json").read_text())
    assert "SessionStart" in hooks["hooks"]
    assert "CLAUDE_PLUGIN_ROOT" in json.dumps(hooks)  # references bundled script
    monitors = json.loads((REPO / "monitors" / "monitors.json").read_text())
    assert isinstance(monitors, list) and monitors[0]["name"] == "selran-hub-watch"
    assert monitors[0]["when"] == "always"

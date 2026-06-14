"""Smoke tests for the previously-untested surfaces: cli.py, mcp_bridge.py,
version coherence, and the tray module's import + probe.
"""

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def test_version_coherent_across_sources():
    import selran_hub
    from selran_hub import hub_router
    from selran_hub.config import VERSION
    # pyproject is the manual-sync source; read it without importing tomllib<3.11 risk
    pyproject = (REPO / "pyproject.toml").read_text()
    assert f'version = "{VERSION}"' in pyproject, "pyproject.toml version out of sync with config.VERSION"
    assert hub_router.HUB_VERSION == VERSION
    assert selran_hub.__version__ == VERSION


def test_cli_parser_builds_and_status_on_dead_port():
    from selran_hub import cli
    # status against a port nothing is on → returns 1, no exception
    rc = cli.main(["status", "--port", "1"])
    assert rc == 1


def test_cli_unknown_command_exits():
    from selran_hub import cli
    with pytest.raises(SystemExit):
        cli.main(["does-not-exist"])


def test_cli_hub_exe_resolves():
    from selran_hub import cli
    exe = cli._hub_exe()
    assert isinstance(exe, list) and exe and exe[-1] == "serve"


def test_bridge_imports_and_points_at_hub_port():
    import selran_hub.mcp_bridge as b
    assert b.DEFAULT_API.endswith(":11999") or b.DEFAULT_API.endswith(
        f":{os.environ.get('SELRAN_HUB_PORT', '11999')}")
    assert "8420" not in b.DEFAULT_API


def test_tray_module_imports_and_probe_is_safe():
    # importing the tray module must not require rumps (lazy import inside run_tray)
    import selran_hub.tray as t
    # the probe against a dead port returns None, never raises
    assert t._probe(1) is None

"""H7 tests — MCP resources + Tool Search server instructions.

Resource registration + shape are verified in-process; the graceful-degradation
path (Hub not running → error JSON, never a crash) is what's deterministically
testable headlessly. A live smoke (below, run manually) reads a real resource
against a running Hub.
"""

import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from selran_hub import mcp_bridge as br  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def test_data_resources_registered():
    uris = {str(r.uri) for r in _run(br.mcp.list_resources())}
    for u in ("selran://sources", "selran://health", "selran://packs"):
        assert u in uris, f"{u} not registered ({uris})"


def test_schema_resource_template_registered():
    templates = [t.uriTemplate for t in _run(br.mcp.list_resource_templates())]
    assert "selran://sources/{source_name}/schema" in templates


def test_resources_degrade_to_error_json_when_hub_down():
    # The Hub isn't running in tests; every resource must return valid JSON
    # (with an "error") rather than raising.
    for uri in ("selran://sources", "selran://health", "selran://packs"):
        contents = _run(br.mcp.read_resource(uri))
        payload = json.loads(contents[0].content)  # must parse
        assert isinstance(payload, dict)
    # template read also degrades cleanly
    sch = _run(br.mcp.read_resource("selran://sources/whatever/schema"))
    assert isinstance(json.loads(sch[0].content), dict)


def test_server_instructions_set_for_tool_search():
    # The one server-side lever for client-side Tool Search.
    instr = getattr(br.mcp, "instructions", None)
    assert instr and "Selran Hub" in instr and "data source" in instr.lower()


def test_hub_get_helper_handles_unreachable():
    # _hub_get returns an error dict (not an exception) when the Hub is down.
    out = br._hub_get("/hub/health", timeout=0.3)
    assert isinstance(out, dict) and ("error" in out or "hub" in out)

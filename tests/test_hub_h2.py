"""H2 shape tests — MCP Apps (SEP-1865) UI surface on the stdio bridge.

These verify the WIRE SHAPE the bridge emits — the only thing testable without a
live MCP-Apps-capable client (the iframe rendering itself can't be exercised
headlessly, and Claude does not render MCP Apps yet; see mcp_bridge.py).

Checked:
  * the ui:// resources are registered at mimeType text/html;profile=mcp-app;
  * resources/read returns self-contained HTML carrying the SEP-1865 bridge
    (ui/initialize handshake, tool-result listener, ui/message send) and no
    external network dependency (CSP-clean);
  * the UI tools carry the load-bearing linkage _meta.ui.resourceUri on their
    definition;
  * the tools return a complete structured + instructional fallback so the model
    can act even when the UI is not rendered.
"""

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from selran_hub import mcp_bridge as br  # noqa: E402

UI_MIME = "text/html;profile=mcp-app"


def _run(coro):
    return asyncio.run(coro)


def _call(name, args):
    """FastMCP call_tool returns (content, structuredContent) for structured
    tools. Normalise to (content_list, structured_dict)."""
    out = _run(br.mcp.call_tool(name, args))
    if isinstance(out, tuple):
        return out[0], out[1]
    return out, None


def test_ui_resources_registered_with_mcp_app_mime():
    resources = _run(br.mcp.list_resources())
    by_uri = {str(r.uri): r for r in resources}
    for uri in (br.PICKER_URI, br.SOURCES_URI):
        assert uri in by_uri, f"{uri} not registered ({list(by_uri)})"
        assert by_uri[uri].mimeType == UI_MIME


def test_picker_html_is_self_contained_and_speaks_sep1865():
    contents = _run(br.mcp.read_resource(br.PICKER_URI))
    blob = contents[0]
    assert blob.mime_type == UI_MIME
    html = blob.content
    # SEP-1865 bridge markers
    assert "ui/initialize" in html
    assert "ui/notifications/tool-result" in html
    assert "ui/message" in html
    # self-contained: no external script/style/network (CSP default is strict)
    assert "http://" not in html and "https://" not in html
    assert "<script" in html and "fetch(" not in html


def test_ui_tools_declare_resource_uri_meta():
    tools = {t.name: t for t in _run(br.mcp.list_tools())}
    assert tools["design_picker"].meta == {"ui": {"resourceUri": br.PICKER_URI}}
    assert tools["data_sources_panel"].meta == {"ui": {"resourceUri": br.SOURCES_URI}}


def test_design_picker_returns_structured_fallback():
    content, structured = _call("design_picker", {"project": "Acme"})
    assert structured is not None, "structuredContent must be emitted for the UI"
    assert structured["project"] == "Acme"
    assert len(structured["directions"]) == 7
    assert all({"id", "name", "feel", "accent"} <= set(d) for d in structured["directions"])
    assert "instructions" in structured  # graceful fallback for non-rendering clients
    assert content  # a model-readable content block is always present


def test_bridge_loads_standalone_like_the_mcpb_bundle():
    # The .mcpb (H3) loads mcp_bridge.py as a standalone module via importlib,
    # not as a package import. With `from __future__ import annotations`, the
    # nested Pydantic models' forward refs must resolve in that context or the
    # @tool(structured_output=True) decoration raises. Guards that regression.
    import importlib.util
    path = REPO / "selran_hub" / "mcp_bridge.py"
    spec = importlib.util.spec_from_file_location("selran_hub_mcp_bridge_probe", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)  # must NOT raise InvalidSignature/PydanticUserError
        assert mod.PickerData.__pydantic_complete__ is True
        assert mod.SourcesData.__pydantic_complete__ is True
    finally:
        sys.modules.pop(spec.name, None)


def test_sources_panel_degrades_when_hub_down():
    # The Hub isn't running in tests; the tool must not crash and must return a
    # usable structured fallback rather than erroring.
    content, structured = _call("data_sources_panel", {})
    assert structured is not None
    assert "sources" in structured and isinstance(structured["sources"], list)
    assert "instructions" in structured

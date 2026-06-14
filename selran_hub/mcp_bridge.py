"""
MCP Bridge — MCP server that proxies tool calls to the
running MCP Server dashboard API.

Supports TWO transport modes:
  • stdio  — Claude launches this process and communicates via stdin/stdout.
             Best for local setups (default).
  • sse    — The bridge runs as an HTTP server and streams responses via
             Server-Sent Events. Best for remote / network access.

Usage:
    python mcp_bridge.py                          # stdio (default)
    python mcp_bridge.py --transport sse          # SSE on port 8421
    python mcp_bridge.py --transport sse --port 9000
    python mcp_bridge.py --api http://127.0.0.1:11999  # explicit Hub URL
"""

from __future__ import annotations

import argparse
import hmac
import json
import sys
from typing import Any, Optional

import httpx
from pydantic import BaseModel
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

import os as _os
# The Hub serves on 127.0.0.1:11999 (override with SELRAN_HUB_PORT). This was
# :8420 in the standalone MCP-server-app; the bridge proxies to the Hub now.
DEFAULT_API = f"http://127.0.0.1:{_os.environ.get('SELRAN_HUB_PORT', '11999')}"
DEFAULT_SSE_PORT = 8421  # the bridge's OWN SSE transport port (not the Hub)

# `instructions` is the one server-side lever for Claude Code's client-side Tool
# Search (which defers MCP tool schemas until needed): it tells Claude WHEN to
# pull these tools in, so the deferred bridge tools surface at the right moment.
mcp = FastMCP(
    "Selran Hub MCP Bridge",
    instructions=(
        "Use these tools to work with the user's LOCAL data through the Selran "
        "Hub (a private daemon on 127.0.0.1): list and inspect connected data "
        "sources (folders, DuckDB/SQLite databases, REST APIs), read table "
        "schemas, preview rows, and run read-only SQL. Reach for them whenever "
        "the user asks about their own files/databases/APIs, 'my data', a local "
        "dataset, or wants to query/preview/describe a source. Read-only and "
        "local-first. Read-only context (the source list, a source's schema, "
        "Hub health, the design-pack catalog) is also exposed as selran:// MCP "
        "resources you can attach."
    ),
)

_api_base: str = DEFAULT_API


def _hub_get(path: str, timeout: float = 10.0):
    """GET a Hub path OUTSIDE the /api namespace (e.g. /hub/health, /v1/packs).
    Returns parsed JSON, or {'error': ...} when the Hub is unreachable."""
    url = f"{_api_base}{path}"
    try:
        with httpx.Client(timeout=timeout, proxy=None) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        return {"error": "Selran Hub is not running. Start it with: selran-hub serve"}
    except Exception as e:
        return {"error": str(e)}


def _api(path: str, method: str = "GET", params: dict = None, body: dict = None) -> dict:
    """Call the dashboard API."""
    url = f"{_api_base}/api{path}"
    try:
        # proxy=None ensures direct connection to localhost
        with httpx.Client(timeout=30, proxy=None) as client:
            if method == "GET":
                resp = client.get(url, params=params)
            elif method == "POST":
                resp = client.post(url, json=body, params=params)
            else:
                resp = client.request(method, url, json=body, params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        return {"error": "Selran Hub is not running. Start it with: selran-hub serve"}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# MCP Tools — Source Management
# ---------------------------------------------------------------------------

@mcp.tool()
def list_sources() -> str:
    """List all registered data sources with their status (online/offline/error),
    type (folder, duckdb, sqlite, api), and configuration."""
    result = _api("/sources")
    if isinstance(result, dict) and "error" in result:
        return result["error"]
    if not result:
        return "No data sources registered. Add sources at http://127.0.0.1:11999"
    lines = []
    for s in result:
        status_icon = {"online": "●", "offline": "○", "error": "✗"}.get(s["status"], "?")
        lines.append(
            f"  {status_icon} {s['name']} ({s['type']}) — {s.get('path') or s.get('url') or 'no path'} [{s['status']}]"
        )
    return f"Data sources ({len(result)}):\n" + "\n".join(lines)


@mcp.tool()
def source_info(source_name: str) -> str:
    """Get detailed info about a specific data source by name or ID.
    Shows stats, rules, and connection status."""
    sources = _api("/sources")
    if isinstance(sources, dict) and "error" in sources:
        return sources["error"]
    # Find by name (case-insensitive) or ID
    match = None
    for s in sources:
        if s["name"].lower() == source_name.lower() or s["id"] == source_name:
            match = s
            break
    if not match:
        names = [s["name"] for s in sources]
        return f"Source '{source_name}' not found. Available: {', '.join(names)}"
    return json.dumps(match, indent=2, default=str)


# ---------------------------------------------------------------------------
# MCP Tools — Data Exploration
# ---------------------------------------------------------------------------

@mcp.tool()
def list_tables(source_name: str) -> str:
    """List all tables or files available in a data source.
    Shows table names, row counts, column counts, and sizes."""
    source_id = _resolve_source_id(source_name)
    if source_id.startswith("error:"):
        return source_id
    result = _api(f"/sources/{source_id}/tables")
    if isinstance(result, dict) and "error" in result:
        return result["error"]
    tables = result.get("tables", [])
    if not tables:
        return f"No tables found in '{source_name}'"
    lines = []
    for t in tables:
        info_parts = []
        if t.get("row_count") is not None:
            info_parts.append(f"{t['row_count']:,} rows")
        if t.get("column_count") is not None:
            info_parts.append(f"{t['column_count']} cols")
        if t.get("size_mb") is not None:
            info_parts.append(f"{t['size_mb']} MB")
        if t.get("type"):
            info_parts.append(t["type"])
        info = " · ".join(info_parts)
        lines.append(f"  • {t['name']}" + (f" ({info})" if info else ""))
    return f"Tables in '{source_name}' ({len(tables)}):\n" + "\n".join(lines)


@mcp.tool()
def preview_data(source_name: str, table_name: str, limit: int = 20) -> str:
    """Preview rows from a table or file in a data source.
    Returns column names and sample data rows."""
    source_id = _resolve_source_id(source_name)
    if source_id.startswith("error:"):
        return source_id
    result = _api(f"/sources/{source_id}/preview/{table_name}", params={"limit": limit})
    if isinstance(result, dict) and "error" in result:
        return result.get("error", "Unknown error")
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    total = result.get("total_rows", len(rows))
    if not columns:
        return "No data returned"
    # Format as a readable table
    header = " | ".join(str(c) for c in columns)
    separator = "-" * min(len(header), 120)
    lines = [f"Preview of '{table_name}' ({len(rows)} of {total:,} rows):", "", header, separator]
    for row in rows[:limit]:
        lines.append(" | ".join(str(cell) if cell is not None else "null" for cell in row))
    return "\n".join(lines)


@mcp.tool()
def table_schema(source_name: str, table_name: str) -> str:
    """Get the column schema (names and types) for a table.
    Useful before writing queries."""
    source_id = _resolve_source_id(source_name)
    if source_id.startswith("error:"):
        return source_id
    result = _api(f"/sources/{source_id}/tables")
    if isinstance(result, dict) and "error" in result:
        return result["error"]
    tables = result.get("tables", [])
    for t in tables:
        if t["name"].lower() == table_name.lower():
            if "columns" in t and isinstance(t["columns"], list) and t["columns"] and isinstance(t["columns"][0], dict):
                lines = [f"Schema for '{table_name}':"]
                for col in t["columns"]:
                    lines.append(f"  • {col['name']}: {col.get('type', 'unknown')}")
                return "\n".join(lines)
            return json.dumps(t, indent=2, default=str)
    return f"Table '{table_name}' not found in '{source_name}'"


# ---------------------------------------------------------------------------
# MCP Tools — Query & Analyze
# ---------------------------------------------------------------------------

@mcp.tool()
def query_source(source_name: str, sql: str, limit: int = 1000) -> str:
    """Execute a read-only SQL query against a data source.

    For folder sources, files become tables by their filename (without extension).
    E.g. 'patients.csv' is queryable as 'patients'.
    For DuckDB/SQLite sources, use the actual table names.

    Use list_tables first to see available table names, then table_schema
    to see columns before writing your query."""
    source_id = _resolve_source_id(source_name)
    if source_id.startswith("error:"):
        return source_id
    result = _api(f"/sources/{source_id}/query", method="POST", body={"sql": sql, "limit": limit})
    if isinstance(result, dict) and "error" in result and "columns" not in result:
        return f"Query error: {result['error']}"
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    if not columns:
        return "Query returned no results"
    header = " | ".join(str(c) for c in columns)
    separator = "-" * min(len(header), 120)
    lines = [f"Query result ({result.get('row_count', len(rows))} rows" +
             (" — truncated" if result.get("truncated") else "") + "):", "", header, separator]
    for row in rows:
        lines.append(" | ".join(str(cell) if cell is not None else "null" for cell in row))
    if result.get("available_tables"):
        lines.append(f"\nAvailable tables: {', '.join(result['available_tables'])}")
    return "\n".join(lines)


@mcp.tool()
def describe_source(source_name: str, table_name: str) -> str:
    """Get descriptive statistics for a table — min, max, mean, std dev
    for numeric columns; unique counts for text columns; null counts for all."""
    source_id = _resolve_source_id(source_name)
    if source_id.startswith("error:"):
        return source_id
    result = _api(f"/sources/{source_id}/describe/{table_name}")
    if isinstance(result, dict) and "error" in result and "columns" not in result:
        return f"Error: {result['error']}"
    lines = [f"Statistics for '{result.get('table', table_name)}' ({result.get('total_rows', '?'):,} rows):", ""]
    for col in result.get("columns", []):
        parts = [f"  {col['column']} ({col.get('type', '?')})"]
        if "mean" in col and col["mean"] is not None:
            parts.append(f"    min={col.get('min')}  max={col.get('max')}  mean={col.get('mean')}  std={col.get('std')}")
        if "unique_values" in col:
            parts.append(f"    unique={col['unique_values']}")
        parts.append(f"    non_null={col.get('non_null', '?')}  nulls={col.get('null_count', '?')}")
        lines.extend(parts)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Tools — Dashboard
# ---------------------------------------------------------------------------

@mcp.tool()
def dashboard_stats() -> str:
    """Get a summary of all data sources — total count, how many
    are online, offline, or have errors."""
    result = _api("/stats")
    if isinstance(result, dict) and "error" in result:
        return result["error"]
    return (
        f"MCP Server Dashboard:\n"
        f"  Total sources: {result.get('total', 0)}\n"
        f"  Online: {result.get('online', 0)}\n"
        f"  Offline: {result.get('offline', 0)}\n"
        f"  Errors: {result.get('error', 0)}"
    )


@mcp.tool()
def check_source(source_name: str) -> str:
    """Run a health check on a data source. Returns current status
    and any error details."""
    source_id = _resolve_source_id(source_name)
    if source_id.startswith("error:"):
        return source_id
    result = _api(f"/sources/{source_id}/check", method="POST")
    if isinstance(result, dict) and "error" in result and "status" not in result:
        return result["error"]
    return f"Source '{source_name}': {result.get('status', 'unknown')}" + (
        f" — {result['error']}" if result.get("error") else ""
    )


# ---------------------------------------------------------------------------
# MCP Apps (SEP-1865) — interactive UI surfaced INLINE in the chat (H2)
# ---------------------------------------------------------------------------
#
# SEP-1865 ("MCP Apps", Final 2026-01-26): a tool declares an interactive UI via
# `_meta.ui.resourceUri` pointing at a pre-declared `ui://` resource served at
# mimeType `text/html;profile=mcp-app`. A compatible host renders the HTML in a
# sandboxed iframe and bridges it over JSON-RPC-on-postMessage. The data flows in
# via a `ui/notifications/tool-result` notification (we put it in the tool's
# structuredContent); the user's choice flows back via a `ui/message` request.
#
# HONESTY NOTE: as of mid-2026 this renders in Goose / VS Code / ChatGPT, but
# Claude Desktop & claude.ai negotiate the capability yet do NOT instantiate the
# iframe (open upstream bugs: modelcontextprotocol/ext-apps#671,
# anthropics/claude-ai-mcp#165), and Claude Code is not a listed host. So every
# tool here ALSO returns a complete text/structured fallback the model can act
# on, and each UI degrades to a "use the options above" note when not rendered.
# This is forward-looking groundwork that lights up the day Claude ships the fix.

UI_MIME = "text/html;profile=mcp-app"
PICKER_URI = "ui://selran/design-picker"
SOURCES_URI = "ui://selran/data-sources"

# The seven pre-baked Design Director directions (kept in sync with the skill's
# starter set). The picker is fully self-contained — it needs no network.
DESIGN_DIRECTIONS = [
    {"id": "technical-minimal", "name": "Technical Minimal", "feel": "precise, restrained, engineer-trusted", "accent": "#2F6FED"},
    {"id": "editorial", "name": "Editorial", "feel": "magazine typography, generous whitespace", "accent": "#111111"},
    {"id": "warm-approachable", "name": "Warm & Approachable", "feel": "friendly, rounded, human", "accent": "#E2725B"},
    {"id": "dark-premium", "name": "Dark Premium", "feel": "high-contrast, cinematic, luxe", "accent": "#C8A24B"},
    {"id": "brutalist", "name": "Brutalist", "feel": "raw, bold, unapologetic", "accent": "#FF4D00"},
    {"id": "vibrant-playful", "name": "Vibrant & Playful", "feel": "energetic color, motion-forward", "accent": "#7C3AED"},
    {"id": "calm-clinical", "name": "Calm Clinical", "feel": "clean, trustworthy, healthcare-grade", "accent": "#0EA5A4"},
]

# Shared SEP-1865 host bridge: JSON-RPC over window.parent.postMessage, with a
# graceful standalone fallback when there is no host (opened as a bare page).
_BRIDGE_JS = r"""
  var HOST = (window.parent && window.parent !== window) ? window.parent : null;
  var _id = 0;
  function send(method, params){ if(HOST) HOST.postMessage({jsonrpc:"2.0", id:++_id, method:method, params:params||{}}, "*"); }
  function notify(method, params){ if(HOST) HOST.postMessage({jsonrpc:"2.0", method:method, params:params||{}}, "*"); }
  function sizeChanged(){ try{ notify("ui/notifications/size-changed", {height: document.documentElement.scrollHeight}); }catch(e){} }
  function sendChoice(text){ send("ui/message", {message: text}); }
  window.addEventListener("message", function(ev){
    var m = ev.data || {};
    if(m.method === "ui/notifications/tool-result" || m.method === "ui/notifications/tool-input"){
      try { onData((m.params && (m.params.structuredContent || m.params.arguments)) || {}); } catch(e){}
    }
  });
  // Announce readiness (SEP-1865 handshake). Harmless when there is no host.
  send("ui/initialize", {protocolVersion:"2025-06-18", clientInfo:{name:"selran-hub-ui", version:"1"}, appCapabilities:{}});
  if(!HOST){ var n=document.getElementById("standalone"); if(n) n.style.display="block"; }
"""

_BASE_CSS = r"""
  :root{--bg:#0f1115;--fg:#e8e8ec;--muted:#9aa0aa;--card:#171a21;--line:#262a33}
  @media (prefers-color-scheme: light){:root{--bg:#fbfbfa;--fg:#16181c;--muted:#5b616b;--card:#fff;--line:#e6e6e1}}
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:16px}
  h1{font-size:16px;margin:0 0 2px} .sub{color:var(--muted);font-size:12.5px;margin:0 0 14px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 13px;cursor:pointer;transition:border-color .12s,transform .12s}
  .card:hover,.card:focus-visible{border-color:var(--accent,#2F6FED);transform:translateY(-1px);outline:none}
  .dot{width:12px;height:12px;border-radius:50%;display:inline-block;vertical-align:middle;margin-right:7px}
  .name{font-weight:650} .feel{color:var(--muted);font-size:12px;margin-top:3px}
  table{width:100%;border-collapse:collapse} th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);font-size:12.5px}
  th{color:var(--muted);font-weight:600;text-transform:uppercase;font-size:10.5px;letter-spacing:.05em}
  .pill{font-size:11px;padding:1px 8px;border-radius:10px;border:1px solid var(--line)}
  #standalone{display:none;margin-top:14px;padding:9px 11px;border:1px dashed var(--line);border-radius:8px;color:var(--muted);font-size:12px}
"""

_PICKER_TEMPLATE = (
    "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
    "<title>Pick a design direction</title><style>" + _BASE_CSS + "</style></head><body>"
    "<h1>How should it feel?</h1><p class=\"sub\" id=\"sub\">Tap a direction — your choice goes straight back to the chat.</p>"
    "<div class=\"grid\" id=\"grid\"></div>"
    "<div id=\"standalone\">This view renders inside an MCP-Apps host. Otherwise, tell the assistant the direction you want by name.</div>"
    "<script>\n"
    "var DEFAULT = __DIRECTIONS__;\n"
    "var PROJECT = \"your project\";\n"
    "function esc(s){var d=document.createElement('div');d.textContent=(s==null?'':String(s));return d.innerHTML;}\n"
    "function render(dirs){\n"
    "  var g=document.getElementById('grid'); g.innerHTML='';\n"
    "  (dirs||DEFAULT).forEach(function(d){\n"
    "    var el=document.createElement('div'); el.className='card'; el.tabIndex=0;\n"
    "    el.style.setProperty('--accent', d.accent||'#2F6FED');\n"
    "    el.innerHTML='<div><span class=\"dot\" style=\"background:'+esc(d.accent||'#2F6FED')+'\"></span>'\n"
    "      +'<span class=\"name\">'+esc(d.name)+'</span></div><div class=\"feel\">'+esc(d.feel||'')+'</div>';\n"
    "    function pick(){ sendChoice('Use the “'+(d.name)+'” design direction for '+PROJECT+'.'); el.style.borderColor=d.accent||'#2F6FED'; document.getElementById('sub').textContent='Sent: '+d.name+'. You can close this.'; }\n"
    "    el.addEventListener('click', pick);\n"
    "    el.addEventListener('keydown', function(e){ if(e.key==='Enter'||e.key===' ') { e.preventDefault(); pick(); } });\n"
    "    g.appendChild(el);\n"
    "  });\n"
    "  sizeChanged();\n"
    "}\n"
    "function onData(data){ if(data && data.project) PROJECT=data.project; render(data && data.directions); }\n"
    "render(DEFAULT);\n"
    + _BRIDGE_JS +
    "\n</script></body></html>"
)

_SOURCES_TEMPLATE = (
    "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
    "<title>Your data sources</title><style>" + _BASE_CSS + "</style></head><body>"
    "<h1>Connected data sources</h1><p class=\"sub\" id=\"sub\">Tap a source to ask the assistant about it.</p>"
    "<table><thead><tr><th>Source</th><th>Type</th><th>Status</th><th>Location</th></tr></thead><tbody id=\"rows\"></tbody></table>"
    "<div id=\"standalone\">This view renders inside an MCP-Apps host. Otherwise, ask the assistant to list your sources.</div>"
    "<script>\n"
    "function esc(s){var d=document.createElement('div');d.textContent=(s==null?'':String(s));return d.innerHTML;}\n"
    "function render(srcs){\n"
    "  var tb=document.getElementById('rows'); tb.innerHTML='';\n"
    "  if(!srcs || !srcs.length){ tb.innerHTML='<tr><td colspan=\"4\" style=\"color:var(--muted)\">No sources yet — add one in the Hub dashboard.</td></tr>'; sizeChanged(); return; }\n"
    "  srcs.forEach(function(s){\n"
    "    var tr=document.createElement('tr'); tr.style.cursor='pointer';\n"
    "    tr.innerHTML='<td>'+esc(s.name)+'</td><td>'+esc(s.type)+'</td><td><span class=\"pill\">'+esc(s.status||'?')+'</span></td><td style=\"color:var(--muted)\">'+esc(s.location||'')+'</td>';\n"
    "    tr.addEventListener('click', function(){ sendChoice('Tell me about the “'+(s.name)+'” data source.'); });\n"
    "    tb.appendChild(tr);\n"
    "  });\n"
    "  sizeChanged();\n"
    "}\n"
    "function onData(data){ render(data && data.sources); }\n"
    "render([]);\n"
    + _BRIDGE_JS +
    "\n</script></body></html>"
)

_PICKER_HTML = _PICKER_TEMPLATE.replace("__DIRECTIONS__", json.dumps(DESIGN_DIRECTIONS))
_SOURCES_HTML = _SOURCES_TEMPLATE


# Typed tool outputs → a real outputSchema + structuredContent (which the UI
# reads from the ui/notifications/tool-result push) AND a JSON text fallback.
class Direction(BaseModel):
    id: str
    name: str
    feel: str
    accent: str


class PickerData(BaseModel):
    project: str
    directions: list[Direction]
    instructions: str


class SourceRow(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    location: str = ""


class SourcesData(BaseModel):
    sources: list[SourceRow]
    instructions: str
    hub_error: Optional[str] = None


# `from __future__ import annotations` (top of file) defers annotation eval, so
# the nested-model forward refs are resolved lazily against this module's
# globals. Rebuild eagerly so the models also work when this file is loaded as a
# STANDALONE module (e.g. inside the .mcpb bundle), not only as a package import.
PickerData.model_rebuild()
SourcesData.model_rebuild()


@mcp.resource(PICKER_URI, mime_type=UI_MIME, name="Selran design-direction picker",
              description="Interactive design-direction picker (MCP Apps / SEP-1865).")
def _picker_resource() -> str:
    return _PICKER_HTML


@mcp.resource(SOURCES_URI, mime_type=UI_MIME, name="Selran data-sources panel",
              description="Interactive table of connected data sources (MCP Apps / SEP-1865).")
def _sources_resource() -> str:
    return _SOURCES_HTML


@mcp.tool(meta={"ui": {"resourceUri": PICKER_URI}}, structured_output=True)
def design_picker(project: str = "your project") -> PickerData:
    """Open an interactive design-direction picker for a visual project. In an
    MCP-Apps-capable client the seven directions render as clickable cards and
    the user's pick is sent straight back to the chat. If the client does not
    render MCP Apps, present the returned directions and ask the user to choose
    one by name."""
    return PickerData(
        project=project,
        directions=DESIGN_DIRECTIONS,
        instructions=(
            "If the interactive picker did not render, list these design "
            "directions to the user and ask them to choose one by name or number."
        ),
    )


@mcp.tool(meta={"ui": {"resourceUri": SOURCES_URI}}, structured_output=True)
def data_sources_panel() -> SourcesData:
    """Show the Hub's connected data sources as an interactive panel. In an
    MCP-Apps-capable client they render as a clickable table; otherwise present
    the returned list. Reflects the live Hub state (empty/unavailable if the Hub
    is not running)."""
    result = _api("/sources")
    if isinstance(result, dict) and "error" in result:
        return SourcesData(
            sources=[], hub_error=result["error"],
            instructions="The Hub is not reachable. Tell the user to start it with: selran-hub serve",
        )
    rows = [
        SourceRow(name=s.get("name"), type=s.get("type"), status=s.get("status"),
                  location=s.get("path") or s.get("url") or "")
        for s in (result or [])
    ]
    return SourcesData(
        sources=rows,
        instructions="If the interactive panel did not render, list these sources for the user.",
    )


# ---------------------------------------------------------------------------
# MCP Resources (H7) — read-only Hub context the client can list / @-mention.
# Resources are application-driven (the user attaches them); they complement the
# model-driven tools above. Audit runs are ephemeral (per-run) so they are not
# exposed as a resource.
# ---------------------------------------------------------------------------

@mcp.resource("selran://sources", name="Connected data sources", mime_type="application/json",
              description="Data sources registered with the Selran Hub (name, type, status, location).")
def res_sources() -> str:
    data = _api("/sources")
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    out = [
        {"id": s.get("id"), "name": s.get("name"), "type": s.get("type"),
         "status": s.get("status"), "location": s.get("path") or s.get("url") or ""}
        for s in (data or [])
    ]
    return json.dumps({"sources": out, "count": len(out)}, indent=2)


@mcp.resource("selran://sources/{source_name}/schema", name="Data source schema",
              mime_type="application/json",
              description="Tables and columns for one data source — attach before writing a query.")
def res_source_schema(source_name: str) -> str:
    sid = _resolve_source_id(source_name)
    if sid.startswith("error:"):
        return json.dumps({"error": sid[len("error:"):].strip()}, indent=2)
    data = _api(f"/sources/{sid}/tables")
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({"source": source_name, "tables": data.get("tables", [])}, indent=2, default=str)


@mcp.resource("selran://health", name="Selran Hub health", mime_type="application/json",
              description="Hub version, capabilities, and a summary of registered services.")
def res_health() -> str:
    return json.dumps(_hub_get("/hub/health"), indent=2, default=str)


@mcp.resource("selran://packs", name="Design pack catalog", mime_type="application/json",
              description="The Design Director design-pack catalog the Hub knows about.")
def res_packs() -> str:
    return json.dumps(_hub_get("/v1/packs"), indent=2, default=str)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_source_id(source_name: str) -> str:
    """Resolve a source name to its ID."""
    sources = _api("/sources")
    if isinstance(sources, dict) and "error" in sources:
        return f"error: {sources['error']}"
    for s in sources:
        if s["name"].lower() == source_name.lower() or s["id"] == source_name:
            return s["id"]
    names = [s["name"] for s in sources]
    return f"error: Source '{source_name}' not found. Available: {', '.join(names)}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Remote transport security (H8) — Streamable HTTP / SSE for remote Claude
# clients, with a bearer-token gate that is MANDATORY off loopback.
# ---------------------------------------------------------------------------

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _is_loopback(host: str) -> bool:
    return (host or "").strip().lower() in LOOPBACK_HOSTS


def _bridge_token() -> str:
    # From the environment only — never a CLI arg (argv leaks via `ps`).
    return _os.environ.get("SELRAN_HUB_BRIDGE_TOKEN", "").strip()


def resolve_http_security(host: str, token: str) -> bool:
    """Enforce that a non-loopback bind REQUIRES a token; returns whether the
    auth gate is enabled. Raises ValueError (caller exits) on an unauthenticated
    network bind — mirrors the daemon's §2.2 'never expose without explicit
    acknowledgement' rule, where the acknowledgement is configuring a secret."""
    forbid_remote = False
    try:  # a managed policy (H9) can forbid remote transport outright
        from . import policy as _policy
        forbid_remote = not _policy.allow_remote_transport()
    except Exception:
        forbid_remote = False
    if forbid_remote and not _is_loopback(host):
        raise ValueError(
            "org policy (managed-policy.json) forbids remote transport — bind a loopback host only."
        )
    if not _is_loopback(host) and not token:
        raise ValueError(
            "refusing to bind the bridge to a non-loopback host without auth — "
            "set SELRAN_HUB_BRIDGE_TOKEN to a secret before exposing it on a network."
        )
    return bool(token)


class BearerAuthMiddleware:
    """Pure-ASGI bearer-token gate for the bridge's HTTP transports. Wrapped
    around the MCP app whenever a token is configured.

    Deny-by-default: only 'lifespan' (server lifecycle, not a network request)
    passes unauthenticated; 'http' requires a valid bearer; any other scope
    (e.g. a future 'websocket') is rejected. Compares raw BYTES with a
    constant-time check (decoding to str would crash on a non-ASCII byte)."""

    def __init__(self, app, token: str):
        self.app = app
        self.token = token.encode("utf-8")

    async def __call__(self, scope, receive, send):
        stype = scope.get("type")
        if stype == "lifespan":
            return await self.app(scope, receive, send)
        if stype != "http":
            return await self._reject(scope, send)
        provided = b""
        for k, v in scope.get("headers") or []:
            if k == b"authorization":
                if v[:7].lower() == b"bearer ":
                    provided = v[7:].strip()
                break
        if provided and hmac.compare_digest(provided, self.token):
            return await self.app(scope, receive, send)
        await self._reject(scope, send)

    async def _reject(self, scope, send):
        if scope.get("type") == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"application/json"),
                        (b"www-authenticate", b'Bearer realm="selran-hub"')],
        })
        await send({
            "type": "http.response.body",
            "body": b'{"error":"unauthorized: send Authorization: Bearer <SELRAN_HUB_BRIDGE_TOKEN>"}',
        })


def _run_http(transport: str, host: str, port: int) -> None:
    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings
    token = _bridge_token()
    try:
        auth_on = resolve_http_security(host, token)
    except ValueError as exc:
        print(f"\n  ✗ {exc}\n", file=sys.stderr)
        raise SystemExit(2)
    mcp.settings.host = host
    mcp.settings.port = port
    if not _is_loopback(host):
        # FastMCP's DNS-rebinding allowlist is frozen to localhost at import, so
        # a real off-loopback client would get 421 Invalid Host. The bearer token
        # is the control here (a rebinding browser has no token → 401), so turn
        # the host allowlist off for the network bind.
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )
    if transport == "streamable-http":
        app = mcp.streamable_http_app()
        path = mcp.settings.streamable_http_path
        label = "Streamable HTTP"
    else:
        app = mcp.sse_app()
        path = mcp.settings.sse_path
        label = "SSE (legacy — prefer streamable-http)"
    if auth_on:
        app = BearerAuthMiddleware(app, token)
    auth_label = "ON (bearer token)" if auth_on else "off — reachable by ANY local user on this machine"
    print(f"\n  Selran Hub MCP Bridge ({label})")
    print(f"  ──────────────────────────────")
    print(f"  Endpoint: http://{host}:{port}{path}")
    print(f"  Auth:     {auth_label}")
    print(f"  Hub:      {_api_base}")
    print(f"  ──────────────────────────────\n")
    # Bound for a network listener: cap connection fan-out and slow-header holds.
    uvicorn.run(app, host=host, port=port, log_level="warning",
                limit_concurrency=64, timeout_keep_alive=10)


def main():
    global _api_base
    parser = argparse.ArgumentParser(
        description="MCP Server Bridge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Transport modes:
  stdio            Default. Claude launches this as a child process over stdin/stdout.
  streamable-http  Modern remote MCP transport — for a Claude client on another
                   machine. Binding off loopback REQUIRES $SELRAN_HUB_BRIDGE_TOKEN
                   (clients send Authorization: Bearer <token>).
  sse              Legacy HTTP transport (same auth rule); prefer streamable-http.

Examples:
  python mcp_bridge.py                                          # stdio (local)
  python mcp_bridge.py --transport streamable-http             # local HTTP on :8421
  SELRAN_HUB_BRIDGE_TOKEN=secret python mcp_bridge.py \\
      --transport streamable-http --host 0.0.0.0 --port 8421   # remote, authenticated
  python mcp_bridge.py --api http://127.0.0.1:11999            # explicit Hub URL
""",
    )
    parser.add_argument(
        "--api", default=DEFAULT_API,
        help=f"Dashboard API base URL (default: {DEFAULT_API})",
    )
    parser.add_argument(
        "--transport", choices=["stdio", "streamable-http", "sse"], default="stdio",
        help="stdio (default, local), streamable-http (remote, modern), or sse (legacy)",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_SSE_PORT,
        help=f"Port for an HTTP transport (default: {DEFAULT_SSE_PORT})",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Host to bind an HTTP transport to (default 127.0.0.1). A non-loopback "
             "host (e.g. 0.0.0.0) REQUIRES $SELRAN_HUB_BRIDGE_TOKEN to be set.",
    )
    args = parser.parse_args()
    _api_base = args.api

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        _run_http(args.transport, args.host, args.port)


if __name__ == "__main__":
    main()

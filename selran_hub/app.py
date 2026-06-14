"""
MCP Server — Management Hub
A general-purpose web app for creating, configuring, and monitoring
MCP servers that connect AI tools to your data sources.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import sys
import tempfile
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .config import (
    get_sources_file, get_api_key, set_api_key, is_headless,
    get_log_file, get_request_log_file, VERSION,
)
from .source_manager import SourceManager

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.FileHandler(get_log_file(), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("mcp-server")

# Request log — keeps last N entries in memory for dashboard + writes to file
request_logger = logging.getLogger("mcp-server.requests")
request_logger.addHandler(logging.FileHandler(get_request_log_file(), encoding="utf-8"))

MAX_LOG_ENTRIES = 500
_request_log: deque[dict] = deque(maxlen=MAX_LOG_ENTRIES)

# ---------------------------------------------------------------------------
# Rate limiter (simple in-memory, per-IP)
# ---------------------------------------------------------------------------

RATE_LIMIT_WINDOW = 60   # seconds
# Generous because it now covers every route and the dashboards poll a few
# panels every 2s (~30 req/min each). The point is to bound abuse on a local
# service, not to be strict.
RATE_LIMIT_MAX = 600     # max requests per window per client

_rate_buckets: dict[str, list[float]] = {}


def _check_rate_limit(client_ip: str) -> bool:
    """Return True if request is allowed, False if rate-limited."""
    now = time.time()
    bucket = _rate_buckets.setdefault(client_ip, [])
    # Prune old entries
    cutoff = now - RATE_LIMIT_WINDOW
    _rate_buckets[client_ip] = [t for t in bucket if t > cutoff]
    bucket = _rate_buckets[client_ip]
    if len(bucket) >= RATE_LIMIT_MAX:
        return False
    bucket.append(now)
    return True


# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------

class ErrorCode:
    NOT_FOUND = "NOT_FOUND"
    BAD_REQUEST = "BAD_REQUEST"
    RATE_LIMITED = "RATE_LIMITED"
    UNAUTHORIZED = "UNAUTHORIZED"
    INTERNAL = "INTERNAL_ERROR"
    CONNECTOR_ERROR = "CONNECTOR_ERROR"


def error_response(status: int, code: str, message: str, details: dict = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Selran Hub",
    version=VERSION,
    description="Selran Hub — the single local runtime for the Selran ecosystem: data sources, port registry, MCP bridge, service lifecycle.",
)
_HUB_PORT = int(os.environ.get("SELRAN_HUB_PORT", "11999"))
_LOCAL_ORIGINS = [f"http://127.0.0.1:{_HUB_PORT}", f"http://localhost:{_HUB_PORT}"]

# CORS is locked to the Hub's own localhost origins — never "*". A page on a
# remote site can still *send* a request (CORS doesn't stop the send), but it
# cannot *read* the response, and the CSRF guard in the middleware below
# refuses cross-origin state-changing requests outright.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_LOCAL_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Hub identity (/hub/health) + absorbed port-registry surface (/health, /v1/*).
# Registered before everything else so the frontend catch-all (defined at the
# bottom of this file) can never shadow these routes.
from .hub_router import router as hub_router  # noqa: E402

app.include_router(hub_router)

manager = SourceManager(get_sources_file())


# ---------------------------------------------------------------------------
# Middleware — logging, auth, rate limiting
# ---------------------------------------------------------------------------

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _is_local_origin(origin: str) -> bool:
    return origin in _LOCAL_ORIGINS


def _is_loopback_client(host: str) -> bool:
    """True for loopback IPs and for non-IP hosts (the test harness presents
    'testclient'; unix sockets present ''). A real remote connection always
    presents a routable IP, which is rejected. The Hub also binds 127.0.0.1,
    so this is defense in depth against a future bind change / reverse proxy."""
    import ipaddress
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return True


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    start = time.time()
    client_ip = request.client.host if request.client else "unknown"
    path = request.url.path

    # 1. Loopback only (defense in depth — the Hub already binds 127.0.0.1).
    if not _is_loopback_client(client_ip):
        return error_response(403, ErrorCode.UNAUTHORIZED,
                              "Selran Hub accepts loopback connections only")

    # 2. CSRF guard on EVERY state-changing request (the registry, service
    #    lifecycle, studio, audit, and entitlements routes are NOT under /api,
    #    so the old /api-only gate left them open).
    if request.method in _UNSAFE_METHODS:
        sec_fetch_site = request.headers.get("sec-fetch-site")
        origin = request.headers.get("origin")

        # (a) Reject anything that announces itself as cross-origin.
        if sec_fetch_site in ("cross-site", "same-site") or \
                (origin is not None and not _is_local_origin(origin)):
            logger.warning(f"CSRF guard refused {request.method} {path} "
                           f"(origin={origin!r}, sec-fetch-site={sec_fetch_site!r})")
            return error_response(403, ErrorCode.UNAUTHORIZED,
                                  "cross-origin state-changing request refused")

        # (b) FAIL CLOSED on the Hub's own surface (/v1, /hub) — including the
        #     RCE sink /v1/services. Don't trust the *absence* of browser
        #     headers: require a custom header that a cross-origin page cannot
        #     send without a CORS preflight, which the locked-to-localhost CORS
        #     policy refuses. Local callers (CLI, skills, the Hub's own pages)
        #     set it freely; a remote web page cannot. (/api keeps the
        #     origin-only guard so the legacy dashboard SPA still works.)
        if path.startswith(("/v1", "/hub")) and \
                request.headers.get("x-selran-local") != "1":
            logger.warning(f"CSRF guard refused {request.method} {path} "
                           f"(missing X-Selran-Local on local-only surface)")
            return error_response(403, ErrorCode.UNAUTHORIZED,
                                  "missing X-Selran-Local header (local-only surface)")

    # 3. Rate limiting — now applies to ALL routes, not just /api.
    if not _check_rate_limit(client_ip):
        logger.warning(f"Rate limited: {client_ip} on {path}")
        return error_response(429, ErrorCode.RATE_LIMITED, "Too many requests. Try again later.")

    # 4. Optional API-key auth for the /api data-source surface. A managed
    #    policy (H9) can REQUIRE it — then /api stays locked until a key is set.
    if path.startswith("/api") and path not in ("/api/health", "/api/auth/status"):
        from . import policy
        api_key = get_api_key()
        if policy.require_auth() and not api_key:
            return error_response(503, ErrorCode.UNAUTHORIZED,
                                  "org policy requires API authentication, but no API key is configured")
        if api_key:
            provided = request.headers.get("X-API-Key") or request.query_params.get("api_key")
            if provided != api_key:
                return error_response(401, ErrorCode.UNAUTHORIZED, "Invalid or missing API key")

    response = await call_next(request)

    # 5. Cache discipline. HTML and the theme/nav script must always
    #    revalidate: a browser pairing a stale cached page with a fresh
    #    nav.js (or vice versa) after an upgrade renders a mixed-theme,
    #    unreadable UI. Vendor libs are large and effectively immutable,
    #    so they may cache for a day.
    ctype = response.headers.get("content-type", "")
    if "text/html" in ctype or path == "/hub/nav.js":
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    elif path.startswith("/vendor/"):
        response.headers.setdefault("Cache-Control", "public, max-age=86400")

    # Request log — keep it focused on the API surface to avoid logging every
    # 2s dashboard poll.
    if path.startswith(("/api", "/v1", "/hub")):
        elapsed = round((time.time() - start) * 1000, 1)
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": request.method,
            "path": path,
            "status": response.status_code,
            "elapsed_ms": elapsed,
            "client": client_ip,
        }
        _request_log.append(log_entry)
        request_logger.info(
            f"{request.method} {path} → {response.status_code} ({elapsed}ms) [{client_ip}]"
        )

    return response


# ---------------------------------------------------------------------------
# Exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}", exc_info=True)
    return error_response(500, ErrorCode.INTERNAL, "An internal error occurred")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class SourceCreate(BaseModel):
    name: str
    type: str  # folder, duckdb, sqlite, api
    path: Optional[str] = None
    url: Optional[str] = None
    description: str = ""
    rules: dict = Field(default_factory=lambda: {
        "read_only": True,
        "row_limit": 1000,
        "sensitive_filter": False,
    })

class SourceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    path: Optional[str] = None
    url: Optional[str] = None
    rules: Optional[dict] = None
    enabled: Optional[bool] = None

class SourceOut(BaseModel):
    id: str
    name: str
    type: str
    path: Optional[str] = None
    url: Optional[str] = None
    description: str
    rules: dict
    enabled: bool
    status: str
    error: Optional[str] = None
    created_at: str
    last_checked: Optional[str] = None
    stats: dict = Field(default_factory=dict)

class QueryBody(BaseModel):
    sql: str
    limit: int = 1000

class AuthConfig(BaseModel):
    enabled: bool
    api_key: Optional[str] = None

# ---------------------------------------------------------------------------
# API Routes — Health & Info
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health_check():
    """Health check endpoint (no auth required)."""
    return {
        "status": "healthy",
        "version": VERSION,
        "uptime_seconds": round(time.time() - _app_start_time, 1),
    }

_app_start_time = time.time()

@app.get("/api/info")
async def app_info():
    """Application info."""
    return {
        "name": "MCP Server",
        "version": VERSION,
        "platform": platform.system(),
        "python": platform.python_version(),
        "headless": is_headless(),
        "auth_enabled": get_api_key() is not None,
    }


# ---------------------------------------------------------------------------
# API Routes — Auth
# ---------------------------------------------------------------------------

@app.get("/api/auth/status")
async def auth_status():
    """Check if auth is enabled (no auth required)."""
    return {"enabled": get_api_key() is not None}


@app.post("/api/auth/configure")
async def configure_auth(body: AuthConfig):
    """Enable or disable API key authentication."""
    key = set_api_key(body.enabled, body.api_key)
    logger.info(f"Auth {'enabled' if body.enabled else 'disabled'}")
    return {
        "enabled": body.enabled,
        "api_key": key if body.enabled else None,
        "message": "API key auth enabled. Include X-API-Key header in requests." if body.enabled
                   else "API key auth disabled.",
    }


# ---------------------------------------------------------------------------
# API Routes — Import / Export (must be before {source_id} routes)
# ---------------------------------------------------------------------------

@app.get("/api/sources/export")
async def export_sources():
    """Export all source configurations as JSON (for backup or migration)."""
    return manager.export_config()


@app.post("/api/sources/import")
async def import_sources(body: dict):
    """Import source configurations from JSON."""
    sources = body.get("sources", [])
    if not sources:
        raise HTTPException(400, "No sources in payload")
    result = manager.import_config(sources)
    logger.info(f"Imported {result['imported']} sources")
    return result


# ---------------------------------------------------------------------------
# API Routes — Sources CRUD
# ---------------------------------------------------------------------------

@app.get("/api/sources", response_model=list[SourceOut])
async def list_sources():
    """List all registered data sources with live status."""
    return manager.list_all()


@app.get("/api/sources/{source_id}", response_model=SourceOut)
async def get_source(source_id: str):
    src = manager.get(source_id)
    if not src:
        raise HTTPException(404, "Source not found")
    return src


@app.post("/api/sources", response_model=SourceOut, status_code=201)
async def create_source(body: SourceCreate):
    """Register a new data source."""
    from . import policy
    allowed = policy.allowed_source_types()
    if allowed is not None and (body.type or "").lower() not in allowed:
        return error_response(
            403, ErrorCode.UNAUTHORIZED,
            f"source type '{body.type}' is not allowed by org policy "
            f"(allowed: {', '.join(sorted(allowed))})",
        )
    logger.info(f"Creating source: {body.name} ({body.type})")
    return manager.create(body)


@app.patch("/api/sources/{source_id}", response_model=SourceOut)
async def update_source(source_id: str, body: SourceUpdate):
    src = manager.update(source_id, body)
    if not src:
        raise HTTPException(404, "Source not found")
    logger.info(f"Updated source: {source_id}")
    return src


@app.delete("/api/sources/{source_id}")
async def delete_source(source_id: str):
    ok = manager.delete(source_id)
    if not ok:
        raise HTTPException(404, "Source not found")
    logger.info(f"Deleted source: {source_id}")
    return {"deleted": True}


@app.post("/api/sources/{source_id}/check")
async def check_source(source_id: str):
    """Manually check connectivity / health of a source."""
    result = manager.check(source_id)
    if result is None:
        raise HTTPException(404, "Source not found")
    return result


@app.post("/api/sources/{source_id}/toggle")
async def toggle_source(source_id: str):
    """Enable / disable a source."""
    src = manager.toggle(source_id)
    if not src:
        raise HTTPException(404, "Source not found")
    return src


# ---------------------------------------------------------------------------
# API Routes — Preview / Explore
# ---------------------------------------------------------------------------

@app.get("/api/sources/{source_id}/tables")
async def list_tables(source_id: str):
    """List tables/files available in a source."""
    tables = manager.list_tables(source_id)
    if tables is None:
        raise HTTPException(404, "Source not found")
    return {"tables": tables}


@app.get("/api/sources/{source_id}/preview/{table_name}")
async def preview_table(source_id: str, table_name: str, limit: int = 20):
    """Preview rows from a table/file."""
    data = manager.preview(source_id, table_name, limit)
    if data is None:
        raise HTTPException(404, "Source or table not found")
    return data


@app.post("/api/sources/{source_id}/query")
async def query_source(source_id: str, body: QueryBody):
    """Execute a read-only SQL query against a source."""
    if not body.sql.strip():
        raise HTTPException(400, "No SQL provided")
    logger.info(f"Query on {source_id}: {body.sql[:100]}...")
    result = manager.query(source_id, body.sql, body.limit)
    if result is None:
        raise HTTPException(404, "Source not found")
    return result


@app.get("/api/sources/{source_id}/describe/{table_name}")
async def describe_table(source_id: str, table_name: str):
    """Get descriptive statistics for a table."""
    result = manager.describe(source_id, table_name)
    if result is None:
        raise HTTPException(404, "Source or table not found")
    return result


# ---------------------------------------------------------------------------
# API Routes — File Browser (native OS dialog)
# ---------------------------------------------------------------------------

# Helper: run osascript in a detached shell process to avoid NSWindow crash.
# Uses a sentinel ("__DONE__") in the result file so we don't read partial output.
def _run_osascript_detached(script: str, timeout: int = 120) -> str | None:
    """Run osascript in a detached shell, return path or None on cancel."""
    fd_s, script_path = tempfile.mkstemp(suffix=".applescript", prefix="osa_")
    os.close(fd_s)
    result_path = script_path + ".result"
    wrapper_path = script_path + ".sh"

    try:
        with open(script_path, "w") as f:
            f.write(script)

        with open(wrapper_path, "w") as f:
            f.write(f'''#!/bin/sh
OUTPUT=$(/usr/bin/osascript "{script_path}" 2>&1)
RC=$?
if [ $RC -eq 0 ]; then
    printf "__DONE__\\n%s" "$OUTPUT" > "{result_path}"
else
    if echo "$OUTPUT" | grep -qi "cancel"; then
        printf "__DONE__\\n" > "{result_path}"
    else
        printf "__DONE__\\nERROR:%s" "$OUTPUT" > "{result_path}"
    fi
fi
rm -f "{script_path}" "{wrapper_path}"
''')
        os.chmod(wrapper_path, 0o755)

        subprocess.Popen(
            ["/bin/sh", wrapper_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True, close_fds=True,
        )

        deadline = time.time() + timeout
        while time.time() < deadline:
            if os.path.exists(result_path):
                try:
                    with open(result_path) as f:
                        raw = f.read()
                except OSError:
                    time.sleep(0.2)
                    continue
                if not raw.startswith("__DONE__"):
                    time.sleep(0.1)
                    continue
                content = raw[len("__DONE__"):].strip()
                if content.startswith("ERROR:"):
                    return content
                return content if content else None
            time.sleep(0.25)

        return "ERROR:Dialog timed out"
    finally:
        for p in (script_path, wrapper_path, result_path):
            try:
                os.unlink(p)
            except OSError:
                pass

@app.get("/api/browse")
async def browse_path(mode: str = "folder"):
    """Open native OS file/folder picker and return the selected path."""
    try:
        system = platform.system()

        if system == "Darwin":
            # On macOS, run osascript in a *detached* helper process to avoid
            # NSInternalInconsistencyException (NSWindow main-thread crash)
            # when called from a non-main thread.
            if mode == "folder":
                script = (
                    'tell application "Finder"\n'
                    '  activate\n'
                    'end tell\n'
                    'set theFolder to choose folder with prompt "Select a folder"\n'
                    'return POSIX path of theFolder'
                )
            else:
                script = (
                    'tell application "Finder"\n'
                    '  activate\n'
                    'end tell\n'
                    'set theFile to choose file with prompt "Select a file"\n'
                    'return POSIX path of theFile'
                )
            posix_path = _run_osascript_detached(script)
            if posix_path is None:
                # User cancelled
                return {"path": None, "cancelled": True}
            if posix_path.startswith("ERROR:"):
                return {
                    "path": None, "cancelled": False,
                    "error": f"File browser failed: {posix_path[6:]}. Enter the path manually.",
                    "headless": True,
                }
            if posix_path.endswith("/"):
                posix_path = posix_path[:-1]
            return {"path": posix_path, "cancelled": False}

        elif system == "Windows":
            # Windows can usually show dialogs even from scheduled tasks
            if mode == "folder":
                ps_cmd = (
                    "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
                    "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                    "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath } else { '' }"
                )
            else:
                ps_cmd = (
                    "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
                    "$d = New-Object System.Windows.Forms.OpenFileDialog; "
                    "if ($d.ShowDialog() -eq 'OK') { $d.FileName } else { '' }"
                )
            result = subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=120,
            )
            path = result.stdout.strip()
            if not path:
                return {"path": None, "cancelled": True}
            return {"path": path, "cancelled": False}

        else:
            # Linux requires a display server — bail early if headless
            if is_headless():
                return {
                    "path": None, "cancelled": False,
                    "error": "File browser unavailable without a display server. Enter the path manually.",
                    "headless": True,
                }
            for toolkit in ("zenity", "kdialog"):
                if mode == "folder":
                    if toolkit == "zenity":
                        cmd = ["zenity", "--file-selection", "--directory", "--title=Select a folder"]
                    else:
                        cmd = ["kdialog", "--getexistingdirectory", os.path.expanduser("~")]
                else:
                    if toolkit == "zenity":
                        cmd = ["zenity", "--file-selection", "--title=Select a file"]
                    else:
                        cmd = ["kdialog", "--getopenfilename", os.path.expanduser("~")]
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    path = result.stdout.strip()
                    if result.returncode == 0 and path:
                        return {"path": path, "cancelled": False}
                    if result.returncode != 0:
                        return {"path": None, "cancelled": True}
                except FileNotFoundError:
                    continue
            return {"path": None, "cancelled": True, "error": "No file dialog available (install zenity or kdialog)"}

    except subprocess.TimeoutExpired:
        return {"path": None, "cancelled": True, "error": "Dialog timed out"}
    except Exception as e:
        return {"path": None, "cancelled": True, "error": str(e)}


# ---------------------------------------------------------------------------
# API Routes — System Check (installation verification)
# ---------------------------------------------------------------------------

@app.get("/api/system-check")
async def system_check():
    """Verify server, background service, and AI client registrations."""
    checks = []

    # 1. Server health
    checks.append({
        "name": "Server running",
        "status": "pass",
        "detail": f"Healthy on port {os.environ.get('MCP_PORT', 8420)}, uptime {int(time.time() - _app_start_time)}s",
    })

    # 2. Background service (macOS LaunchAgent / Linux systemd / Windows schtasks)
    system = platform.system()
    if system == "Darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / "com.neutrondev.mcp-server.plist"
        if plist.exists():
            # Check if loaded
            result = subprocess.run(
                ["launchctl", "list", "com.neutrondev.mcp-server"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                checks.append({"name": "Background service", "status": "pass", "detail": "macOS LaunchAgent installed and loaded"})
            else:
                checks.append({"name": "Background service", "status": "warn", "detail": "LaunchAgent file exists but not loaded — try: launchctl load ~/Library/LaunchAgents/com.neutrondev.mcp-server.plist"})
        else:
            checks.append({"name": "Background service", "status": "fail", "detail": "No LaunchAgent found — run python start.py to install"})
    elif system == "Linux":
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "mcp-server"],
            capture_output=True, text=True,
        )
        if result.stdout.strip() == "active":
            checks.append({"name": "Background service", "status": "pass", "detail": "systemd user service active"})
        else:
            checks.append({"name": "Background service", "status": "fail", "detail": "systemd service not active — run python start.py to install"})
    elif system == "Windows":
        result = subprocess.run(
            ["schtasks", "/query", "/tn", "MCP-Server"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            checks.append({"name": "Background service", "status": "pass", "detail": "Windows Task Scheduler job found"})
        else:
            checks.append({"name": "Background service", "status": "fail", "detail": "No scheduled task found — run python start.py to install"})
    else:
        checks.append({"name": "Background service", "status": "skip", "detail": f"Not supported on {system}"})

    # 3. MCP bridge file exists
    bridge_path = Path(__file__).resolve().parent / "mcp_bridge.py"
    if bridge_path.exists():
        checks.append({"name": "MCP bridge script", "status": "pass", "detail": str(bridge_path)})
    else:
        checks.append({"name": "MCP bridge script", "status": "fail", "detail": "mcp_bridge.py not found in backend/"})

    # 4. AI client registrations
    home = Path.home()
    ai_clients = {
        "Claude Desktop": {
            "Darwin": home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
            "Linux": home / ".config" / "claude" / "claude_desktop_config.json",
            "Windows": home / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json",
        },
        "Claude Code": {
            "Darwin": home / ".claude.json",
            "Linux": home / ".claude.json",
            "Windows": home / ".claude.json",
        },
        "Cursor": {
            "Darwin": home / ".cursor" / "mcp.json",
            "Linux": home / ".cursor" / "mcp.json",
            "Windows": home / ".cursor" / "mcp.json",
        },
        "Windsurf": {
            "Darwin": home / ".codeium" / "windsurf" / "mcp_config.json",
            "Linux": home / ".codeium" / "windsurf" / "mcp_config.json",
            "Windows": home / ".codeium" / "windsurf" / "mcp_config.json",
        },
        "Continue.dev": {
            "Darwin": home / ".continue" / "config.json",
            "Linux": home / ".continue" / "config.json",
            "Windows": home / ".continue" / "config.json",
        },
    }

    for client_name, paths in ai_clients.items():
        config_path = paths.get(system)
        if not config_path:
            continue
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
                servers = config.get("mcpServers", {})
                if "selran-hub" in servers or "mcp-server" in servers:
                    entry = servers.get("selran-hub") or servers.get("mcp-server")
                    if "url" in entry:
                        detail = f"Registered (SSE: {entry['url']})"
                    elif "command" in entry:
                        detail = f"Registered (stdio: {Path(entry['args'][0]).name if entry.get('args') else '?'})"
                    else:
                        detail = "Registered (unknown transport)"
                    checks.append({"name": client_name, "status": "pass", "detail": detail})
                else:
                    checks.append({"name": client_name, "status": "fail", "detail": "Config exists but mcp-server not registered"})
            except Exception as e:
                checks.append({"name": client_name, "status": "warn", "detail": f"Could not read config: {e}"})
        else:
            # Check if the client is even installed (parent dir exists)
            if config_path.parent.exists():
                checks.append({"name": client_name, "status": "fail", "detail": "Client detected but mcp-server not registered — run python start.py"})
            else:
                checks.append({"name": client_name, "status": "skip", "detail": "Not installed"})

    # 5. Data sources
    source_count = len(manager.list_all())
    if source_count > 0:
        online = sum(1 for s in manager.list_all() if s.get("status") == "online")
        checks.append({"name": "Data sources", "status": "pass", "detail": f"{source_count} configured, {online} online"})
    else:
        checks.append({"name": "Data sources", "status": "warn", "detail": "No sources added yet — click '+ Add Source' to connect your data"})

    # Summary
    passed = sum(1 for c in checks if c["status"] == "pass")
    total = sum(1 for c in checks if c["status"] != "skip")

    return {
        "checks": checks,
        "summary": {"passed": passed, "total": total, "all_pass": passed == total},
    }


# ---------------------------------------------------------------------------
# API Routes — MCP Config Generation
# ---------------------------------------------------------------------------

@app.get("/api/mcp-config")
async def get_mcp_config(format: str = "claude", transport: str = "stdio"):
    """Generate MCP config for Claude Desktop, Claude Code, or generic.

    Query params:
      format:    'claude' or 'generic'
      transport: 'stdio' (default, local) or 'sse' (remote/network)
    """
    return manager.generate_mcp_config(format, transport)


@app.post("/api/mcp-config/install")
async def install_mcp_config(format: str = "claude"):
    """Write MCP config to the appropriate location."""
    result = manager.install_mcp_config(format)
    return result


# ---------------------------------------------------------------------------
# API Routes — Stats & Logs
# ---------------------------------------------------------------------------

@app.get("/api/stats")
async def dashboard_stats():
    """Aggregate stats for the dashboard."""
    sources = manager.list_all()
    type_counts = {}
    for s in sources:
        t = s["type"]
        type_counts[t] = type_counts.get(t, 0) + 1
    return {
        "total": len(sources),
        "online": sum(1 for s in sources if s["status"] == "online"),
        "offline": sum(1 for s in sources if s["status"] == "offline"),
        "error": sum(1 for s in sources if s["status"] == "error"),
        "types": type_counts,
    }


@app.get("/api/logs")
async def get_logs(limit: int = 100, level: str = "all"):
    """Get recent request logs."""
    entries = list(_request_log)
    if level != "all":
        status_filter = {"error": range(400, 600), "success": range(200, 400)}
        if level in status_filter:
            entries = [e for e in entries if e.get("status", 0) in status_filter[level]]
    return {"logs": entries[-limit:], "total": len(entries)}


# ---------------------------------------------------------------------------
# Serve frontend (production)
# ---------------------------------------------------------------------------

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
if FRONTEND_DIR.exists():
    ASSETS_DIR = FRONTEND_DIR / "assets"
    if ASSETS_DIR.exists():
        app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

    _FRONTEND_ROOT = FRONTEND_DIR.resolve()

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # API namespaces never fall through to the frontend: unknown API paths
        # must error like an API, not serve index.html.
        if full_path.startswith(("api", "v1", "hub", "health", "studio", "audit")):
            raise HTTPException(404)
        # Path containment: a non-normalizing client (curl --path-as-is, some
        # HTTP libs, proxies) can send ../ to escape the frontend dir and read
        # arbitrary files. Resolve and require the target stays under the root.
        target = (FRONTEND_DIR / full_path).resolve()
        if target.is_file() and target.is_relative_to(_FRONTEND_ROOT):
            return FileResponse(target)
        return FileResponse(_FRONTEND_ROOT / "index.html")

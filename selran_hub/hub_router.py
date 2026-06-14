"""Selran Hub identity + absorbed port-registry routes (spec §3.2, §4.1).

The registry contract is mirrored from the rescued app-port-registry service
verbatim — same paths, same response shapes, same status codes (including the
historical quirk that an unknown app on GET /v1/apps/{id} returns 400, not
404). Existing clients (every Selran app, the app-port-registry CLI, the
app-startup skill's scripts) must keep working unmodified against the Hub.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .port_registry_core import RegistryError, RegistryStore
from .service_manager import ServiceManager
from .studio import StudioManager, render_page
from .audit_panel import AuditPanelManager, render_panel
from .entitlements import EntitlementManager, LicenseError
from . import packs as packs_mod
from .theme import THEME_CSS

HUB_NAME = "selran"
from .config import VERSION as HUB_VERSION
HUB_API = 1
# The honesty contract (spec §4.1): list only what this build actually serves.
HUB_CAPABILITIES = ["sources", "mcp", "ports", "services", "studio", "audit", "entitlements"]

router = APIRouter()

_store: RegistryStore | None = None
_services: ServiceManager | None = None
_studio = StudioManager()
_audit = AuditPanelManager()
_entitlements = EntitlementManager()


def get_store() -> RegistryStore:
    """Lazy singleton so tests can point SELRAN_HUB_REGISTRY_DB at a temp file
    before the first request. Default matches the historical registry location,
    so an existing machine's allocations carry over on cutover."""
    global _store
    if _store is None:
        db = Path(
            os.environ.get(
                "SELRAN_HUB_REGISTRY_DB",
                str(Path.home() / ".config" / "app-port-registry.sqlite3"),
            )
        )
        _store = RegistryStore(db)
    return _store


def get_services() -> ServiceManager:
    global _services
    if _services is None:
        db = Path(
            os.environ.get(
                "SELRAN_HUB_REGISTRY_DB",
                str(Path.home() / ".config" / "app-port-registry.sqlite3"),
            )
        )
        _services = ServiceManager(db)
    return _services


def _error(message: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"status": "error", "message": message})


# --------------------------------------------------------------------------
# Hub identity (spec §4.1)
# --------------------------------------------------------------------------

@router.get("/hub/health")
async def hub_health(request: Request):
    return {
        "hub": HUB_NAME,
        "version": HUB_VERSION,
        "api": HUB_API,
        "capabilities": HUB_CAPABILITIES,
        "services": get_services().summary(),
    }


@router.get("/v1/update")
async def update_status(request: Request):
    """Update availability (H6). Opt-in: does nothing unless
    SELRAN_HUB_UPDATE_CHECK is set — the only outbound call the Hub makes, and it
    sends nothing about the user. Cached weekly."""
    from . import updater
    return updater.status_for_endpoint()


@router.get("/v1/policy")
async def policy_status(request: Request):
    """The effective managed policy (H9) — read-only. Empty/unmanaged unless an
    admin has deployed managed-policy.json to the system-managed location."""
    from . import policy
    return policy.effective()


# --------------------------------------------------------------------------
# Registry compatibility surface (spec §3.2) — contract mirrored verbatim
# --------------------------------------------------------------------------

@router.get("/health")
async def registry_health(request: Request):
    port = request.url.port or 0
    return {"status": "ok", "service": "app-port-registry", "port": port, "hub": HUB_NAME}


@router.get("/v1/report")
async def report():
    return get_store().list_apps()


@router.get("/v1/apps")
async def apps():
    return get_store().list_apps()


@router.get("/v1/apps/{app_id}")
async def get_app(app_id: str):
    try:
        return get_store().get_app(app_id)
    except RegistryError as exc:
        return _error(str(exc))


@router.get("/v1/lookup")
async def lookup(path: str = ""):
    try:
        return get_store().lookup_path(path)
    except RegistryError as exc:
        return _error(str(exc))


@router.get("/v1/validate")
async def validate():
    return get_store().validate()


@router.get("/v1/archived")
async def archived():
    return get_store().list_archived_apps()


@router.post("/v1/ensure")
async def ensure(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise RegistryError("JSON body must be an object")
        return get_store().ensure_app(
            str(body.get("app_id", "")),
            str(body.get("path", "")),
            str(body.get("description", "")),
        )
    except RegistryError as exc:
        return _error(str(exc))


@router.post("/v1/reclaim")
async def reclaim(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise RegistryError("JSON body must be an object")
        return get_store().reclaim_ports(
            app_id=str(body.get("app_id", "") or "") or None,
            path=str(body.get("path", "") or "") or None,
        )
    except RegistryError as exc:
        return _error(str(exc))


@router.post("/v1/archive")
async def archive(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise RegistryError("JSON body must be an object")
        return get_store().archive_app(
            app_id=str(body.get("app_id", "") or "") or None,
            path=str(body.get("path", "") or "") or None,
            reason=str(body.get("reason", "")),
        )
    except RegistryError as exc:
        return _error(str(exc))


# --------------------------------------------------------------------------
# Service lifecycle surface (spec §3.3, §6) — M2
# --------------------------------------------------------------------------

@router.get("/v1/services")
async def services_list():
    return get_services().list_services()


@router.post("/v1/services")
async def services_register(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise RegistryError("JSON body must be an object")
        return get_services().register(
            service_id=str(body.get("id", "")),
            cwd=str(body.get("cwd", "")),
            start_cmd=str(body.get("start_cmd", "")),
            name=str(body.get("name", "")),
            health_url=str(body.get("health_url", "")),
            registry_app_id=str(body.get("registry_app_id", "")),
            env={str(k): str(v) for k, v in (body.get("env") or {}).items()},
        )
    except RegistryError as exc:
        return _error(str(exc))


@router.get("/v1/services/{service_id}")
async def services_describe(service_id: str):
    try:
        return get_services().describe(service_id)
    except RegistryError as exc:
        return _error(str(exc))


@router.post("/v1/services/{service_id}/start")
async def services_start(service_id: str):
    try:
        return get_services().start(service_id)
    except RegistryError as exc:
        return _error(str(exc))


@router.post("/v1/services/{service_id}/stop")
async def services_stop(service_id: str):
    try:
        return get_services().stop(service_id)
    except RegistryError as exc:
        return _error(str(exc))


@router.post("/v1/services/{service_id}/restart")
async def services_restart(service_id: str):
    try:
        return get_services().restart(service_id)
    except RegistryError as exc:
        return _error(str(exc))


@router.delete("/v1/services/{service_id}")
async def services_unregister(service_id: str):
    try:
        return get_services().unregister(service_id)
    except RegistryError as exc:
        return _error(str(exc))


# --------------------------------------------------------------------------
# Orphan-PID reaper surface (H0) — show every PID on an app's ports, stop the
# orphaned/stale ones safely (identity-gated; never kills by port alone).
# --------------------------------------------------------------------------

def _ports_for_registry_app(app_id: str | None) -> list[int]:
    if not app_id:
        return []
    try:
        app = get_store().get_app(app_id)
    except RegistryError:
        return []
    rng = app.get("range") or []
    if len(rng) == 2:
        from .port_registry_core import ports_for_range
        return ports_for_range(int(rng[0]), int(rng[1]))
    return []


@router.get("/v1/services/{service_id}/pids")
async def services_pids(service_id: str):
    try:
        svc = get_services().describe(service_id)
        ports = _ports_for_registry_app(svc.get("registry_app_id"))
        return get_services().scan_pids(
            ports, service_id=service_id, registry_app_id=svc.get("registry_app_id")
        )
    except RegistryError as exc:
        return _error(str(exc))


@router.get("/v1/apps/{app_id}/pids")
async def app_pids(app_id: str):
    try:
        ports = _ports_for_registry_app(app_id)
        return get_services().scan_pids(ports, registry_app_id=app_id)
    except RegistryError as exc:
        return _error(str(exc))


@router.post("/v1/services/{service_id}/pids/{pid}/stop")
async def services_pid_stop(service_id: str, pid: int, request: Request):
    try:
        body: dict = {}
        try:
            parsed = await request.json()
            if isinstance(parsed, dict):
                body = parsed
        except Exception:
            body = {}
        svc = get_services().describe(service_id)
        ports = _ports_for_registry_app(svc.get("registry_app_id"))
        return get_services().stop_pid(
            pid,
            service_id=service_id,
            expected_command=str(body.get("command", "")),
            expected_create_time=body.get("create_time"),
            force=bool(body.get("force")),
            ports=ports,
        )
    except RegistryError as exc:
        return _error(str(exc))


# --------------------------------------------------------------------------
# Service panel — minimal dashboard page (spec §5.1, M2)
# --------------------------------------------------------------------------

from fastapi.responses import HTMLResponse  # noqa: E402

_PANEL_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Selran Hub — Services</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>""" + THEME_CSS + """
 body{font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--sh-bg);color:var(--sh-text);margin:0;padding:36px 24px}
 .wrap{max-width:880px;margin:0 auto} h1{font-size:22px;margin:0 0 4px} .sub{color:var(--sh-muted);margin:0 0 24px}
 table{width:100%;border-collapse:collapse;background:var(--sh-panel);border:1px solid var(--sh-border);border-radius:10px;overflow:hidden}
 th,td{padding:10px 14px;text-align:left;border-bottom:1px solid var(--sh-border2);font-size:14px}
 th{color:var(--sh-muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.06em}
 .state{padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600}
 .running{background:var(--sh-okbg);color:var(--sh-ok)}.stopped{background:var(--sh-border);color:var(--sh-text3)}
 .failed{background:var(--sh-badbg);color:var(--sh-bad)}.registered{background:var(--sh-accentbg);color:var(--sh-link)}
 button{background:var(--sh-btn);color:var(--sh-text);border:1px solid var(--sh-border3);border-radius:7px;padding:6px 12px;font-size:13px;cursor:pointer;margin-right:6px}
 button:hover{border-color:var(--sh-border4)} .empty{padding:28px;text-align:center;color:var(--sh-muted)}
 .pdet td{background:var(--sh-bg);padding:0}
 .pwrap{padding:8px 14px 14px}
 .cov{margin:0 0 8px;padding:8px 12px;border-radius:7px;font-size:12.5px}
 .cov.partial{background:var(--sh-badbg,#3a1d1d);color:var(--sh-bad,#e57373)}
 .cov.complete{background:var(--sh-okbg,#16301f);color:var(--sh-ok,#4caf82)}
 .ptbl{width:100%;border-collapse:collapse;background:var(--sh-panel2,#16161c);border:1px solid var(--sh-border)}
 .ptbl th,.ptbl td{padding:7px 10px;font-size:12.5px;border-bottom:1px solid var(--sh-border2);text-align:left;vertical-align:top}
 .cls{padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600;white-space:nowrap}
 .cls.owned{background:var(--sh-okbg,#16301f);color:var(--sh-ok,#4caf82)}
 .cls.owned-unverified{background:var(--sh-accentbg,#2a2410);color:var(--sh-warn,#caa14b)}
 .cls.ambiguous{background:var(--sh-border);color:var(--sh-text3)}
 .cls.foreign{background:var(--sh-panel);color:var(--sh-muted)}
 .role{font-size:11px;font-weight:600;margin-left:6px;color:var(--sh-warn,#caa14b)}
 .pcmd{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;color:var(--sh-text3);word-break:break-all;max-width:430px}
 .stopx{background:var(--sh-badbg,#3a1d1d);color:var(--sh-bad,#e57373);border:1px solid var(--sh-bad,#e57373)}
 .nostop{color:var(--sh-muted);font-size:11.5px}
</style></head><body>
<script src="/hub/nav.js"></script>
<div class="wrap">
<h1>Services</h1><p class="sub">Lifecycle with verified process identity. Refreshes every 3s. Click <strong>PIDs</strong> to see — and safely stop — leftover processes holding an app's ports.</p>
<table><thead><tr><th>Service</th><th>State</th><th>PID</th><th>Health</th><th>Actions</th></tr></thead>
<tbody id="rows"><tr><td colspan="5" class="empty">Loading…</td></tr></tbody></table>
</div><script>
function esc(s){var d=document.createElement('div');d.textContent=(s==null?'':String(s));return d.innerHTML;}
var expanded={}, pidCache={};
async function act(id, verb){ await fetch(`/v1/services/${id}/${verb}`, {method:"POST", headers:{"X-Selran-Local":"1"}}); load(); }
async function load(){
  if(Object.keys(expanded).length) return;   // don't clobber an open PID view
  const r = await fetch("/v1/services"); const d = await r.json();
  const tb = document.getElementById("rows");
  if(!d.services || !d.services.length){ tb.innerHTML = '<tr><td colspan="5" class="empty">No services yet. When a Selran app registers itself (or you add one via the API), it shows up here with Start / Stop / Restart controls.<br><a href="https://github.com/apourmd941/selran-hub/blob/main/USER_GUIDE.md" target="_blank" style="color:var(--sh-link)">Learn how services work →</a></td></tr>'; return; }
  tb.innerHTML = d.services.map(rowHtml).join("");
}
function rowHtml(s){
  return `<tr>
    <td><strong>${esc(s.name)}</strong><div style="color:#9b9ba6;font-size:12px">${esc(s.id)}</div></td>
    <td><span class="state ${s.state}">${s.state}</span></td>
    <td>${s.pid ?? "—"}</td><td>${s.health ?? "—"}</td>
    <td>${s.state === "running"
        ? `<button onclick="act('${esc(s.id)}','stop')">Stop</button><button onclick="act('${esc(s.id)}','restart')">Restart</button>`
        : `<button onclick="act('${esc(s.id)}','start')">Start</button>`}<button onclick="togglePids('${esc(s.id)}')">PIDs</button></td>
  </tr><tr class="pdet" id="det-${esc(s.id)}" style="display:none"><td colspan="5"><div class="pwrap" id="pw-${esc(s.id)}">Scanning…</div></td></tr>`;
}
async function togglePids(id){
  var det=document.getElementById("det-"+CSS.escape(id));
  if(det.style.display!=="none"){ det.style.display="none"; delete expanded[id]; return; }
  expanded[id]=1; det.style.display="";
  await refreshPids(id);
}
async function refreshPids(id){
  var pw=document.getElementById("pw-"+CSS.escape(id)); pw.textContent="Scanning…";
  var r=await fetch("/v1/services/"+encodeURIComponent(id)+"/pids"); var d=await r.json();
  if(d.status!=="ok"){ pw.innerHTML='<div class="cov partial">'+esc(d.message||"scan failed")+'</div>'; return; }
  pidCache[id]=d.pids||[];
  var cov = d.coverage==="partial"
    ? '<div class="cov partial">⚠ Could not see every listener'+((d.occupied_owner_not_visible&&d.occupied_owner_not_visible.length)?(' — port(s) '+d.occupied_owner_not_visible.join(", ")+' are in use but owned by another user or root (re-run the Hub elevated to manage them)'):'')+'. This is <strong>not</strong> an "all clear".</div>'
    : '<div class="cov complete">All listeners on this app\'s ports are accounted for.</div>';
  if(!d.stop_supported){ cov+='<div class="cov partial">Stopping PIDs needs psutil on macOS/Linux and is unavailable on this build/platform — shown read-only.</div>'; }
  if(!d.pids || !d.pids.length){ pw.innerHTML=cov+'<div class="nostop" style="padding:8px 2px">No processes found on this app\'s ports.</div>'; return; }
  var rows=d.pids.map(function(p,i){
    var canStop=p.offer_stop && d.stop_supported;
    var btn=canStop?('<button class="stopx" onclick="stopPid(\''+esc(id)+'\','+i+')">Stop</button>')
                    :('<span class="nostop">'+esc((p.reasons&&p.reasons[0])||"shown only")+'</span>');
    var role=p.role==="orphan"?'<span class="role">orphan</span>'
            :(p.role==="current"?'<span class="role" style="color:var(--sh-ok,#4caf82)">current</span>':'');
    return '<tr><td>'+p.pid+role+'</td>'
      +'<td><span class="cls '+esc(p.classification)+'">'+esc(p.classification)+'</span></td>'
      +'<td class="pcmd">'+esc(p.command)+'</td>'
      +'<td>'+((p.ports&&p.ports.length)?p.ports.join(", "):"—")+'</td>'
      +'<td>'+esc(p.owner||"—")+'</td><td>'+btn+'</td></tr>';
  }).join("");
  pw.innerHTML=cov+'<table class="ptbl"><thead><tr><th>PID</th><th>Class</th><th>Command</th><th>Port(s)</th><th>Owner</th><th></th></tr></thead><tbody>'+rows+'</tbody></table>';
}
async function stopPid(id, idx){
  var p=(pidCache[id]||[])[idx]; if(!p) return;
  var unverified=p.classification!=="owned";
  var msg=unverified
    ? ("Force-stop PID "+p.pid+"?\n\n"+p.command+"\n\nSelran did NOT verify it launched this. It is yours and is on this app's ports. Stop it?")
    : ("Stop PID "+p.pid+"?\n\n"+p.command);
  if(!confirm(msg)) return;
  var body={command:p.command, create_time:p.create_time};
  if(unverified) body.force=true;
  var r=await fetch("/v1/services/"+encodeURIComponent(id)+"/pids/"+p.pid+"/stop",{method:"POST",headers:{"Content-Type":"application/json","X-Selran-Local":"1"},body:JSON.stringify(body)});
  var d=await r.json();
  if(d.status!=="ok"){ alert("Could not stop PID "+p.pid+": "+(d.message||"error")); }
  await refreshPids(id);
}
load(); setInterval(load, 3000);
</script></body></html>"""


@router.get("/hub/panel", response_class=HTMLResponse)
async def hub_panel():
    return _PANEL_HTML


# --------------------------------------------------------------------------
# Design studio surface (spec §7) — M3: interactive choice over localhost
# --------------------------------------------------------------------------

@router.post("/v1/studio/sessions")
async def studio_create(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise RegistryError("JSON body must be an object")
        session = _studio.create(str(body.get("title", "")), str(body.get("html", "")))
        base = f"http://127.0.0.1:{request.url.port or 11999}"
        return {
            "status": "ok",
            "id": session.session_id,
            "url": f"{base}/studio/{session.session_id}",
            "version": session.version,
        }
    except (RegistryError, ValueError) as exc:
        return _error(str(exc))


@router.get("/studio/{session_id}")
async def studio_page(session_id: str):
    from fastapi.responses import HTMLResponse as _HTML
    s = _studio.get(session_id)
    if s is None:
        return JSONResponse(status_code=404, content={"status": "error", "message": "unknown or expired studio session"})
    return _HTML(render_page(s))


@router.post("/v1/studio/sessions/{session_id}/choice")
async def studio_choice_post(session_id: str, request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict) or not str(body.get("choice", "")).strip():
            raise RegistryError("choice is required")
        s = _studio.record_choice(session_id, str(body["choice"]))
        return {"status": "ok", "id": s.session_id, "choice": s.choice}
    except KeyError:
        return JSONResponse(status_code=404, content={"status": "error", "message": "unknown or expired studio session"})
    except (RegistryError, ValueError) as exc:
        return _error(str(exc))


@router.get("/v1/studio/sessions/{session_id}/choice")
async def studio_choice_get(session_id: str):
    s = _studio.get(session_id)
    if s is None:
        return JSONResponse(status_code=404, content={"status": "error", "message": "unknown or expired studio session"})
    if s.choice is None:
        return {"status": "pending", "id": s.session_id, "version": s.version}
    return {"status": "ok", "id": s.session_id, "choice": s.choice, "version": s.version}


@router.post("/v1/studio/sessions/{session_id}/update")
async def studio_update(session_id: str, request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise RegistryError("JSON body must be an object")
        s = _studio.update_html(session_id, str(body.get("html", "")))
        return {"status": "ok", "id": s.session_id, "version": s.version}
    except KeyError:
        return JSONResponse(status_code=404, content={"status": "error", "message": "unknown or expired studio session"})
    except (RegistryError, ValueError) as exc:
        return _error(str(exc))


@router.get("/v1/studio/sessions/{session_id}/content")
async def studio_content(session_id: str, since: int = 0):
    s = _studio.get(session_id)
    if s is None:
        return JSONResponse(status_code=404, content={"status": "error", "message": "unknown or expired studio session"})
    if s.version <= since:
        return {"status": "unchanged", "version": s.version}
    return {"status": "ok", "version": s.version, "html": s.html}


# --------------------------------------------------------------------------
# Audit panel surface (spec §7) — M4: Greenloop live run dashboard
# --------------------------------------------------------------------------

@router.post("/v1/audit/runs")
async def audit_create(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise RegistryError("JSON body must be an object")
        scope = body.get("scope") or []
        if not isinstance(scope, list):
            raise RegistryError("scope must be a list")
        run = _audit.create(str(body.get("title", "")), str(body.get("repo", "")), [str(x) for x in scope])
        base = f"http://127.0.0.1:{request.url.port or 11999}"
        return {"status": "ok", "id": run.run_id, "url": f"{base}/audit/{run.run_id}", "version": run.version}
    except (RegistryError, ValueError) as exc:
        return _error(str(exc))


@router.get("/audit/{run_id}")
async def audit_page(run_id: str):
    from fastapi.responses import HTMLResponse as _HTML
    run = _audit.get(run_id)
    if run is None:
        return JSONResponse(status_code=404, content={"status": "error", "message": "unknown or expired audit run"})
    return _HTML(render_panel(run))


@router.post("/v1/audit/runs/{run_id}/events")
async def audit_events(run_id: str, request: Request):
    try:
        body = await request.json()
        events = body if isinstance(body, list) else body.get("events") if isinstance(body, dict) else None
        if events is None:
            raise RegistryError("body must be an event list or {\"events\": [...]}")
        run = _audit.append_events(run_id, events)
        return {"status": "ok", "id": run.run_id, "version": run.version}
    except KeyError:
        return JSONResponse(status_code=404, content={"status": "error", "message": "unknown or expired audit run"})
    except (RegistryError, ValueError) as exc:
        return _error(str(exc))


@router.get("/v1/audit/runs/{run_id}")
async def audit_state(run_id: str, since: int = 0):
    run = _audit.get(run_id)
    if run is None:
        return JSONResponse(status_code=404, content={"status": "error", "message": "unknown or expired audit run"})
    if run.version <= since:
        return {"status": "unchanged", "version": run.version}
    return run.to_state()


# --------------------------------------------------------------------------
# Entitlements surface (spec §10) — M6: offline-verified pack licenses
# --------------------------------------------------------------------------

@router.get("/v1/entitlements")
async def entitlements_list():
    return {"status": "ok", "entitlements": _entitlements.list_entitlements()}


@router.post("/v1/entitlements/install")
async def entitlements_install(request: Request):
    try:
        doc = await request.json()
        return {"status": "ok", "entitlement": _entitlements.install(doc)}
    except LicenseError as exc:
        return _error(str(exc))
    except Exception:
        return _error("body must be a license file (JSON with 'license' and 'signature')")


@router.get("/v1/entitlements/check")
async def entitlements_check(product: str = ""):
    return _entitlements.check(product)


@router.delete("/v1/entitlements/{license_id}")
async def entitlements_remove(license_id: str):
    if _entitlements.remove(license_id):
        return {"status": "ok", "removed": license_id}
    return JSONResponse(status_code=404, content={"status": "error", "message": f"no installed license {license_id!r}"})


# --------------------------------------------------------------------------
# Pack browser (spec §5.1, §10) — catalog + entitlement state
# --------------------------------------------------------------------------

@router.get("/v1/packs")
async def packs_catalog():
    import json as _json
    from pathlib import Path as _Path
    catalog = _json.loads((_Path(__file__).parent / "pack_catalog.json").read_text())
    ents = {e["product"]: e for e in _entitlements.list_entitlements() if e.get("valid")}
    has_all = "packs-all" in ents or "all" in ents
    for p in catalog["packs"]:
        e = ents.get(p["product"])
        p["entitled"] = bool(e) or has_all
        p["tier"] = (e or ents.get("packs-all") or ents.get("all") or {}).get("tier") if p["entitled"] else None
        p["purchase_url"] = catalog["purchase_base_url"] + p["id"].removeprefix("pack-")
        # Visual identity: live (from the installed pack) when present, else
        # the bundled catalog identity — so users who own nothing still see
        # each pack's real colors and direction in the gallery.
        ident = packs_mod.pack_identity(p["product"]) or {}
        bundled = p.get("identity") or {}
        p["accent"] = ident.get("accent") or bundled.get("accent") or ""
        p["direction"] = ident.get("direction") or bundled.get("direction") or ""
        p["swatches"] = (ident.get("swatches") or bundled.get("swatches") or [])[:6]
    return {"status": "ok", **catalog}


_PACKS_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Selran Hub — Packs</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>""" + THEME_CSS + """
 body{font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--sh-bg);color:var(--sh-text);margin:0;padding:36px 24px}
 .wrap{max-width:980px;margin:0 auto} h1{font-size:22px;margin:0 0 4px} .sub{color:var(--sh-muted);margin:0 0 22px}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
 .pack{display:block;background:var(--sh-panel);border:1px solid var(--sh-border);border-radius:10px;padding:16px;text-decoration:none;color:inherit;transition:border-color .15s,transform .15s;overflow:hidden}
 .pack:hover{border-color:var(--sh-border4);transform:translateY(-2px)}
 .pack h3{margin:0 0 6px;font-size:15.5px}
 .pack .open{display:block;margin-top:10px;color:var(--sh-link);font-size:12.5px}
 .pack .dir{color:var(--sh-muted2);font-size:12px;margin:-2px 0 8px;text-transform:capitalize}
 .badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11.5px;font-weight:700}
 .owned{background:var(--sh-okbg);color:var(--sh-ok)}.locked{background:var(--sh-border);color:var(--sh-text3)}
 .sws{display:flex;gap:0;border-radius:6px;overflow:hidden;height:18px;margin-top:11px;box-shadow:0 0 0 1px var(--sh-border)}
 .sws i{flex:1}
</style></head><body>
<script src="/hub/nav.js"></script>
<div class="wrap">
<h1>Design Director packs</h1>
<p class="sub">Licenses are plain signed files, verified offline. Nothing phones home.</p>
<div class="grid" id="grid">Loading…</div>
</div><script>
fetch("/v1/packs").then(r=>r.json()).then(d=>{
 document.getElementById("grid").innerHTML = d.packs.map(p=>{
   var base = (p.product||p.id||"").replace(/^pack-/,"");
   var acc = p.accent || "var(--sh-border3)";
   var sws = (p.swatches||[]).map(c=>`<i style="background:${c}"></i>`).join("");
   return `<a class="pack" href="/hub/packs/${base}" style="border-top:3px solid ${acc}">
   <h3>${p.name}</h3>
   ${p.direction?`<div class="dir">${p.direction.replace(/-/g," ")}</div>`:""}
   <span class="badge ${p.entitled?"owned":"locked"}">${p.entitled?("licensed — "+p.tier):"not licensed"}</span>
   ${sws?`<span class="sws">${sws}</span>`:""}
   <span class="open" style="color:${p.accent?acc:"var(--sh-link)"}">View examples →</span></a>`;
 }).join("");
});
</script></body></html>"""


@router.get("/hub/packs")
async def hub_packs_page():
    from fastapi.responses import HTMLResponse as _HTML
    return _HTML(_PACKS_PAGE)


# --------------------------------------------------------------------------
# Shared navigation bar + friendly Apps & Ports page (M: usability)
# --------------------------------------------------------------------------

# One source of truth: every Hub page includes <script src="/hub/nav.js">.
# It injects a top bar with plain-language tabs, a live status strip, and a
# one-line description of the current page — so a non-technical user can find
# everything from anywhere and see at a glance that the Hub is alive.
_NAV_JS = r"""
(function(){
  // ── theme: dark / light / system (persisted; applied before paint) ──
  // Source of truth is the in-page variable `tcur` so the toggle always works
  // even when storage is unavailable (e.g. private browsing). localStorage is
  // best-effort persistence; a ?theme= URL param seeds the value ONCE (a
  // shareable link) and then defers to the toggle.
  var TKEY = "selran-theme", TORDER = ["system", "dark", "light"];
  var mql = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;
  var tcur = "system";
  try {
    var stored = localStorage.getItem(TKEY);
    if (TORDER.indexOf(stored) >= 0) tcur = stored;
  } catch(e){}
  try {
    var q = new URLSearchParams(location.search).get("theme");
    if (TORDER.indexOf(q) >= 0) {
      tcur = q;
      try { localStorage.setItem(TKEY, q); } catch(e){}
    }
  } catch(e){}
  function tapply(){
    var resolved = (tcur === "system") ? ((mql && mql.matches) ? "light" : "dark") : tcur;
    document.documentElement.setAttribute("data-theme", resolved);
  }
  tapply();
  if (mql && mql.addEventListener) mql.addEventListener("change", function(){ if (tcur === "system") tapply(); });
  function tlabel(p){ return p === "dark" ? "☾ Dark" : p === "light" ? "☀ Light" : "◐ Auto"; }

  var PAGES = [
    {href:"/",          icon:"🔗", label:"Data Sources", desc:"Connect folders, databases & APIs so Claude can read them.",
     active:function(p){return p==="/"||p===""||p.indexOf("/index")===0;}},
    {href:"/hub/ports", icon:"🔌", label:"Apps & Ports", desc:"Every app gets its own ports automatically — nothing clashes.",
     active:function(p){return p.indexOf("/hub/ports")===0;}},
    {href:"/hub/panel", icon:"⚙️",  label:"Services", desc:"Start, stop and restart your apps safely.",
     active:function(p){return p.indexOf("/hub/panel")===0;}},
    {href:"/hub/packs", icon:"🛍️", label:"Design Director Packs", desc:"Your Design Director add-on licenses.",
     active:function(p){return p.indexOf("/hub/packs")===0;}}
  ];
  var path = location.pathname;
  // Theme variables for pages that don't embed them server-side (e.g. the
  // dashboard SPA) — duplicates on hub pages are identical, so harmless.
  var tvars = document.createElement("style");
  tvars.textContent = "__THEME_VARS__";
  document.head.appendChild(tvars);

  // Favicon (Selran hexagon) for every Hub page, theme-neutral green.
  if (!document.querySelector("link[rel~='icon']")) {
    var favSvg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
      + '<polygon points="50,4 90,27 90,73 50,96 10,73 10,27" fill="#10b981"/>'
      + '<polygon points="50,22 74,36 74,64 50,78 26,64 26,36" fill="#0c0c10"/></svg>';
    var fav = document.createElement("link");
    fav.rel = "icon";
    fav.href = "data:image/svg+xml," + encodeURIComponent(favSvg);
    document.head.appendChild(fav);
  }
  var css = document.createElement("style");
  css.textContent = ""
   + "body{padding-top:0!important}"
   + "#selnav{position:sticky;top:0;z-index:9998;background:var(--sh-navbg,rgba(12,12,16,.94));backdrop-filter:saturate(140%) blur(8px);border-bottom:1px solid var(--sh-border2,#23232c);"
   + "font:14px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}"
   + "#selnav .bar{max-width:1180px;margin:0 auto;display:flex;align-items:center;gap:6px;padding:10px 20px;flex-wrap:wrap}"
   + "#selnav .logo{font-weight:700;color:var(--sh-text,#e8e8ec);text-decoration:none;margin-right:14px;font-size:15px;white-space:nowrap}"
   + "#selnav .logo .hx{color:var(--sh-ok,#5ee59a);margin-right:6px}"
   + "#selnav a.tab{color:var(--sh-text3,#b9b9c4);text-decoration:none;padding:7px 13px;border-radius:8px;white-space:nowrap}"
   + "#selnav a.tab:hover{background:var(--sh-hover,#17171d);color:var(--sh-text,#e8e8ec)}"
   + "#selnav a.tab.on{background:var(--sh-hover,#17171d);color:var(--sh-text,#e8e8ec);font-weight:600}"
   + "#selnav .grow{flex:1}"
   + "#selnav .status{display:flex;align-items:center;gap:7px;color:var(--sh-muted,#9b9ba6);font-size:12.5px;white-space:nowrap}"
   + "#selnav .dot{width:8px;height:8px;border-radius:50%;background:var(--sh-ok,#5ee59a);box-shadow:0 0 0 3px rgba(94,229,154,.15)}"
   + "#selnav .dot.off{background:var(--sh-bad,#ff8d96);box-shadow:0 0 0 3px rgba(255,141,150,.15)}"
   + "#selnav .help{color:var(--sh-link,#86b3ff);text-decoration:none;font-size:12.5px;margin-left:12px}"
   + "#selnav button.theme{background:transparent;color:var(--sh-muted,#9b9ba6);border:1px solid var(--sh-border,#2a2a33);"
   + "border-radius:8px;padding:5px 11px;font:inherit;font-size:12.5px;cursor:pointer;margin-left:10px;white-space:nowrap}"
   + "#selnav button.theme:hover{color:var(--sh-text,#e8e8ec);border-color:var(--sh-border4,#6a6a7a)}";
  document.head.appendChild(css);

  function esc(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML;}
  var tabs = PAGES.map(function(pg){
    var on = pg.active(path) ? " on" : "";
    return '<a class="tab'+on+'" href="'+pg.href+'">'+pg.icon+'  '+esc(pg.label)+'</a>';
  }).join("");
  var nav = document.createElement("div");
  nav.id = "selnav";
  nav.innerHTML = '<div class="bar">'
    + '<a class="logo" href="/"><span class="hx">⬢</span>Selran Hub</a>'
    + tabs
    + '<span class="grow"></span>'
    + '<span class="status" id="selstatus"><span class="dot"></span>checking…</span>'
    + '<button class="theme" id="selantheme" title="Theme: follows your system, or pin dark/light"></button>'
    + '<a class="help" href="https://github.com/apourmd941/selran-hub/blob/main/USER_GUIDE.md" target="_blank">ℹ Guide</a>'
    + '</div>';
  document.body.insertBefore(nav, document.body.firstChild);

  var tbtn = document.getElementById("selantheme");
  tbtn.textContent = tlabel(tcur);
  tbtn.addEventListener("click", function(){
    tcur = TORDER[(TORDER.indexOf(tcur) + 1) % TORDER.length];
    try { localStorage.setItem(TKEY, tcur); } catch(e){}
    tapply();
    tbtn.textContent = tlabel(tcur);
  });

  function refresh(){
    var st = document.getElementById("selstatus");
    fetch("/hub/health").then(function(r){return r.json();}).then(function(h){
      var running = (h.services||[]).filter(function(s){return s.state==="running";}).length;
      fetch("/v1/report").then(function(r){return r.json();}).then(function(rep){
        st.innerHTML = '<span class="dot"></span>Running · v'+esc(h.version)
          +'  ·  '+rep.app_count+' apps · '+running+' services';
      }).catch(function(){ st.innerHTML = '<span class="dot"></span>Running · v'+esc(h.version); });
    }).catch(function(){ st.innerHTML = '<span class="dot off"></span>Not responding'; });
  }
  refresh(); setInterval(refresh, 5000);
})();
"""


@router.get("/hub/nav.js")
async def hub_nav_js():
    from fastapi.responses import Response
    content = _NAV_JS.replace("__THEME_VARS__", " ".join(THEME_CSS.split()))
    return Response(content=content, media_type="application/javascript")


_PORTS_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Selran Hub — Apps & Ports</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>""" + THEME_CSS + """
 body{font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--sh-bg);color:var(--sh-text);margin:0;padding:0 24px 60px}
 .wrap{max-width:1180px;margin:0 auto;padding-top:22px} h1{font-size:21px;margin:0 0 4px}
 .sub{color:var(--sh-muted);margin:0 0 20px;font-size:13.5px}
 .note{background:var(--sh-panel);border:1px solid var(--sh-border);border-left:3px solid var(--sh-ok);border-radius:8px;padding:12px 16px;color:var(--sh-text3);font-size:13.5px;margin-bottom:18px}
 table{width:100%;border-collapse:collapse;background:var(--sh-panel);border:1px solid var(--sh-border);border-radius:10px;overflow:hidden}
 th,td{padding:10px 14px;text-align:left;border-bottom:1px solid var(--sh-border2);font-size:13.5px}
 th{color:var(--sh-muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.06em}
 code{background:var(--sh-panel2);padding:2px 7px;border-radius:5px;color:var(--sh-link)}
 .empty{padding:26px;text-align:center;color:var(--sh-muted)}
 .btn-acc{background:var(--sh-accent);color:var(--sh-accent-fg);border:0;border-radius:8px;padding:9px 16px;font-size:14px;font-weight:600;cursor:pointer}
 .formbox{display:none;margin-top:12px;background:var(--sh-panel);border:1px solid var(--sh-border);border-radius:10px;padding:16px;max-width:560px}
 .formbox input{width:100%;box-sizing:border-box;background:var(--sh-panel2);border:1px solid var(--sh-border);border-radius:7px;padding:9px 12px;color:var(--sh-text);margin-bottom:8px;font-size:14px}
 .formhint{font-size:13px;color:var(--sh-muted);margin-bottom:10px}
 .inuse{cursor:pointer;color:var(--sh-link);text-decoration:underline}
 .apdet td{background:var(--sh-panel2,#16161c);padding:10px 16px}
 .cov{margin:0 0 8px;padding:7px 11px;border-radius:7px;font-size:12.5px}
 .cov.partial{background:var(--sh-badbg,#3a1d1d);color:var(--sh-bad,#e57373)}
 .cov.complete{background:var(--sh-okbg,#16301f);color:var(--sh-ok,#4caf82)}
 .ppid{font-size:12.5px;padding:5px 0;border-bottom:1px solid var(--sh-border2);font-family:ui-monospace,Menlo,monospace;word-break:break-all}
 .ppid .tag{font-family:-apple-system,sans-serif;font-size:11px;font-weight:600;padding:1px 7px;border-radius:10px;margin-right:6px;background:var(--sh-border);color:var(--sh-text3)}
 .ppid .tag.orphan{background:var(--sh-accentbg,#2a2410);color:var(--sh-warn,#caa14b)}
</style></head><body><div class="wrap">
<h1>Apps & Ports</h1>
<p class="sub">Every app that asks the Hub gets its own block of ports, so two apps never try to use the same one.</p>
<div class="note">This list lives only on <strong>your</strong> computer (in your home folder) — it is never uploaded or shared. You don't manage it by hand; apps ask the Hub for ports automatically. Building a new app and want to reserve it a port block? Use <strong>Register an app</strong> below.</div>
<div style="margin:0 0 18px">
 <button id="addbtn" class="btn-acc">+ Register an app</button>
 <div id="addform" class="formbox">
  <div class="formhint">Give your app a name and its folder. The Hub reserves it a block of ports that won't clash with anything else.</div>
  <input id="aname" placeholder="app name (e.g. my-new-app)">
  <input id="apath" placeholder="folder (e.g. /Users/you/projects/my-new-app)" style="margin-bottom:10px">
  <button id="asave" class="btn-acc" style="padding:8px 14px;font-size:13px;border-radius:7px">Reserve ports</button>
  <span id="amsg" style="margin-left:10px;font-size:13px;color:var(--sh-muted)"></span>
 </div>
</div>
<table><thead><tr><th>App</th><th>Main port</th><th>All ports</th><th>Location</th><th>In use</th></tr></thead>
<tbody id="rows"><tr><td colspan="5" class="empty">Loading…</td></tr></tbody></table>
</div>
<script src="/hub/nav.js"></script>
<script>
function esc(s){var d=document.createElement('div');d.textContent=s==null?'':String(s);return d.innerHTML;}
fetch("/v1/report").then(r=>r.json()).then(d=>{
  var apps=(d.apps||[]).slice().sort((a,b)=>a.range[0]-b.range[0]);
  var tb=document.getElementById("rows");
  if(!apps.length){tb.innerHTML='<tr><td colspan="5" class="empty">No apps have requested ports yet.</td></tr>';return;}
  tb.innerHTML=apps.map(a=>`<tr>
    <td><strong>${esc(a.app_id)}</strong></td>
    <td><code>${a.range[0]}</code></td>
    <td>${a.range[0]}–${a.range[1]}</td>
    <td style="color:#8a8a96">${esc(a.path||"")}</td>
    <td><span class="inuse" onclick="scanApp('${esc(a.app_id)}')">check</span></td></tr>
   <tr class="apdet" id="ad-${esc(a.app_id)}" style="display:none"><td colspan="5" id="ap-${esc(a.app_id)}"></td></tr>`).join("");
});
async function scanApp(id){
  var det=document.getElementById("ad-"+CSS.escape(id)), cell=document.getElementById("ap-"+CSS.escape(id));
  if(det.style.display!=="none"){ det.style.display="none"; return; }
  det.style.display=""; cell.textContent="Scanning…";
  var r=await fetch("/v1/apps/"+encodeURIComponent(id)+"/pids"); var d=await r.json();
  if(d.status!=="ok"){ cell.innerHTML='<div class="cov partial">'+esc(d.message||"scan failed")+'</div>'; return; }
  var cov = d.coverage==="partial"
    ? '<div class="cov partial">⚠ Could not see every listener'+((d.occupied_owner_not_visible&&d.occupied_owner_not_visible.length)?(' — port(s) '+d.occupied_owner_not_visible.join(", ")+' are in use but owned by another user or root'):'')+'. Not an "all clear".</div>'
    : '<div class="cov complete">All listeners on this app\'s ports are accounted for.</div>';
  var list = (!d.pids||!d.pids.length)
    ? '<div style="color:var(--sh-muted);font-size:12.5px">No processes found on these ports.</div>'
    : d.pids.map(function(p){
        var tag=p.role==="orphan"?'<span class="tag orphan">orphan</span>':(p.role==="current"?'<span class="tag" style="color:var(--sh-ok,#4caf82)">current</span>':'<span class="tag">'+esc(p.classification)+'</span>');
        return '<div class="ppid">'+tag+'pid '+p.pid+(p.ports&&p.ports.length?(' · :'+p.ports.join(",:")):'')+(p.owner?(' · '+esc(p.owner)):'')+'<br><code>'+esc(p.command)+'</code></div>';
      }).join("");
  var foot = (d.pids&&d.pids.some(function(p){return p.offer_stop;}))
    ? '<div style="font-size:12px;color:var(--sh-muted);margin-top:8px">To stop an orphan, open <a href="/hub/panel" style="color:var(--sh-link)">Services</a>.</div>' : '';
  cell.innerHTML=cov+list+foot;
}
document.getElementById("addbtn").onclick=function(){var f=document.getElementById("addform");f.style.display=f.style.display==="none"?"block":"none";};
document.getElementById("asave").onclick=function(){
  var name=document.getElementById("aname").value.trim(), path=document.getElementById("apath").value.trim(), msg=document.getElementById("amsg");
  if(!name||!path){msg.textContent="Enter a name and a folder.";return;}
  msg.textContent="Reserving…";
  fetch("/v1/ensure",{method:"POST",headers:{"Content-Type":"application/json","X-Selran-Local":"1"},body:JSON.stringify({app_id:name,path:path})})
   .then(r=>r.json()).then(d=>{ if(d.range){msg.textContent="✓ Reserved ports "+d.range[0]+"–"+d.range[1];setTimeout(function(){location.reload();},900);} else {msg.textContent=d.message||"Could not reserve.";} })
   .catch(function(){msg.textContent="Error reaching the Hub.";});
};
</script></body></html>"""


@router.get("/hub/ports")
async def hub_ports_page():
    from fastapi.responses import HTMLResponse as _HTML
    return _HTML(_PORTS_PAGE)


# --------------------------------------------------------------------------
# Pack detail + example previews (reads installed pack content; never ships it)
# --------------------------------------------------------------------------

@router.get("/v1/packs/{name}")
async def pack_detail(name: str):
    det = packs_mod.pack_detail(name)
    ent = _entitlements.check(name if name.startswith("pack-") else "pack-" + name)
    det["entitled"] = bool(ent.get("entitled"))
    det["tier"] = ent.get("tier")
    return det


@router.get("/hub/packs/{name}/screen/{filename}")
async def pack_screen(name: str, filename: str):
    from fastapi.responses import HTMLResponse, Response
    html = packs_mod.screen_html(name, filename)
    if html is None:
        return Response(status_code=404, content="not found")
    return HTMLResponse(html)


def _bundled_identity(product: str) -> dict:
    """The catalog-shipped visual identity for a pack — the fallback that
    keeps the gallery and detail pages colorful for users who don't have the
    pack installed (which is exactly when those pages matter most)."""
    import json as _json
    from pathlib import Path as _Path
    try:
        catalog = _json.loads((_Path(__file__).parent / "pack_catalog.json").read_text())
    except (OSError, ValueError):
        return {}
    for p in catalog.get("packs", []):
        if p.get("product") == product:
            return p.get("identity") or {}
    return {}


@router.get("/hub/packs/{name}")
async def pack_detail_page(name: str):
    from fastapi.responses import HTMLResponse
    det = packs_mod.pack_detail(name)
    product = name if name.startswith("pack-") else "pack-" + name
    ent = _entitlements.check(product)
    owned = bool(ent.get("entitled"))
    base = name[5:] if name.startswith("pack-") else name
    title = det.get("display_name") or base.replace("-", " ").title()
    desc = det.get("description") or "A Selran Design Director add-on pack."
    price = det.get("price_usd")
    homepage = det.get("homepage") or f"https://selran.design/packs/{base}"
    screens = det.get("screens", [])
    comp_n = det.get("component_count", 0)
    ident = det.get("identity") or {}
    if not ident.get("accent"):
        ident = _bundled_identity(product)
    pa = ident.get("accent") or "#2f81f7"  # page accent = the pack's own accent

    import json as _json
    badge = (f'<span class="own">✓ You own this — {ent.get("tier")}</span>' if owned
             else (f'<a class="buy" href="{homepage}" target="_blank">Get this pack'
                   + (f' — ${price}' if price else '') + ' →</a>'))

    # Multi-page example viewer: the pack's own (hand-authored) app screens
    # come first, then the generated artifact pages in a fixed story order —
    # app screen → website → presentation → charts → document.
    _ARTIFACTS = {
        "01-app.sample.html": ("App screen", 780),
        "02-website.sample.html": ("Website", 820),
        "03-presentation.sample.html": ("Presentation", 880),
        "04-charts.sample.html": ("Charts & data", 880),
        "05-document.sample.html": ("Document", 1150),
    }
    pages_list = []
    for s in screens:
        if s not in _ARTIFACTS:
            label = s.replace(".sample.html", "").replace(".html", "").replace("-", " ").title()
            pages_list.append({"file": s, "label": f"App: {label}", "h": 780})
    for fn, (label, h) in _ARTIFACTS.items():
        if fn in screens:
            pages_list.append({"file": fn, "label": label, "h": h})

    if pages_list:
        tabs = "".join(
            f'<button class="vtab{" on" if i == 0 else ""}" data-i="{i}">{p["label"]}</button>'
            for i, p in enumerate(pages_list))
        first = pages_list[0]
        gallery_block = f"""<h2>What this pack makes ({len(pages_list)} example pages)</h2>
<div class="viewer">
 <div class="vtabs">{tabs}</div>
 <iframe id="vframe" sandbox="allow-scripts" src="/hub/packs/{base}/screen/{first["file"]}" style="height:{first["h"]}px"></iframe>
 <div class="vpager">
  <button id="vprev" disabled>← Previous</button>
  <span id="vpos" class="vpos">1 / {len(pages_list)}</span>
  <button id="vnext"{"" if len(pages_list) > 1 else " disabled"}>Next →</button>
 </div>
</div>"""
    elif det.get("present"):
        gallery_block = '<p class="muted">This pack has no sample screens to preview.</p>'
    else:
        gallery_block = ('<div class="note">Install this pack to preview its example pages here. '
                         f'<a href="{homepage}" target="_blank">See examples on selran.design →</a></div>')

    viewer_js = """
<script>
(function(){
  var PAGES = __PAGES__, BASE = "__BASE__", i = 0;
  var frame = document.getElementById("vframe");
  if (!frame) return;
  var tabs = Array.prototype.slice.call(document.querySelectorAll(".vtab"));
  var prev = document.getElementById("vprev"), next = document.getElementById("vnext");
  var pos = document.getElementById("vpos");
  function show(n){
    if (n < 0 || n >= PAGES.length) return;
    i = n;
    frame.src = "/hub/packs/" + BASE + "/screen/" + PAGES[i].file;
    frame.style.height = PAGES[i].h + "px";
    tabs.forEach(function(t, k){ t.className = "vtab" + (k === i ? " on" : ""); });
    pos.textContent = (i + 1) + " / " + PAGES.length;
    prev.disabled = (i === 0); next.disabled = (i === PAGES.length - 1);
  }
  tabs.forEach(function(t){ t.addEventListener("click", function(){ show(parseInt(t.dataset.i, 10)); }); });
  prev.addEventListener("click", function(){ show(i - 1); });
  next.addEventListener("click", function(){ show(i + 1); });
  document.addEventListener("keydown", function(e){
    if (e.key === "ArrowLeft") show(i - 1);
    if (e.key === "ArrowRight") show(i + 1);
  });
})();
</script>""".replace("__PAGES__", _json.dumps(pages_list)).replace("__BASE__", base) if pages_list else ""

    swatches = ""
    for c in (ident.get("swatches") or ident.get("palette") or []):
        swatches += f'<span class="sw" style="background:{c}" title="{c}"></span>'
    identity_block = ""
    if ident:
        chips = ""
        if ident.get("direction"):
            chips += f'<span class="chip">🎨 {ident["direction"].replace("-"," ")}</span>'
        if ident.get("feel"):
            chips += f'<span class="chip">🔤 {ident["feel"]}</span>'
        accent_lbl = f'<code>{ident["accent"]}</code>' if ident.get("accent") else ""
        identity_block = (f'<div class="identity"><div class="swrow">{swatches}</div>'
                          f'<div class="idmeta">{chips} {accent_lbl}</div></div>')

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Selran Hub — {title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>{THEME_CSS}
 body{{font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--sh-bg);color:var(--sh-text);margin:0;padding:0 24px 60px}}
 .wrap{{max-width:1180px;margin:0 auto;padding-top:22px}}
 a.back{{color:var(--sh-link);text-decoration:none;font-size:13px}}
 h1{{font-size:24px;margin:14px 0 2px}} .price{{color:var(--sh-muted);font-size:14px}}
 .lead{{color:var(--sh-text2);font-size:15px;max-width:70ch;margin:12px 0 16px}}
 .own{{display:inline-block;background:var(--sh-okbg);color:var(--sh-ok);padding:7px 14px;border-radius:20px;font-size:13px;font-weight:600}}
 a.buy{{display:inline-block;background:{pa};color:#fff;padding:8px 16px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:600}}
 .meta{{color:var(--sh-muted2);font-size:13px;margin:8px 0 22px}}
 h2{{font-size:15px;color:var(--sh-muted);margin:26px 0 12px}}
 .note{{background:var(--sh-panel);border:1px solid var(--sh-border);border-left:3px solid var(--sh-link);border-radius:8px;padding:14px 16px;color:var(--sh-text2);font-size:14px}}
 .muted{{color:var(--sh-muted2)}}
 .viewer{{background:var(--sh-panel);border:1px solid var(--sh-border);border-radius:12px;overflow:hidden}}
 .vtabs{{display:flex;flex-wrap:wrap;gap:4px;padding:10px 12px;border-bottom:1px solid var(--sh-border2)}}
 .vtab{{background:transparent;color:var(--sh-text3);border:1px solid transparent;border-radius:8px;padding:7px 13px;font-size:13px;cursor:pointer}}
 .vtab:hover{{background:var(--sh-hover);color:var(--sh-text)}}
 .vtab.on{{background:{pa};color:#fff;font-weight:600}}
 #vframe{{width:100%;border:0;background:#fff;display:block}}
 .vpager{{display:flex;align-items:center;justify-content:center;gap:16px;padding:10px;border-top:1px solid var(--sh-border2)}}
 .vpager button{{background:var(--sh-btn);color:var(--sh-text);border:1px solid var(--sh-border3);border-radius:7px;padding:7px 14px;font-size:13px;cursor:pointer}}
 .vpager button:disabled{{opacity:.4;cursor:default}}
 .vpos{{color:var(--sh-muted);font-size:12.5px;font-variant-numeric:tabular-nums}}
 .identity{{background:var(--sh-panel);border:1px solid var(--sh-border);border-radius:12px;padding:16px 18px;margin:6px 0 18px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}}
 .swrow{{display:flex;gap:0;border-radius:8px;overflow:hidden;box-shadow:0 0 0 1px var(--sh-border)}}
 .sw{{width:46px;height:46px;display:inline-block}}
 .idmeta{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:13px}}
 .chip{{background:var(--sh-panel2);border:1px solid var(--sh-border);border-radius:20px;padding:5px 11px;color:var(--sh-text2)}}
 .chip code{{background:transparent;color:var(--sh-muted)}}
 a.buy,.own{{--pa:{pa}}}
</style></head><body>
<script src="/hub/nav.js"></script>
<div class="wrap">
<a class="back" href="/hub/packs">← All packs</a>
<h1>{title}</h1>
<div class="price">{('$'+str(price)) if price else 'Design Director add-on pack'}</div>
<p class="lead">{desc}</p>
{identity_block}
<div>{badge}</div>
<div class="meta">{comp_n} components{(' · '+str(len(pages_list))+' example pages') if pages_list else ''}</div>
{gallery_block}
</div>
{viewer_js}
</body></html>"""
    return HTMLResponse(page)

"""Selran Hub audit panel (spec §7, M4) — Greenloop's live run dashboard.

Greenloop (app-audit / audit-fix) streams small structured events as a run
progresses; the Hub derives state and serves a live page. The skill never
renders dashboard HTML — it sends JSON facts ({"type":"finding", ...}),
which keeps the model-side cost of live visibility near zero.

Event types:
  phase    {type, phase}                          — a phase began
  item     {type, category, item, verdict?}       — checklist item progress
  finding  {type, severity, title, location?, category?}
  fix      {type, title, status, location?}       — audit-fix progress
            status: fixed | deferred | reverted | failed
  note     {type, text}
  complete {type, summary?}                       — run finished

Runs are in-memory and ephemeral, like studio sessions: a Hub restart clears
them, and Greenloop's fallback (text-mode status blocks) already covers
absence.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any

MAX_RUNS = 20
RUN_TTL_SECONDS = 12 * 60 * 60

SEVERITIES = ("critical", "high", "medium", "low", "info")
FIX_STATUSES = ("fixed", "deferred", "reverted", "failed")


@dataclass
class AuditRun:
    run_id: str
    title: str
    repo: str
    scope: list[str]
    version: int = 1
    status: str = "running"  # running | completed
    phase: str = ""
    current_item: str = ""
    items_checked: int = 0
    findings: list[dict[str, Any]] = field(default_factory=list)
    fixes: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    summary: str = ""
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.monotonic)

    def severity_counts(self) -> dict[str, int]:
        counts = {s: 0 for s in SEVERITIES}
        for f in self.findings:
            counts[f["severity"]] = counts.get(f["severity"], 0) + 1
        return counts

    def to_state(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "id": self.run_id,
            "title": self.title,
            "repo": self.repo,
            "scope": self.scope,
            "run_status": self.status,
            "phase": self.phase,
            "current_item": self.current_item,
            "items_checked": self.items_checked,
            "severity_counts": self.severity_counts(),
            "findings": self.findings,
            "fixes": self.fixes,
            "notes": self.notes[-20:],
            "summary": self.summary,
            "started_at": self.started_at,
            "version": self.version,
        }


class AuditPanelManager:
    def __init__(self) -> None:
        self._runs: dict[str, AuditRun] = {}

    def _sweep(self) -> None:
        now = time.monotonic()
        for k in [k for k, r in self._runs.items() if now - r.updated_at > RUN_TTL_SECONDS]:
            del self._runs[k]
        while len(self._runs) >= MAX_RUNS:
            oldest = min(self._runs.values(), key=lambda r: r.updated_at)
            del self._runs[oldest.run_id]

    def create(self, title: str, repo: str = "", scope: list[str] | None = None) -> AuditRun:
        if not title.strip():
            raise ValueError("title is required")
        self._sweep()
        rid = secrets.token_urlsafe(8)
        run = AuditRun(run_id=rid, title=title, repo=repo, scope=list(scope or []))
        self._runs[rid] = run
        return run

    def get(self, run_id: str) -> AuditRun | None:
        return self._runs.get(run_id)

    def append_events(self, run_id: str, events: list[dict[str, Any]]) -> AuditRun:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if not isinstance(events, list) or not events:
            raise ValueError("events must be a non-empty list")
        for ev in events:
            if not isinstance(ev, dict):
                raise ValueError("each event must be an object")
            etype = str(ev.get("type", ""))
            if etype == "phase":
                run.phase = str(ev.get("phase", ""))
                run.current_item = ""
            elif etype == "item":
                run.items_checked += 1
                cat = str(ev.get("category", ""))
                item = str(ev.get("item", ""))
                run.current_item = f"{cat}: {item}" if cat else item
            elif etype == "finding":
                sev = str(ev.get("severity", "")).lower()
                if sev not in SEVERITIES:
                    raise ValueError(f"finding severity must be one of {SEVERITIES}")
                if not str(ev.get("title", "")).strip():
                    raise ValueError("finding title is required")
                run.findings.append({
                    "severity": sev,
                    "title": str(ev["title"]),
                    "location": str(ev.get("location", "")),
                    "category": str(ev.get("category", "")),
                })
            elif etype == "fix":
                status = str(ev.get("status", "")).lower()
                if status not in FIX_STATUSES:
                    raise ValueError(f"fix status must be one of {FIX_STATUSES}")
                if not str(ev.get("title", "")).strip():
                    raise ValueError("fix title is required")
                run.fixes.append({
                    "title": str(ev["title"]),
                    "status": status,
                    "location": str(ev.get("location", "")),
                })
            elif etype == "note":
                run.notes.append(str(ev.get("text", "")))
            elif etype == "complete":
                run.status = "completed"
                run.summary = str(ev.get("summary", ""))
            else:
                raise ValueError(f"unknown event type: {etype!r}")
        run.version += 1
        run.updated_at = time.monotonic()
        return run

    def summary(self) -> dict[str, Any]:
        return {"active_runs": len(self._runs)}


PANEL_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>__TITLE__ — Greenloop live panel</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>__THEME_CSS__
 body{font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--sh-bg);color:var(--sh-text);margin:0;padding:32px 22px}
 .wrap{max-width:980px;margin:0 auto}
 h1{font-size:21px;margin:0} .sub{color:var(--sh-muted);margin:4px 0 18px;font-size:13.5px}
 .row{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px}
 .card{background:var(--sh-panel);border:1px solid var(--sh-border);border-radius:10px;padding:14px 16px;flex:1;min-width:150px}
 .card .k{color:var(--sh-muted);font-size:11px;text-transform:uppercase;letter-spacing:.07em}
 .card .v{font-size:18px;font-weight:650;margin-top:3px}
 .sev{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11.5px;font-weight:700;text-transform:uppercase}
 .critical{background:var(--sh-badbg);color:var(--sh-bad)}.high{background:var(--sh-badbg);color:var(--sh-bad)}
 .medium{background:var(--sh-warnbg);color:var(--sh-warn)}.low{background:var(--sh-accentbg);color:var(--sh-link)}.info{background:var(--sh-border);color:var(--sh-text3)}
 .fixed{background:var(--sh-okbg);color:var(--sh-ok)}.deferred{background:var(--sh-warnbg);color:var(--sh-warn)}
 .reverted{background:var(--sh-badbg);color:var(--sh-bad)}.failed{background:var(--sh-badbg);color:var(--sh-bad)}
 table{width:100%;border-collapse:collapse;background:var(--sh-panel);border:1px solid var(--sh-border);border-radius:10px;overflow:hidden;margin-bottom:18px}
 th,td{padding:9px 13px;text-align:left;border-bottom:1px solid var(--sh-border2);font-size:13.5px}
 th{color:var(--sh-muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.06em}
 .pulse{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--sh-ok);margin-right:7px;animation:p 1.6s infinite}
 @keyframes p{50%{opacity:.25}} .done .pulse{animation:none;background:var(--sh-link)}
 .empty{padding:20px;text-align:center;color:var(--sh-muted)}
</style>
<script>(function(){try{var p=localStorage.getItem("selran-theme")||"system";var r=p==="system"?(window.matchMedia&&matchMedia("(prefers-color-scheme: light)").matches?"light":"dark"):p;document.documentElement.setAttribute("data-theme",r);}catch(e){}})();</script>
</head><body><div class="wrap" id="root">
<h1><span class="pulse"></span><span id="title">__TITLE__</span></h1>
<p class="sub" id="sub">connecting…</p>
<div class="row">
 <div class="card"><div class="k">Phase</div><div class="v" id="phase">—</div></div>
 <div class="card"><div class="k">Items checked</div><div class="v" id="items">0</div></div>
 <div class="card"><div class="k">Findings</div><div class="v" id="fcount">0</div></div>
 <div class="card"><div class="k">Now checking</div><div class="v" id="current" style="font-size:13.5px;font-weight:500">—</div></div>
</div>
<div class="row" id="sevrow"></div>
<h3 style="font-size:14px;color:#9b9ba6">Findings</h3>
<table><thead><tr><th>Severity</th><th>Title</th><th>Location</th><th>Category</th></tr></thead>
<tbody id="findings"><tr><td colspan="4" class="empty">None yet</td></tr></tbody></table>
<h3 style="font-size:14px;color:#9b9ba6">Fix progress</h3>
<table><thead><tr><th>Status</th><th>Fix</th><th>Location</th></tr></thead>
<tbody id="fixes"><tr><td colspan="3" class="empty">No fixes yet</td></tr></tbody></table>
</div><script>
(function(){
 var RID="__RID__", V=0;
 function esc(x){var d=document.createElement("div");d.textContent=x==null?"":String(x);return d.innerHTML;}
 function load(){
  fetch("/v1/audit/runs/"+RID+"?since="+V).then(function(r){return r.json();}).then(function(d){
   if(d.status==="unchanged")return;
   if(d.status!=="ok")return;
   V=d.version;
   document.getElementById("title").textContent=d.title;
   document.getElementById("sub").textContent=(d.repo?d.repo+" — ":"")+(d.run_status==="completed"?("completed. "+(d.summary||"")):"running ("+(d.scope||[]).join(", ")+")");
   if(d.run_status==="completed")document.getElementById("root").classList.add("done");
   document.getElementById("phase").textContent=d.phase||"—";
   document.getElementById("items").textContent=d.items_checked;
   document.getElementById("fcount").textContent=d.findings.length;
   document.getElementById("current").textContent=d.current_item||"—";
   var sevs=["critical","high","medium","low","info"];
   document.getElementById("sevrow").innerHTML=sevs.map(function(s){
    return '<div class="card"><div class="k">'+s+'</div><div class="v"><span class="sev '+s+'">'+(d.severity_counts[s]||0)+"</span></div></div>";}).join("");
   document.getElementById("findings").innerHTML=d.findings.length?d.findings.map(function(f){
    return "<tr><td><span class='sev "+esc(f.severity)+"'>"+esc(f.severity)+"</span></td><td>"+esc(f.title)+"</td><td>"+esc(f.location)+"</td><td>"+esc(f.category)+"</td></tr>";}).join("")
    :'<tr><td colspan="4" class="empty">None yet</td></tr>';
   document.getElementById("fixes").innerHTML=d.fixes.length?d.fixes.map(function(f){
    return "<tr><td><span class='sev "+esc(f.status)+"'>"+esc(f.status)+"</span></td><td>"+esc(f.title)+"</td><td>"+esc(f.location)+"</td></tr>";}).join("")
    :'<tr><td colspan="3" class="empty">No fixes yet</td></tr>';
  }).catch(function(){});
 }
 load(); setInterval(load, 2000);
})();
</script></body></html>"""


def render_panel(run: AuditRun) -> str:
    from .theme import THEME_CSS

    return (PANEL_PAGE
            .replace("__THEME_CSS__", THEME_CSS)
            .replace("__TITLE__", run.title.replace("<", "&lt;"))
            .replace("__RID__", run.run_id))

"""Selran Hub design studio (spec §7, M3) — interactive choice over localhost.

The generic mechanism that turns a skill's rendered HTML into a LIVE page:
a skill posts HTML, the Hub serves it at a URL, the user clicks an element
carrying a `data-choice` attribute, and the skill polls the choice back —
no typing, no copy-paste. Updates can be pushed so an open page re-renders
in place (live design-partner mode).

Sessions are in-memory and ephemeral by design: a Hub restart clears them,
and skills already handle absence via their capability-ladder fallback.

Conventions for skill-provided HTML:
  - clickable options carry `data-choice="<value to send back>"`
  - the Hub wraps the HTML with the click/poll script; skills ship none
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

MAX_SESSIONS = 50
SESSION_TTL_SECONDS = 4 * 60 * 60  # stale-session sweep horizon


@dataclass
class StudioSession:
    session_id: str
    title: str
    html: str
    version: int = 1
    choice: str | None = None
    choice_at: float | None = None
    created_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.monotonic)


class StudioManager:
    def __init__(self) -> None:
        self._sessions: dict[str, StudioSession] = {}

    def _sweep(self) -> None:
        now = time.monotonic()
        stale = [k for k, s in self._sessions.items() if now - s.updated_at > SESSION_TTL_SECONDS]
        for k in stale:
            del self._sessions[k]
        while len(self._sessions) >= MAX_SESSIONS:
            oldest = min(self._sessions.values(), key=lambda s: s.updated_at)
            del self._sessions[oldest.session_id]

    def create(self, title: str, html: str) -> StudioSession:
        if not html.strip():
            raise ValueError("html is required")
        self._sweep()
        sid = secrets.token_urlsafe(8)
        session = StudioSession(session_id=sid, title=title or "Selran Studio", html=html)
        self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> StudioSession | None:
        return self._sessions.get(session_id)

    def update_html(self, session_id: str, html: str) -> StudioSession:
        s = self._sessions.get(session_id)
        if s is None:
            raise KeyError(session_id)
        if not html.strip():
            raise ValueError("html is required")
        s.html = html
        s.version += 1
        s.updated_at = time.monotonic()
        # a new render invalidates a stale, unconsumed choice
        s.choice = None
        s.choice_at = None
        return s

    def record_choice(self, session_id: str, choice: str) -> StudioSession:
        s = self._sessions.get(session_id)
        if s is None:
            raise KeyError(session_id)
        s.choice = str(choice)
        s.choice_at = time.monotonic()
        s.updated_at = time.monotonic()
        return s

    def summary(self) -> dict[str, Any]:
        return {"active_sessions": len(self._sessions)}


# The wrapper page. The skill's HTML is NEVER injected into the Hub's own
# origin — it is rendered inside a SANDBOXED iframe (`sandbox="allow-scripts"`
# WITHOUT `allow-same-origin`), so it runs in a null origin: it cannot read the
# Hub's DOM, call /v1/* same-origin, or touch storage, even if the HTML is
# malicious or derived from an ingested external site. Clicks on [data-choice]
# elements are bridged to the parent (Hub origin) via postMessage; only the
# parent — same-origin — posts the choice to the API.
PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>__TITLE__ — Selran Studio</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>__THEME_CSS__
 html,body{margin:0;height:100%}
 #selran-studio-bar{position:fixed;top:0;left:0;right:0;z-index:99999;height:38px;box-sizing:border-box;
  background:var(--sh-bg);color:var(--sh-text);font:13px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  padding:9px 16px;display:flex;gap:10px;align-items:center;border-bottom:1px solid var(--sh-border)}
 #selran-studio-bar .dot{width:8px;height:8px;border-radius:50%;background:var(--sh-ok);flex:none}
 #selran-studio-bar.sent{background:var(--sh-okbg)}
 #selran-frame{position:fixed;top:38px;left:0;right:0;bottom:0;width:100%;border:0;background:#fff}
</style>
<script>(function(){try{var p=localStorage.getItem("selran-theme")||"system";var r=p==="system"?(window.matchMedia&&matchMedia("(prefers-color-scheme: light)").matches?"light":"dark"):p;document.documentElement.setAttribute("data-theme",r);}catch(e){}})();</script>
</head><body>
<div id="selran-studio-bar"><span class="dot"></span><span id="selran-studio-msg">
Selran Studio — click an option to send it to Claude. This page updates live.</span></div>
<iframe id="selran-frame" sandbox="allow-scripts"></iframe>
<script>
(function(){
  var SID = "__SID__", VERSION = __VERSION__;
  var INITIAL_HTML = __HTML_JSON__;
  var bar = document.getElementById("selran-studio-bar");
  var msg = document.getElementById("selran-studio-msg");
  var frame = document.getElementById("selran-frame");

  // Bridge injected INTO the sandboxed frame: wires data-choice clicks to a
  // postMessage up to this parent. Runs in a null origin — no Hub access.
  var BRIDGE =
    '<style>[data-choice]{cursor:pointer}[data-choice].selran-picked{outline:3px solid #5ee59a;outline-offset:2px}</style>' +
    '<script>document.addEventListener("click",function(e){var el=e.target.closest&&e.target.closest("[data-choice]");if(!el)return;e.preventDefault();' +
    'var p=document.querySelector("[data-choice].selran-picked");if(p)p.classList.remove("selran-picked");el.classList.add("selran-picked");' +
    'parent.postMessage({selranChoice:String(el.getAttribute("data-choice"))},"*");});<\\/script>';

  function setFrame(html){ frame.srcdoc = BRIDGE + html; }

  window.addEventListener("message", function(ev){
    if (ev.source !== frame.contentWindow) return;          // only our frame
    var d = ev.data;
    if (!d || typeof d.selranChoice !== "string") return;
    fetch("/v1/studio/sessions/" + SID + "/choice", {
      method: "POST", headers: {"Content-Type": "application/json", "X-Selran-Local": "1"},
      body: JSON.stringify({choice: d.selranChoice})
    }).then(function(){
      bar.classList.add("sent");
      msg.textContent = "✓ Sent to Claude: " + d.selranChoice + " — go back to the chat. (You can still click a different option.)";
    });
  });

  function poll(){
    fetch("/v1/studio/sessions/" + SID + "/content?since=" + VERSION)
      .then(function(r){ return r.json(); })
      .then(function(d){
        if (d.status === "ok" && d.version > VERSION) {
          VERSION = d.version;
          setFrame(d.html);
          bar.classList.remove("sent");
          msg.textContent = "Updated by Claude — click an option to answer.";
        }
      }).catch(function(){ /* hub briefly away; keep polling */ });
  }

  setFrame(INITIAL_HTML);
  setInterval(poll, 2000);
})();
</script></body></html>"""


def render_page(session: StudioSession) -> str:
    from .theme import THEME_CSS

    # JSON-encode the skill HTML so it lands as a safe JS string literal, and
    # neutralize "</" so it can't break out of the parent <script> block.
    html_json = json.dumps(session.html).replace("</", "<\\/")
    return (
        PAGE_TEMPLATE
        .replace("__THEME_CSS__", THEME_CSS)
        .replace("__TITLE__", session.title.replace("<", "&lt;"))
        .replace("__SID__", session.session_id)
        .replace("__VERSION__", str(session.version))
        .replace("__HTML_JSON__", html_json)
    )

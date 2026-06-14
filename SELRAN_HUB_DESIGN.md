# Selran Hub — Design Specification

**Version:** v1 (drafted 2026-06-10)
**Status:** v1 ACCEPTED — open questions resolved with Aidin 2026-06-10
**Owner:** Selran — Aidin Eslampour

The single local runtime for the Selran ecosystem: one download that every
Selran plugin detects and lights up against. Written §-numbered so app-audit
can generate its checklist from this document.

## 1. Overview

Selran ships free Claude plugins (Greenloop, Design Director, more coming).
Each works standalone, but their richer experiences — live design-studio
widgets, optional add-on packs, cross-app services — benefit from a local
runtime. Selran Hub is that runtime: one daemon, one well-known port, one
dashboard, one MCP bridge.

The design principle: **never gate a plugin's free core on a download; the Hub
only adds optional, enhanced experiences on top.** A plugin that detects the
Hub lights up extra capabilities; without it, the plugin still works fully.

## 2. Architectural decisions

### 2.1 Optionality is absolute
No free Selran plugin may ever require the Hub to perform its core function.
Plugins must degrade gracefully to their hub-less behavior in every case.
A plugin may *mention* the Hub at natural moments, at most once per session.

### 2.2 Local-first, localhost-only
The Hub must bind `127.0.0.1` only. It must have no cloud backend, no
telemetry without explicit opt-in, and no egress except features the user
explicitly configures with their own keys. User content must never be
required to leave the machine for any Hub function.

### 2.3 One daemon, one well-known port
The Hub must own port **11999** — the existing port-registry contract. Every
current Selran app already talks to `127.0.0.1:11999`; the Hub serves a
superset of that API, so shipping the Hub upgrades existing installs without
breaking them. The Hub must never require a second well-known port (all other
services get dynamic ports *from* it).

### 2.4 Evolution, not rewrite
The Hub is built by evolving **MCP-server-app** (FastAPI service + web
dashboard + thin stdio MCP bridge, MIT, already cross-platform) and absorbing
**app-port-registry** (the 1,012-line allocation service, rescued into this
repo) and the lifecycle discipline of the **app-startup** skill. No
from-scratch rewrite.

### 2.5 MIT core, entitlements later
The Hub core is MIT. Commercial pack entitlements (§10) are a later phase and
live behind their own module boundary so the core never depends on them.

## 3. Components and what they absorb

### 3.1 From MCP-server-app (the chassis)
The persistent FastAPI service, the web dashboard, the data-source registry
(folders/DuckDB/SQLite/REST), and the stdio MCP bridge pattern. These carry
over with rebranding (`Selran Hub`) and the port move from :8420 to :11999.

### 3.2 From app-port-registry (the allocation core)
All existing routes carry over verbatim under the same paths — `/health`,
`/v1/report`, `/v1/ensure`, `/v1/reclaim`, `/v1/archive`, `/v1/lookup`,
`/v1/apps/{id}`, `/v1/archived`. Existing clients (every Selran app, the
`app-port-registry` CLI, app-startup scripts) must keep working unmodified.

### 3.3 From app-startup (lifecycle discipline)
The skill stays a skill (and later ships inside the Hub's own plugin). Its
brain — safe process cleanup, verified process identity, scaffolded
start/stop scripts — becomes a Hub API (`/v1/services/*`) so the dashboard
and MCP tools can start/stop/restart registered services, not just allocate
their ports.

## 4. Detection contract (how plugins find the Hub)

### 4.1 The probe
`GET http://127.0.0.1:11999/hub/health` →

```json
{
  "hub": "selran",
  "version": "1.0.0",
  "api": 1,
  "capabilities": ["ports", "sources", "mcp", "services"],
  "services": [{"id": "design-studio", "state": "running", "port": 12345}]
}
```

Rules: the `hub` field must equal `"selran"` (distinguishes the Hub from the
bare port-registry, which serves `/health` but not `/hub/health`).
`capabilities` is the honesty contract — plugins must check it before using a
feature, exactly like cartographer's `state.json.capabilities`.

### 4.2 Probe discipline for plugins
- Timeout ≤ 250 ms; treat timeout/refusal/non-200 as "no Hub" silently.
- Never retry in a loop; probe at most once per relevant moment.
- Never tell the user the Hub is "missing" — only offer it where it would
  genuinely improve the next step, at most once per session (§2.1).

### 4.3 MCP surface
The Hub bridge exposes tools namespaced `selran_hub_*`. Plugins may ship an
`.mcp.json` pointing at the bridge; when the Hub is absent the server simply
fails to connect and the tools don't exist — which IS the graceful path.
Skills must therefore check tool availability, never assume it.

The bridge also exposes read-only **MCP resources** (H7) the client can list and
`@`-mention: `selran://sources` (the connected sources), the
`selran://sources/{name}/schema` template (tables/columns — attach before
querying), `selran://health`, and `selran://packs`. Resources are
application-driven (the user attaches them) and complement the model-driven
tools; each degrades to an `{"error": …}` JSON when the Hub is down. The bridge
sets FastMCP server **`instructions`** — the one server-side lever for Claude
Code's client-side **Tool Search** (which defers MCP tool schemas until needed);
the instructions tell Claude when to pull the Hub's tools in. Deferral itself is
client policy — no server flag controls it.

### 4.4 Interactive UI in the chat — MCP Apps / SEP-1865 (H2)
The bridge also exposes **MCP Apps** (SEP-1865, Final 2026-01-26): tools that
render an interactive HTML UI inline in the chat instead of a localhost browser
tab. A tool declares its UI via `_meta.ui.resourceUri` pointing at a pre-declared
`ui://` resource served at mimeType `text/html;profile=mcp-app`; a compatible
host renders it in a sandboxed iframe and bridges it over JSON-RPC-on-postMessage
(`ui/initialize` handshake → `ui/notifications/tool-result` data push →
`ui/message` choice back). Shipped surfaces:
- `design_picker` → `ui://selran/design-picker` — the seven Design Director
  directions as clickable cards; the pick is sent straight back to the chat.
  (The studio's reach without a localhost tab; also works on Claude.ai web,
  which can't reach loopback.)
- `data_sources_panel` → `ui://selran/data-sources` — the live connected
  sources as a clickable table.

Every UI tool ALSO returns complete `structuredContent` + a text/`instructions`
fallback, so the model can act when the UI is not rendered, and each resource is
self-contained (inline HTML/JS, no network — clean under the default MCP-Apps
CSP). **Honesty note (mid-2026):** MCP Apps is spec-Final and renders in Goose /
VS Code / ChatGPT, but Claude Desktop & claude.ai negotiate the capability yet do
NOT instantiate the iframe (open upstream bugs ext-apps#671, claude-ai-mcp#165),
and Claude Code is not a listed host. So in Claude this currently falls back to
the text/structured result; it lights up the moment Anthropic ships rendering.
This is forward-looking groundwork, built to spec and shape-verified over a live
stdio MCP session (it cannot be render-verified headlessly).

## 5. Surfaces

1. **Dashboard** (web, served by the daemon): sources, ports, services,
   installed Selran products, pack browser (later).
2. **REST API** (§3.2, §3.3, §4.1) — localhost only.
3. **MCP tools** via the stdio bridge (§4.3).
4. **CLI** `selran-hub` (status / start / stop / logs), absorbing the
   `app-port-registry` CLI as a compatibility alias.

## 6. Service directory

Registered Selran services with lifecycle state (`registered → starting →
running → stopping → stopped → failed`), port (from the allocator), health
URL, and start/stop commands. The Hub must verify process identity before
killing anything (the app-startup rule: never `kill` by port alone — confirm
the PID belongs to the expected command line).

### 6.1 Orphan-PID reaper (H1)

A leftover process from a *previous* version of an app — a re-parented child,
or a leader the Hub forgot after a crash — can keep holding a port and break the
next launch (parallel PID on the same port). The Hub surfaces and clears these
safely:

- **Show, read-only:** `GET /v1/services/{id}/pids` and `/v1/apps/{app_id}/pids`
  enumerate every PID associated with an app — *Source A* (listeners on its port
  range, via `lsof`) ∪ *Source B* (the Hub's recorded launches: recorded pid,
  process-group members, command-line matches, and launch-marker matches). Each
  PID is classified **owned / owned-unverified / ambiguous / foreign**.
- **Stop, identity-gated:** `POST /v1/services/{id}/pids/{pid}/stop` re-verifies
  a reuse-proof tuple `(pid, create_time, command)` atomically immediately before
  *each* signal (the PID-reuse guard the old cmdline-only check lacked).
- **Launch marker:** every Hub-launched child carries
  `SELRAN_HUB_INSTANCE=<service_id>:<launch_uuid>` in its environment — the
  strongest, unforgeable OWNED signal, recognising even an orphan from a prior
  launch. Marker match → one-click Stop (group-kill only for a recorded leader's
  own group, never the Hub's). Otherwise: `owner==me` + (recorded-command match
  OR currently on the app's ports) is **owned-unverified** — stoppable only with
  explicit `force` and a single-PID signal.
- **Never-touch:** `pid<=1`, the Hub itself / its ancestors / its own process
  group, a process owned by another user, and any process whose identity or
  `create_time` cannot be read are **foreign** — shown, never stoppable. The
  stop path fails closed when identity is unprovable (e.g. psutil absent).
- **Free vs blind:** an empty listener list is never reported as "all clear." A
  bind probe distinguishes a genuinely free port from one occupied by a listener
  the scanner lacks privilege to see (macOS non-root / foreign owner); such
  ports are surfaced as `coverage: partial` with an explicit "owner not visible"
  note, not silence.
- **Startup reconcile:** on construction the Hub marks any recorded-but-no-
  longer-alive runtime row stopped (so a stale row can't masquerade or block a
  restart) — and never sends a signal during reconcile.

Stopping is POSIX-only in this release (Windows enumeration is read-only;
signalling is hard-gated). The dashboard exposes the scan + Stop on the Services
panel and a read-only "In use" drill-in on Apps & Ports.

## 7. Plugin enhancement matrix

| Plugin | Without Hub (today, must keep working) | With Hub |
|---|---|---|
| Design Director | capability-ladder picker, full core | live design-studio widget, rendered previews served locally, commercial packs |
| Greenloop | full methodology | **live audit panel** — real-time phases, findings, and fix progress in the dashboard (included with the Hub; Greenloop's skill advertises it per §4.2 once the panel ships) |
| Future products | core function | one-line "connects to your Hub" |

Design Director v1.1 is the first consumer and the acceptance test for §4.

## 8. Security & privacy

- Localhost binding is a **must** (§2.2); the Hub must refuse to start bound
  to any non-loopback interface without an explicit
  `--i-understand-the-risk` flag.
- No telemetry without opt-in; opt-in telemetry must be local-first
  (file-based, user-inspectable) before any transmission.
- The Hub itself must never read or index user content; it brokers access
  (sources, ports, lifecycle) — the reading happens inside the user's Claude
  session as it does today.
- **Secrets live in the OS keychain (H5).** The API-key auth token and data-
  source credentials (API endpoint headers / bearer tokens) are stored via
  `secrets_store.py` in the OS keychain — macOS Keychain, Windows Credential
  Manager, or the Linux Secret Service. When no keychain backend is available
  (headless Linux), they fall back to a single owner-only (mode 0600) JSON file.
  `auth.json` / `sources.json` now hold only non-secret config (and are written
  0600); exports and API responses never carry credentials. Legacy plaintext
  secrets are migrated into the store on first read.
- **Remote transport is opt-in and authenticated (H8).** The daemon stays
  loopback-only (above). The MCP *bridge* can optionally run a remote transport
  (Streamable HTTP / legacy SSE) for a Claude client on another machine — but
  binding any non-loopback host REQUIRES `SELRAN_HUB_BRIDGE_TOKEN` (the bridge
  refuses to start otherwise), and every request must carry
  `Authorization: Bearer <token>` (constant-time compare) or get 401. Same rule
  closes the pre-existing SSE gap (it could bind `0.0.0.0` unauthenticated).
- PRIVACY.md ships in the repo from day one, same standard as the plugins.
- **Managed policy / MDM (H9).** An organization can lock down a managed machine
  with a read-only `managed-policy.json` deployed to a system location (macOS
  `/Library/Application Support/Selran Hub/`, Linux `/etc/selran-hub/`, Windows
  `%PROGRAMDATA%\Selran Hub\`; override `SELRAN_HUB_POLICY_FILE`). The Hub READS
  and ENFORCES it; a normal user can't override it. Enforced keys:
  `allow_remote_transport:false` (the bridge refuses any non-loopback bind),
  `allowed_source_types` (block e.g. `api` egress — enforced on create AND
  import), `require_auth:true` (`/api` stays locked until a key is set),
  `disable_update_check:true` (no outbound update call, CLI included).
  `GET /v1/policy` reports the effective policy. This is the LOCAL-FIRST
  equivalent of Claude Code's managed-settings — deliberately NOT a cloud
  fleet-management / multi-tenant / RBAC control plane (the Hub has no backend
  and stays single-machine; org rollout is the admin's existing MDM pushing the
  file).

## 9. Distribution phases

All three operating systems (macOS, Windows, Linux) are supported targets;
the phases stage the *installation experience*, not the OS coverage — the
core is Python/FastAPI and must stay cross-platform from day one.

1. **P1 — developers:** public repo + `bootstrap.sh` (venv + run). Runs on
   all three OSes. Good enough for Hub-aware plugin development.
2. **P2 — technical users:** `pipx install selran-hub` / Homebrew tap, plus
   auto-start on boot per OS: LaunchAgent (macOS), systemd user unit (Linux),
   Windows service or Scheduled Task (Windows).
3. **P3 — everyone, including engineers:** signed + notarized double-click
   installer with a menu-bar / system-tray presence and a first-run setup UI.
   macOS first (primary audience), then Windows, then Linux. **Committed —
   all three phases will be completed** (owner decision 2026-06-10): the
   easiest installation is the product standard for every audience, not a
   non-engineer concession. Known recurring costs, accepted and budgeted:
   Apple Developer Program (~$99/yr) + notarization tooling, a Windows
   code-signing identity (~$200–500/yr, or Azure Trusted Signing), and
   per-OS installer + auto-update maintenance. P1 and P2 still ship first
   because they unblock development and early adopters while P3 is built.

Additionally, a **`.mcpb` Desktop Extension** (H3, `mcpb/` + `scripts/build_mcpb.sh`,
runbook in `docs/MCPB.md`) gives Claude Desktop users a one-click way to register
the Hub *bridge* (drag the bundle into Settings → Extensions). It bundles only
the stdio bridge + its deps and connects to the separately-installed Hub daemon;
signing + directory submission share the P3 signing identity.

**Auto-update (H6, `updater.py`):** the Hub can tell the user when a newer
release is published (compared against the public GitHub `releases/latest`).
`selran-hub update-check` is an explicit CLI command; an opt-in
(`SELRAN_HUB_UPDATE_CHECK=1`) `/v1/update` route + SessionStart hook surface it
automatically, cached weekly. It is the only outbound call the Hub makes and
sends nothing about the user (local-first, §8). The *signed/notarized
installers* that auto-update would deliver are still gated on the Apple Developer
ID — runbook in `ops/P3-PLAN.md`.

## 10. Commerce (deferred phase)

The Hub is where pack entitlements eventually live: license files verified
offline, an entitlement API the design-director pack flow queries, the
dashboard's pack browser linking to purchase. Out of scope for v1; the module
boundary (§2.5) is in scope for v1 so this bolts on without surgery.

## 11. Roadmap

- **M0 — rescue (done with this commit):** app-startup skill and
  app-port-registry implementation versioned in this repo.
- **M1 — identity:** MCP-server-app gains `/hub/health` (§4.1), rebrand,
  port move to :11999 with registry routes proxied/absorbed (§3.2).
- **M2 — lifecycle:** `/v1/services/*` (§6) + dashboard service panel.
- **M3 — first consumer:** Design Director v1.1 detects the Hub and unlocks
  the live studio widget (§7). Acceptance: the same conversation, with the
  Hub running, visibly upgrades.
- **M4 — Greenloop live audit panel** (§7): audit runs stream phase/finding
  progress to a Hub-served dashboard page; Greenloop's skill gains the
  Hub-detection mention.
- **M5 — packaging:** P1→P2→P3 (§9) — all three phases, P3 macOS first.
  Status 2026-06-10: **P1 + P2 complete** (proper `selran_hub` package,
  `pipx install git+…` proven from a clean venv, `selran-hub` CLI with
  serve/status/logs and per-OS autostart: LaunchAgent / systemd user unit /
  Scheduled Task). **P3 gated** on the owner's signing identities (Apple
  Developer Program; Windows signing) — full build runbook in ops/P3-PLAN.md.
- **M6 — commerce:** entitlements (§10), pack browser.
  Status 2026-06-10: **DONE** — Ed25519-signed license files verified
  offline (signing key held only by the owner at ~/.selran/keys/, public
  key embedded), /v1/entitlements API + /v1/entitlements/check consumed
  by design-director 3.8's pack flow, 25-pack catalog + /hub/packs
  browser, owner-side issuer tool. Founder license (packs-all,
  enterprise, perpetual) issued and installed on the owner's Hub.
- **H1 — orphan-PID reaper** (§6.1). Status 2026-06-13: **DONE** (v0.8.0) —
  read-only PID scan (`/v1/services/{id}/pids`, `/v1/apps/{app_id}/pids`) +
  identity-gated single/group stop (`…/pids/{pid}/stop`), reuse-proof
  `(pid, create_time, command)` tuple re-verified before each signal, launch
  marker `SELRAN_HUB_INSTANCE`, free-vs-blind port coverage, startup reconcile,
  dashboard drill-ins. psutil added as a dependency; stop is POSIX-only this
  release. Designed and adversarially safety-reviewed before build; 11 H1
  acceptance tests (68 total green). First phase of the H-series upgrade
  roadmap (next: H2 MCP Apps, H3 .mcpb, … vs Anthropic's plugin/extension
  platform).
- **H2 — MCP Apps (SEP-1865)** (§4.4). Status 2026-06-13: **DONE as groundwork**
  (v0.9.0) — the bridge exposes `design_picker` + `data_sources_panel` as
  `ui://` interactive resources (`text/html;profile=mcp-app`) linked via
  `_meta.ui.resourceUri`, each with a complete structured/text fallback. 5 shape
  tests (73 total green) + a live stdio MCP-session handshake verify the wire
  shape. Renders inline in MCP-Apps hosts (Goose / VS Code / ChatGPT); falls
  back to text in Claude until Anthropic ships iframe rendering (open upstream
  bug ext-apps#671). Forward-looking — cannot be render-verified headlessly.
  Next: H3 signed `.mcpb` Desktop Extension.
- **H3 — `.mcpb` Desktop Extension** (§9, docs/MCPB.md). Status 2026-06-13:
  **DONE (unsigned bundle)** at v0.9.0 — `mcpb/manifest.json` (MCPB v0.4) +
  `mcpb/server/main.py` shim + `scripts/build_mcpb.sh` produce a one-click
  bundle of the Hub bridge for Claude Desktop. The bundle ships just
  `mcp_bridge.py` + its deps (mcp/httpx/pydantic) — lean and self-contained —
  and connects to the separately-installed Hub daemon (`hub_port` user-config →
  `SELRAN_HUB_PORT`). Verified: `mcpb validate`/`pack`/`info` + the unpacked
  bundle runs a real stdio MCP session in a clean env (initialize / 11 tools /
  ui:// resources). Building the bundle surfaced + fixed a real standalone-load
  bug (eager Pydantic `model_rebuild()` for the forward-ref models, guarded by a
  regression test). **Gated (owner actions):** signing/notarization needs the
  Apple Developer ID (same blocker as the DMG, ops/P3-PLAN.md), and directory
  submission is manual. The drag-to-install flow can't be verified here.
- **H4 — event push (background monitor + SessionStart hook)** (§7). Status
  2026-06-13: **DONE** (v0.10.0). The Hub *plugin* now ships `hooks/hooks.json`
  (SessionStart → `scripts/hub_session_context.py` injects a one-line Hub status
  as context, silent when the Hub is absent) and `monitors/monitors.json` (a
  background monitor → `scripts/hub_watch.py` that notifies the chat, unprompted,
  when a service goes down (transitions to "failed") or the Hub becomes
  unreachable — low-noise: silent baseline, transitions only). Both are stdlib
  scripts (no deps) hitting loopback. `claude plugin validate` passes; 10 unit
  tests on the transition/summary logic + a live smoke (hook silent-when-down /
  summary-when-up; monitor emits exactly one line on a real service crash) — 84
  total green. Monitors are experimental (Claude Code v2.1.105+); whether the
  host fires the hook / runs the monitor in a live session can't be verified
  headlessly, but the scripts and logic are proven. Next: H5 OS-keychain secrets.
- **H5 — OS-keychain secret storage** (§8). Status 2026-06-13: **DONE**
  (v0.11.0). New `secrets_store.py` (keyring-backed — macOS Keychain / Windows
  Credential Manager / Linux Secret Service — with a 0600-file fallback when no
  keychain is present). The API-key auth token and data-source API headers now
  live in the keychain, not plaintext: `config.get/set_api_key` keep only
  `{enabled}` in a 0600 `auth.json`; `source_manager` strips endpoint headers to
  the keychain (inject-at-connector-build, merge-preserve on edit, migrate
  legacy inline secrets on load, delete on source-delete), writes `sources.json`
  0600, and export + API responses no longer carry credentials. `keyring` added
  as a dependency. Adversarially reviewed (3-lens workflow) and hardened:
  crash-safe load-migration (a flaky keychain can't crash Hub startup), files
  re-tightened to 0600 on load (not only on write), atomic secrets-file writes
  (mkstemp + os.replace), reconcile-prune of orphaned endpoint secrets on update,
  collision-proof endpoint keys, probe cleanup, forced-backend guard. Credentials
  belong in endpoint `headers` (the protected channel); `params`/`body` are
  non-secret request config. 13 H5 tests + a live round-trip through the real
  macOS Keychain AND the file fallback — 97 total green. Next: H6 auto-update +
  installers.
- **H6 — auto-update check** (§9). Status 2026-06-13: **DONE (checker)** at
  v0.12.0; signed/notarized installers remain **gated** on the Apple Developer ID
  (ops/P3-PLAN.md). New `updater.py` compares the running version (tuple-of-ints
  semver, never string compare) against the public GitHub `releases/latest`,
  cached weekly. Surfaces: `selran-hub update-check` CLI (explicit; always runs),
  a read-only `/v1/update` route, and the SessionStart hook (relays the Hub's
  result, staying self-contained). **Local-first:** the only outbound call the
  Hub makes, it sends nothing about the user, and the automatic surface is
  OPT-IN (`SELRAN_HUB_UPDATE_CHECK=1`) — off by default. 6 H6 tests (semver-not-
  lexicographic compare, weekly cache, network-failure fallback, opt-in gate) +
  a live check against the real GitHub releases endpoint — 103 total green. Next:
  H7 MCP resources + deferred Tool Search.
- **H7 — MCP resources + Tool Search instructions** (§4.3). Status 2026-06-13:
  **DONE** (v0.13.0). The bridge exposes read-only `selran://` resources
  (sources, `sources/{name}/schema` template, health, packs) the client lists
  and `@`-mentions — GA and actually consumed by Claude Code + Desktop (unlike
  H2's render-gated UI), complementing the existing tools. It also sets FastMCP
  server `instructions` so Claude Code's client-side **Tool Search** (which
  defers MCP tool schemas) surfaces the Hub's tools at the right moment — the
  only server-side lever (deferral is client policy; no server flag exists). 5
  H7 tests (resource + template registration, graceful error-JSON when the Hub
  is down, instructions set) + a live read of `selran://sources` /
  `selran://health` against a running Hub — 108 total green. Audit runs are
  ephemeral (per-run) so they aren't a resource. Next: H8 Streamable-HTTP +
  OAuth (optional) / H9 enterprise.
- **H8 — remote transport + auth** (§8). Status 2026-06-13: **DONE** (v0.14.0).
  The MCP bridge gains the modern **Streamable HTTP** transport (and keeps legacy
  SSE) for a remote Claude client, gated by a bearer token. Local-first
  preserved: stdio stays the default, the **daemon stays loopback-only**, and a
  non-loopback bind **refuses to start without `SELRAN_HUB_BRIDGE_TOKEN`** — every
  request then needs `Authorization: Bearer <token>` (constant-time, ASGI
  middleware) or 401. This also closes a pre-existing gap (SSE could bind
  `0.0.0.0` unauthenticated). Full OAuth 2.1 (DCR/PKCE) is the Anthropic-managed
  connector-directory path; the self-hosted bridge uses the bearer token as the
  verifiable equivalent. Adversarially reviewed (bypass / exposure / robustness)
  and hardened per its findings: fixed FastMCP's import-time DNS-rebinding
  allowlist that broke the real off-loopback flow (421); bytes-compare so a
  non-ASCII Bearer can't crash the gate (was an unauth 500); deny-by-default
  scope handling (only `lifespan` passes, websocket rejected); uvicorn
  concurrency/keep-alive bounds. 10 H8 tests + a live streamable-http smoke (401
  without token, 200 with, **remote Host header → 200 not 421**, non-ASCII → 401
  not 500, exit-2 refusal on a network bind) — 118 total green. Next: H9
  enterprise (optional, only if Hub targets teams).
- **H9 — managed policy / MDM** (§8). Status 2026-06-13: **DONE** (v0.15.0) —
  the H-series finale. New `policy.py` reads a read-only admin-deployed
  `managed-policy.json` (system-managed location) and enforces it across the
  Hub: bridge refuses remote transport, `/api` data-source surface restricts
  source types (create + import) / requires auth, and update checks are forced
  off (CLI included); `GET /v1/policy` reports the effective policy. The honest
  scope: this is the local-first MDM lockdown layer, **not** a cloud fleet /
  RBAC control plane (out of scope by architecture). A self-audit caught and
  fixed two enforcement bypasses (bulk-import skipped the type restriction; the
  explicit update-check CLI ignored the no-egress policy). 10 H9 tests + a live
  smoke (managed policy refuses a remote bind and blocks the update-check CLI) —
  128 total green. **The H1–H9 upgrade roadmap is complete (v0.8.0 → v0.15.0).**

Each milestone ends with a Greenloop pass (cartographer → app-audit →
audit-fix) before it's called done. This spec is the canonical spec for that
machinery.

## 12. Resolved questions (decided with Aidin, 2026-06-10)

- **selran-hub is the successor product.** MCP-server-app's code is imported
  here; the old repo is archived with a pointer. One product going forward.
- **All three OSes supported**; per-OS auto-start lands in P2, polished
  installers in P3 (macOS → Windows → Linux). See §9.
- **Greenloop live audit panel: INCLUDED** (owner decision 2026-06-10).
  Ships as a Hub service after Design Director's studio; Greenloop tells
  users it's included with the Hub once it exists (never advertise vapor;
  probe discipline §4.2 applies).

# Selran Hub

The single local runtime for the Selran ecosystem — one daemon, one
well-known port (`127.0.0.1:11999`), one dashboard, one MCP bridge. By
[Selran](https://github.com/apourmd941) — written and maintained by **Aidin
Eslampour**.

Free Selran plugins ([Greenloop](https://github.com/apourmd941/selran-devloop),
[Design Director](https://github.com/apourmd941/selran-design-director)) work
fully without it; the Hub adds optional enhanced experiences they detect and
light up against (live clickable design pickers, the Greenloop audit panel,
add-on packs).

**Status:** capabilities live — `ports` (registry), `services` (lifecycle with
verified process identity, incl. a safe **orphan-PID reaper** that finds and
stops leftover processes still holding an app's ports), `studio` (live
clickable pickers), `audit` (Greenloop live panel), `entitlements` (offline
pack licensing). The MCP bridge also exposes **MCP Apps** (SEP-1865) interactive
tools — a design-direction picker and a data-sources panel that render inline in
the chat on hosts that support them (with a text fallback elsewhere). As a Claude
Code plugin it also **pushes events into your session**: a SessionStart hook
injects the Hub's status as context, and a background monitor notifies you,
unprompted, when a local service goes down. Secrets (the API-key token,
data-source credentials) are stored in the **OS keychain** (macOS Keychain /
Windows Credential Manager / Linux Secret Service), with an owner-only 0600 file
fallback — never world-readable plaintext. `selran-hub update-check` tells you
when a newer release is out (opt-in automatic check; the only call it ever makes
out, and it sends nothing about you). The MCP bridge also exposes your connected
sources, schemas, and Hub health as read-only **MCP resources** (`selran://…`)
you can `@`-mention in Claude. For a Claude client on another machine, the bridge
can run a **Streamable-HTTP** transport — loopback by default; exposing it on a
network requires a bearer token (`SELRAN_HUB_BRIDGE_TOKEN`), enforced on every
request. Organizations can lock down a managed machine with a read-only
`managed-policy.json` (MDM-style) that the Hub enforces — restrict source types,
forbid remote access, require auth, disable update checks. Runs on macOS,
Windows, and Linux.

> Local-first: binds `127.0.0.1` only, no telemetry, no cloud backend. See
> [PRIVACY.md](https://github.com/apourmd941/selran-hub/blob/main/PRIVACY.md). MIT licensed — see [LICENSE](https://github.com/apourmd941/selran-hub/blob/main/LICENSE).

## What it looks like

The control room — data sources, ports, services, and packs in one place,
with dark, light, and follow-the-system themes:

| Dark | Light |
|---|---|
| ![Dashboard, dark theme](https://raw.githubusercontent.com/apourmd941/selran-hub/main/docs/screenshots/dashboard-dark.png) | ![Dashboard, light theme](https://raw.githubusercontent.com/apourmd941/selran-hub/main/docs/screenshots/dashboard-light.png) |

Design Director packs get a gallery (each pack shows its real palette and
type direction) and a multi-page example viewer — app screen, website,
presentation, charts, and document, all rendered in the pack's own design
language:

| Pack gallery | Example viewer |
|---|---|
| ![Pack gallery](https://raw.githubusercontent.com/apourmd941/selran-hub/main/docs/screenshots/packs-gallery.png) | ![Pack example viewer](https://raw.githubusercontent.com/apourmd941/selran-hub/main/docs/screenshots/pack-viewer.png) |

## Install

**macOS — signed installer (easiest).** Download the latest
`SelranHub-*.dmg` from [Releases](https://github.com/apourmd941/selran-hub/releases),
drag to Applications, launch. Signed and notarized by Apple — no warnings. A
menu-bar icon shows status and opens the dashboard. (Windows and Linux
installers are in progress; use pipx below meanwhile.)

**Any OS — pip / pipx (technical users):**

```bash
pipx install git+https://github.com/apourmd941/selran-hub
selran-hub serve                # run it (foreground)
selran-hub autostart install    # or: start on login (LaunchAgent / systemd / Scheduled Task)
selran-hub status               # check it
```

**Claude Desktop — one-click bridge (`.mcpb`):** build the MCP Bundle with
`scripts/build_mcpb.sh` and drag `dist/selran-hub-*.mcpb` into Claude Desktop →
Settings → Extensions. This installs the *bridge* that exposes your Hub's tools
to Claude; the Hub daemon still installs via one of the options above. See
[docs/MCPB.md](https://github.com/apourmd941/selran-hub/blob/main/docs/MCPB.md).

**Developers (from a clone):** `./bootstrap.sh` then `./run_hub.sh`. Tests:
`python3 -m pytest tests/ -q` (in-process, no bound ports).

See [SELRAN_HUB_DESIGN.md](https://github.com/apourmd941/selran-hub/blob/main/SELRAN_HUB_DESIGN.md) for the full specification and
roadmap, and [ops/P3-PLAN.md](https://github.com/apourmd941/selran-hub/blob/main/ops/P3-PLAN.md) for the installer build pipeline.

## Feedback & contributions

Bug reports and feature requests are welcome — open an issue. Pull requests are
not accepted: to keep authorship and licensing unambiguous, all code here is
written by the author. Describe a fix in an issue and it'll be credited.

## License & attribution

MIT — © 2026 Selran, Aidin Eslampour. Privacy: [PRIVACY.md](https://github.com/apourmd941/selran-hub/blob/main/PRIVACY.md).
Contact: aidin.eslampour@selran.ai

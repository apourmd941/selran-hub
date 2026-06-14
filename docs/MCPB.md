# Selran Hub — MCP Bundle (`.mcpb`) for one-click install

`.mcpb` is Anthropic's [MCP Bundle](https://github.com/anthropics/mcpb) format
(formerly `.dxt`): a single file a user drags into **Claude Desktop → Settings →
Extensions** to install an MCP server with no JSON editing. This repo ships a
bundle that registers the **Selran Hub bridge** — the stdio MCP server that
exposes your Hub's data-source tools (and the MCP-Apps UI tools) to Claude.

## What's in the bundle

```
manifest.json          # MCPB v0.4 manifest (validated by `mcpb validate`)
server/main.py         # entry shim — loads the bridge as a standalone module
server/mcp_bridge.py   # the bridge (no intra-package imports → self-contained)
server/lib/            # the bridge's deps for the build platform (mcp, httpx, pydantic)
```

The bundle is just the **bridge**. The Hub *daemon* (FastAPI on 127.0.0.1:11999)
is installed and run separately (`pipx install git+https://github.com/apourmd941/selran-hub`
or the signed app). With no Hub running, the tools return a friendly "start the
Hub" message rather than failing. The user-config `hub_port` (default 11999)
flows to the bridge as `SELRAN_HUB_PORT`.

## Build

```bash
scripts/build_mcpb.sh           # assemble → validate → pack → dist/selran-hub-<version>.mcpb
scripts/build_mcpb.sh --sign    # also sign (self-signed by default)
```

The version is read from `selran_hub/config.py` so the manifest never drifts.
Build artifacts (`dist/`, `*.mcpb`) are gitignored — never commit the binary.

**Cross-platform note:** `server/lib/` carries native wheels (`pydantic-core`)
for the build platform, so build on each target OS (macOS / Windows / Linux) for
a cross-platform release, or switch the manifest `server.type` to `uv` to resolve
deps at runtime.

## Sign + verify (release)

Signing is gated on a real code-signing identity (the same **Apple Developer ID**
that gates the signed `.app` / DMG — see `ops/P3-PLAN.md`). Until then the bundle
installs with an "unsigned" warning (and is blocked only where MDM enforces
`isDesktopExtensionSignatureRequired`).

```bash
# self-signed (dev): proves the sign/verify path
npx @anthropic-ai/mcpb sign dist/selran-hub-<version>.mcpb --self-signed
npx @anthropic-ai/mcpb verify dist/selran-hub-<version>.mcpb

# release: sign with the Developer ID identity (pass via MCPB_SIGN_ARGS)
MCPB_SIGN_ARGS="--cert <path> --key <path>" scripts/build_mcpb.sh --sign
```

## Submit to the directory

Manual, owner-only step: submit the signed `.mcpb` at the Claude extension
directory submission form. Automated screening runs first; the **"Anthropic
Verified"** badge is a stricter manual review.

## Verification status

Built to the MCPB v0.4 schema and verified as far as is possible without Claude
Desktop on this machine:

- `mcpb validate` passes; `mcpb pack` produces the bundle; `mcpb info` reads it.
- The **unpacked bundle's `server/main.py` runs over a real stdio MCP session**
  in a clean environment (deps resolved only from `server/lib/`): `initialize`
  succeeds, `tools/list` returns all 11 tools, `resources/list` advertises the
  `ui://` resources. (The H2 MCP-Apps UI still only *renders* in MCP-Apps hosts;
  in Claude the data tools work and the UI falls back to text — see §4.4 of the
  design spec.)
- Not verified here: the actual drag-to-install flow in Claude Desktop, and
  signing/notarization (gated on the Developer ID).

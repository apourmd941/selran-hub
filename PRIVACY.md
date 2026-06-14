# Privacy Policy — Selran Hub

Effective: 2026-06-11

Selran Hub is a local daemon. It runs entirely on your machine, binds
`127.0.0.1` only, and is the single local runtime that Selran's Claude plugins
detect and use.

- **No data collection, no telemetry.** The Hub has no cloud backend and sends
  no analytics or usage data anywhere. It makes no network calls of its own.
- **Localhost only.** The Hub refuses non-loopback connections and rejects
  cross-origin state-changing requests (so a web page you visit cannot drive
  it). Nothing it manages is reachable from the network.
- **Local artifacts only, under your control.** Everything the Hub stores stays
  on your machine: the port registry (`~/.config/app-port-registry.sqlite3`),
  the service registry and logs (`~/.selran/hub/`), installed pack licenses
  (`~/.selran/hub/licenses/` — plain signed files you can read), and registered
  data sources (in the OS app-support directory). You can inspect or delete any
  of it.
- **It brokers, it does not read.** The Hub allocates ports, supervises the
  services you register, verifies pack licenses offline, and bridges data
  sources to MCP clients. The actual reading of your data happens inside your
  own Claude session, governed by Anthropic's privacy terms — the Hub adds no
  additional processing or recipients.
- **Data sources you register** (folders, databases, APIs) are accessed only
  when you or your AI client query them, locally. Their contents are never sent
  anywhere by the Hub.

Questions: aidin.eslampour@selran.ai

Selran Hub — © 2026 Selran, Aidin Eslampour.

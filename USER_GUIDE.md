# Selran Hub — User Guide

## What it is, in one sentence

**Selran Hub is one small app that runs quietly in the background and acts as
the "control room" for everything Selran on your computer.** You install it
once; it starts itself whenever you log in; and other Selran tools (and Claude)
talk to it automatically.

It lives at **`http://127.0.0.1:11999`** — that's your own machine only
(`127.0.0.1` means "this computer"). Nothing is on the internet, nothing is
shared, nothing phones home.

## The mental model

Think of the Hub as a building with five rooms. You don't have to use all of
them — most people start with one or two.

| Room | What it does | Who uses it |
|---|---|---|
| 🔌 **Ports** | Hands out network ports to your apps so they never collide | Automatic — every Selran app asks the Hub for ports |
| 🔗 **Data Sources (MCP)** | Connect a folder, database, or API once — Claude can then read/query it | You, via the dashboard |
| ⚙️ **Services** | Start / stop / restart your apps, safely | You or Selran tools |
| 🎨 **Studio** | Live clickable design pickers | Design Director plugin (automatic) |
| 📋 **Audit panel** | Live view of a code audit as it runs | Greenloop plugin (automatic) |
| 🛍️ **Packs** | Your Design Director add-on licenses | You, via the dashboard |

So to the common question — *"is it a port registry or an MCP hub?"* — it's
**both, and three more things.** The port registry is the foundation (it's
already managing every Selran app's ports); the MCP data-source hub is the part
you interact with most.

---

## 1. Install it

**macOS (easiest):**
1. Download `SelranHub-x.y.z.dmg` from the
   [Releases page](https://github.com/apourmd941/selran-hub/releases).
2. Open it, drag **Selran Hub** to Applications, and launch it.
3. A small **hexagon icon (⬢)** appears in your menu bar. That's it — it's
   running, and it will start automatically every time you log in.

It's signed and notarized by Apple, so you won't see any "unidentified
developer" warnings.

**Any OS (for developers):**
```bash
pipx install git+https://github.com/apourmd941/selran-hub
selran-hub serve                # run it
selran-hub autostart install    # make it start on login
selran-hub status               # check it's up
```

---

## 2. Open the control room

Click the **⬢ menu-bar icon → Open Dashboard**, or just visit
**http://127.0.0.1:11999** in any browser.

The dashboard is the home for **Data Sources**. The other rooms are one click
away:

- **Services:** http://127.0.0.1:11999/hub/panel
- **Packs:** http://127.0.0.1:11999/hub/packs

---

## 3. Common things you'll want to do

### "I want Claude to read a folder / database / API of mine"

This is the most popular use. It takes 30 seconds:

1. Open the dashboard → click **+ Add Source**.
2. Pick what you're connecting:
   - **Folder** — any folder of files (CSVs, JSON, docs…)
   - **Database** — a SQLite or DuckDB file
   - **API** — a REST endpoint
3. Give it a name and point it at the thing. Save.
4. Click **MCP Config** → **Install** (or copy the snippet). This tells Claude
   the Hub exists.
5. Restart Claude. Now Claude can list your sources, preview tables, and run
   read-only queries against them — all locally.

Your data never leaves your machine; the Hub just lets Claude *ask* about it.

### "I want my apps to stop fighting over ports"

You don't have to do anything — this is automatic. When a Selran app starts, it
asks the Hub for a free block of ports, and the Hub guarantees no two apps get
the same one. You can *see* the current allocations at
http://127.0.0.1:11999/v1/report (or via the registry, which is what powers it).

### "I want to start/stop one of my apps from one place"

Open **Services** (`/hub/panel`). Apps registered as services show their state
(running / stopped / failed) and give you **Start / Stop / Restart** buttons.
The Hub verifies it's killing the *right* process before it stops anything — it
will never kill an unrelated program that happened to reuse a process ID.

### "A leftover process from the old version is blocking my app's port"

Open **Services** and click **PIDs** on the app's row (or **check** under "In
use" on the Apps & Ports page). The Hub lists *every* process holding that app's
ports — including orphans from a previous launch — and labels each one:

- **owned** — the Hub launched it (it carries the Hub's launch marker); one
  click to **Stop**, cleanly, as a group.
- **owned-unverified** — it's *your* process on the app's port but the Hub can't
  prove it launched it; you can still force-stop it after a clear confirmation.
- **ambiguous / foreign** — shown but never stoppable (another user's process, a
  system process, or one the Hub can't read). If a port is held by something it
  can't see (e.g. a `sudo`-launched leftover), it says so plainly instead of
  pretending the port is free — so you're never given a false "all clear."

Every stop re-checks the process's identity at the instant it signals, so a
recycled process ID can never be hit by mistake.

### "I bought a Design Director pack — where is it?"

Open **Design Director Packs** (`/hub/packs`). Every pack card shows its own
color palette and design direction, plus whether you're licensed. Your
license is a small signed file that's checked **offline** — nothing contacts a
server. To add a license, drop the license file you received into
`~/.selran/hub/licenses/`.

### "What does a pack actually look like before I buy it?"

Click any pack. Each one opens a **multi-page example viewer** showing real
things made in that pack's design system — flip through them with the tabs,
the Previous/Next buttons, or your arrow keys:

1. **App screen** — a product interface in the pack's style
2. **Website** — a full landing page
3. **Presentation** — a three-slide deck
4. **Charts & data** — graphs, KPIs, and a data sheet
5. **Document** — a print-style piece true to the pack's industry
   (a résumé for the Resume pack, a legal brief for Legal Tech, a journal
   article for Academic…)

Two packs never look alike: each direction has its own layouts, typography,
and voice — not just different colors.

### "Can I use it in light mode?"

Yes. The **theme button** in the top bar cycles **◐ Auto → ☾ Dark → ☀ Light**.
Auto follows your computer's appearance setting. Your choice is remembered on
this machine, and you can pin a theme in a link by adding `?theme=dark` or
`?theme=light` to any Hub URL.

---

## 4. Using it with the plugins (the magic part)

If you use the **Greenloop** or **Design Director** Claude plugins, you don't
configure anything — they **detect the Hub automatically** and light up extra
features:

- **Design Director** → when you pick a design direction, instead of describing
  options it opens a **live clickable picker** in your browser; you click one
  and it flows straight back to Claude.
- **Greenloop** → when it audits your code, it opens a **live panel** where
  findings and fixes appear in real time as it works.

Without the Hub, both plugins still work fully — they just use simpler
text-based flows. The Hub only *adds* to them.

---

## 5. The menu-bar app

The ⬢ icon gives you, at a glance:
- whether the Hub is running and which version,
- how many services are active,
- one-click access to the Dashboard, Services, and Packs,
- Quit.

It's designed to be invisible until you need it.

---

## 6. Is it safe / private?

Yes, by design:
- It binds to **`127.0.0.1` only** — unreachable from the network.
- It **refuses cross-origin requests**, so a random website you visit can't
  drive it.
- **No telemetry, no analytics, no cloud backend.** Its only outbound call is an
  opt-in update check (`selran-hub update-check`, or when `SELRAN_HUB_UPDATE_CHECK`
  is set) that asks GitHub whether a newer release exists — off by default and
  disableable by managed policy.
- Everything it stores stays on your machine and is yours to inspect or delete:
  port allocations, registered services, pack licenses, and the data sources
  you added.

Full details: [PRIVACY.md](PRIVACY.md).

---

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| Menu-bar icon is hollow (⬡) / dashboard won't load | The Hub isn't running. Launch the app, or run `selran-hub serve`. |
| `selran-hub status` says NOT running | `selran-hub serve` (foreground) or `selran-hub autostart install` (background). |
| Claude doesn't see your data sources | Did you run **MCP Config → Install** and restart Claude? |
| Want to see logs | Menu bar isn't enough? Run `selran-hub logs`. |
| A port seems stuck | The registry self-heals, but you can check `http://127.0.0.1:11999/v1/report`. |

---

*Selran Hub — © Selran, Aidin Eslampour. Runs locally, keeps to itself.*

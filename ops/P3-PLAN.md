# P3 — Signed installers with UI (spec §9.3)

The "double-click it and it just works" phase, for every audience including
engineers. P1 (bootstrap) and P2 (pip/pipx + autostart CLI) shipped in M5;
P3 is gated on signing identities that only the owner can obtain, then the
build work below.

## Gate 1 — the two things only Aidin can do

1. **Apple Developer Program** (~$99/yr): enroll at developer.apple.com with
   the Selran entity (or individual). Yields the `Developer ID Application`
   certificate used to sign, and notarization access (`notarytool`).
   Lead time: usually 1–2 days (identity verification).
2. **Windows code-signing identity**: pick one —
   - **Azure Trusted Signing** (~$10/mo, fastest to obtain, recommended), or
   - an EV/OV code-signing certificate from a CA (~$200–500/yr).
   Without it, installs show SmartScreen warnings — the exact thing P3 exists
   to remove.

Nothing else in this plan can ship to strangers until Gate 1 is done.
Everything below can be BUILT and tested locally unsigned in the meantime.

## The tray app (cross-platform UI shell)

A small wrapper around the existing daemon — not a rewrite:

- **Library:** `pystray` (tray icon: status dot, Open dashboard, Open panel,
  Start/Stop, Logs, Quit) + the existing web dashboard as the real UI.
- Behavior: launches `selran_hub.app` in-process, owns the autostart toggle
  (reusing `cli.py`'s installers), shows a first-run welcome page
  (`/hub/panel` + a short setup card).
- Lives at `selran_hub/tray.py`, entry `selran-hub tray`. Pure addition; the
  headless paths stay primary.

## macOS (first)

1. Bundle: **PyInstaller** `--windowed` build of the tray entry →
   `Selran Hub.app`. (Briefcase is the fallback if PyInstaller fights the
   `duckdb`/`mcp` natives.)
2. Sign: `codesign --deep --options runtime` with the Developer ID cert;
   hardened runtime + entitlements (network-server only — localhost bind).
3. Notarize: `xcrun notarytool submit --wait`, then `stapler staple`.
4. Package: `create-dmg` with drag-to-Applications layout.
5. CI: GitHub Actions `macos-latest` job; secrets: cert p12 + notary keys.
6. Auto-update: Sparkle is overkill for v1 — the tray checks
   `/hub/health` vs the GitHub releases feed weekly and shows an
   "update available" menu item linking the new DMG.

## Windows (second)

1. Bundle: PyInstaller one-dir build of the tray entry.
2. Installer: **Inno Setup** (simplest credible UX) — installs to
   `%LOCALAPPDATA%\SelranHub`, creates the logon task via the existing CLI.
3. Sign installer + exe via Azure Trusted Signing in CI.

## Linux (third)

1. **AppImage** (one file, no install) of the tray build, plus the existing
   pipx path as the recommended route for Linux users.
2. Optional later: a Flatpak if demand shows up in issues.

## Acceptance (per OS)

- Fresh machine/VM with nothing installed → download → double-click →
  no security warnings → tray icon up → `/hub/health` answers on 11999 →
  design-director rung 0 and the greenloop panel work in a Claude session.
- Uninstall leaves no running processes and no autostart entries.

## Order of work once Gate 1 clears

tray.py → unsigned local .app + smoke → signing/notarization in CI → DMG →
acceptance on a clean macOS account → Windows (Inno + signing) → AppImage.

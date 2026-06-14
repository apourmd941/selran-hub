"""Pack discovery + sample-screen previews.

The Hub never ships pack content (packs are the commercial Design Director
product). It reads packs from wherever they're installed on THIS machine and
renders their self-contained sample screens as previews. Packs that aren't
present show a description + purchase link instead.

Pack content location (first match wins):
  - $SELRAN_HUB_PACKS_DIR
  - ~/.claude/skills/selran-design-director/packs   (the core's install path)
"""

from __future__ import annotations

import os
import re
from pathlib import Path


def _candidate_dirs() -> list[Path]:
    out: list[Path] = []
    env = os.environ.get("SELRAN_HUB_PACKS_DIR")
    if env:
        out.append(Path(env).expanduser())
    out.append(Path.home() / ".claude" / "skills" / "selran-design-director" / "packs")
    return [d for d in out if d.is_dir()]


def _base_name(name: str) -> str:
    return name[5:] if name.startswith("pack-") else name


def find_pack_dir(name: str) -> Path | None:
    base = _base_name(name)
    for d in _candidate_dirs():
        p = d / base
        if p.is_dir():
            return p
    return None


def _yaml_scalar(text: str, key: str) -> str:
    m = re.search(rf'^{key}:\s*"?([^"\n]+)"?\s*$', text, re.MULTILINE)
    return m.group(1).strip().strip('"') if m else ""


def _yaml_folded(text: str, key: str) -> str:
    """Read a `key: >` folded multi-line block (indented continuation lines)."""
    m = re.search(rf"^{key}:\s*>\s*\n((?:[ \t]+.*\n?)+)", text, re.MULTILINE)
    if not m:
        return _yaml_scalar(text, key)
    lines = [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]
    return " ".join(lines)


def pack_detail(name: str) -> dict:
    """Real metadata + sample-screen list for a pack present on disk."""
    d = find_pack_dir(name)
    if d is None:
        return {"present": False, "id": name}
    yaml = ""
    yf = d / "pack.yaml"
    if yf.exists():
        try:
            yaml = yf.read_text(encoding="utf-8")
        except OSError:
            yaml = ""
    screens_dir = d / "provides" / "sample-screens"
    comps_dir = d / "provides" / "components"
    screens = sorted(p.name for p in screens_dir.glob("*.html")) if screens_dir.is_dir() else []
    components = sorted(p.stem for p in comps_dir.glob("*.html")) if comps_dir.is_dir() else []
    return {
        "present": True,
        "id": name,
        "display_name": _yaml_scalar(yaml, "display_name") or _base_name(name).replace("-", " ").title(),
        "description": _yaml_folded(yaml, "description"),
        "price_usd": _yaml_scalar(yaml, "price_usd"),
        "homepage": _yaml_scalar(yaml, "homepage"),
        "version": _yaml_scalar(yaml, "version"),
        "screens": screens,
        "components": components,
        "component_count": len(components),
        "identity": pack_identity(name),
    }


# What each base direction's typography "feels" like (packs inherit the
# direction's font family and override only tokens, so the direction conveys
# the type character).
_DIRECTION_FEEL = {
    "technical-minimal": "Clean geometric sans · dense, calm",
    "editorial": "Serif display · magazine hierarchy",
    "dark-premium": "Refined serif · luxe restraint",
    "brutalist": "Heavy grotesk/mono · raw, loud",
    "warm-approachable": "Friendly rounded sans",
    "bold-distinctive": "Big expressive display",
    "vibrant-playful": "Energetic, colorful",
}


def _hex_after(text: str, key: str) -> str:
    m = re.search(rf'(?m)^\s*{key}:\s*"?(#[0-9A-Fa-f]{{3,8}})"?', text)
    return m.group(1) if m else ""


def _palette_hexes(text: str) -> list[str]:
    # a `palette:` or `series:` list of `- "#......"` entries
    m = re.search(r"(?m)^\s*(?:palette|series|chart):\s*\n((?:\s*-\s*.*\n?)+)", text)
    if not m:
        return []
    out = []
    for ln in m.group(1).splitlines():
        h = re.search(r'(#[0-9A-Fa-f]{6})', ln)
        if h:
            out.append(h.group(1))
    return out[:6]


def pack_identity(name: str) -> dict:
    """The pack's visual signature: base direction, accent, palette, bg/fg —
    read from its pack-overrides/<direction>.yaml. Empty if not present."""
    d = find_pack_dir(name)
    if d is None:
        return {}
    ov = d / "pack-overrides"
    files = sorted(ov.glob("*.yaml")) if ov.is_dir() else []
    if not files:
        return {}
    text = files[0].read_text(encoding="utf-8", errors="ignore")
    direction = files[0].stem
    accent = _hex_after(text, "accent")
    accent_alt = _hex_after(text, "accent_alt")
    bg = _hex_after(text, "bg")
    fg = _hex_after(text, "fg")
    palette = _palette_hexes(text)
    # A swatch strip that always tells the pack's colour story. Packs with an
    # explicit palette (e.g. playful-consumer) use it directly; packs that only
    # define tokens (e.g. dark-premium luxury) compose bg → accent → accent_alt
    # → fg so a dark pack shows its full signature, not just one accent chip.
    if palette:
        swatches = palette
    else:
        swatches, seen = [], set()
        for c in (bg, accent, accent_alt, fg):
            cl = (c or "").lower()
            if cl and cl not in seen:
                seen.add(cl)
                swatches.append(c)
    return {
        "direction": direction,
        "feel": _DIRECTION_FEEL.get(direction, direction.replace("-", " ")),
        "accent": accent,
        "accent_hover": _hex_after(text, "accent_hover"),
        "accent_alt": accent_alt,
        "bg": bg,
        "fg": fg,
        "palette": palette or ([accent] if accent else []),
        "swatches": swatches or ([accent] if accent else []),
    }


def screen_html(name: str, filename: str) -> str | None:
    """The HTML of one sample screen, with path containment."""
    d = find_pack_dir(name)
    if d is None:
        return None
    root = (d / "provides" / "sample-screens").resolve()
    target = (root / filename).resolve()
    if not target.is_file() or not target.is_relative_to(root):
        return None
    try:
        return target.read_text(encoding="utf-8")
    except OSError:
        return None

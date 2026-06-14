"""Shared dark/light theme variables for every Hub-served page.

Every server-rendered page embeds THEME_CSS at the top of its <style> and
references colors only through var(--sh-*). The active theme is chosen by
nav.js (dark / light / system, persisted in localStorage as `selran-theme`)
by setting `data-theme` on <html>; with no attribute, dark applies.
"""

THEME_CSS = """
:root{color-scheme:dark;
 --sh-bg:#101014;--sh-panel:#16161c;--sh-panel2:#0e0e13;--sh-hover:#17171d;--sh-navbg:rgba(12,12,16,.94);
 --sh-border:#2a2a33;--sh-border2:#22222b;--sh-border3:#3a3a46;--sh-border4:#6a6a7a;
 --sh-text:#e8e8ec;--sh-text2:#c4c4cc;--sh-text3:#b9b9c4;--sh-muted:#9b9ba6;--sh-muted2:#8a8a96;
 --sh-link:#86b3ff;--sh-accent:#2f81f7;--sh-accent-fg:#ffffff;--sh-accentbg:#1c2a45;
 --sh-ok:#5ee59a;--sh-okbg:#0f3d22;--sh-bad:#ff8d96;--sh-badbg:#46141a;
 --sh-warn:#ffce7a;--sh-warnbg:#4a3413;--sh-btn:#26262f;
}
html[data-theme=light]{color-scheme:light;
 --sh-bg:#f2f3f6;--sh-panel:#ffffff;--sh-panel2:#f7f7fa;--sh-hover:#ededf2;--sh-navbg:rgba(255,255,255,.94);
 --sh-border:#d8d8e0;--sh-border2:#e4e4ea;--sh-border3:#c2c2cc;--sh-border4:#9a9aa8;
 --sh-text:#1a1a21;--sh-text2:#41414c;--sh-text3:#50505c;--sh-muted:#686874;--sh-muted2:#7c7c88;
 --sh-link:#1f5fd0;--sh-accent:#1f5fd0;--sh-accent-fg:#ffffff;--sh-accentbg:#e3edfb;
 --sh-ok:#117a44;--sh-okbg:#dcf3e6;--sh-bad:#c22f3e;--sh-badbg:#fbe3e6;
 --sh-warn:#8a5a00;--sh-warnbg:#f7e8c8;--sh-btn:#e9e9ef;
}
"""

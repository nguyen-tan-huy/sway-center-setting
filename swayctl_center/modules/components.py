"""Shell components: the bar, notifications, idle/lock, clipboard history and
the input method. Each can be "managed": swayctl-center then runs it as a
systemd user unit with config files it generates (themed with the active
theme and font) under <app folder>/generated/<component>/. The user's own
config files for these programs are never touched.

A component is never started while the same program is already running from
somewhere else (typically an `exec` in the user's sway config) - two bars or
two notification daemons would fight. First start adopts that situation by
marking such components unmanaged.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
import re
import shlex
import signal
import time
from pathlib import Path
from typing import Any

from .. import jsonc, owned, schema, swayconfig, swayipc, theming, themes, units
from . import Context

log = logging.getLogger(__name__)


def _font(ctx: Context) -> tuple[str, int]:
    f = (ctx.values or {}).get("font") or {"family": "sans-serif", "size": 10}
    return f["family"], f["size"]


def _font_weight(ctx: Context) -> int:
    """The interface font's weight as a CSS number."""
    from .font import css_weight
    return css_weight(((ctx.values or {}).get("font") or {}).get("weight", "regular"))


def _modern(ctx: Context) -> bool:
    return ((ctx.values or {}).get("appearance") or {}).get("style") == "modern"


def _glass(ctx: Context) -> bool:
    return bool(((ctx.values or {}).get("effects") or {}).get("glass"))


def _hex_rgb(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _luminance(c: str) -> float:
    r, g, b = _hex_rgb(c)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255


def _mix_hex(c: str, other: str, t: float) -> str:
    a, b = _hex_rgb(c), _hex_rgb(other)
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def _appearance(ctx) -> dict[str, Any]:
    return (ctx.values or {}).get("appearance") or {}


def _frame_color(ctx) -> str:
    c = _appearance(ctx).get("frame_color") or "#0b1014"
    return c if re.fullmatch(r"#[0-9a-fA-F]{6}", c) else "#0b1014"


def glass_desk(ctx) -> bool:
    """Interface style "glass": the whole desktop is one sheet of liquid glass over a video."""
    return _appearance(ctx).get("ui_style") == "glass"


def glass_desk_css(ctx) -> str:
    """The bar of the glass desk: no material of its own (the glass frame under it is the pane), its
    text white over the video, the pills' bodies gone."""
    if not glass_desk(ctx):
        return ""
    return """
/* interface style: glass desk - the bar is part of the sheet of glass (generated) */
window.bar.bar { background: none; border: none; border-radius: 0; box-shadow: none; }
window.bar .workspaces, window.bar .clock, window.bar .status, window.bar .tray, window.bar .mode,
window.bar .window-title { background: none; border-color: transparent; box-shadow: none; }
window.bar .module label, window.bar .module image, window.bar .clock, window.bar .status label,
window.bar .window-title { color: #ffffff; text-shadow: 0 1px 2px alpha(black, 0.35); -gtk-icon-shadow: 0 1px 2px alpha(black, 0.35); }
window.bar .workspace:not(.focused):not(.under-drop) { color: alpha(white, 0.78); }
"""


def frame_css(ctx) -> str:
    """Interface style "frame": the bar is the top edge of a solid colour that also fills the
    space around and between the windows (background.py sets the output to the same colour)."""
    if _appearance(ctx).get("ui_style") != "frame":
        return ""
    c = _frame_color(ctx)
    light = _luminance(c) > 0.55
    ink = "#111317" if light else "#ffffff"
    dim = "alpha(#111317, 0.62)" if light else "alpha(white, 0.68)"
    return f"""
/* interface style: frame - one solid colour, no blur (generated) */
window.bar.bar {{ background: {c}; border: none; border-radius: 0; box-shadow: none; color: {ink}; }}
window.bar .module label, window.bar .module image, window.bar .clock, window.bar .status label {{ color: {ink}; text-shadow: none; }}
window.bar .workspace:not(.focused):not(.under-drop) {{ color: {dim}; }}
"""


def popup_flat_css(ctx) -> str:
    """Quick Settings, the volume/brightness pill and the launcher as plain blocks (no glass, no
    blur) in a tone of the frame colour: a little lighter on a dark colour, a little darker on a
    light one."""
    ap = _appearance(ctx)
    if ap.get("quick_surface") != "flat":
        return ""
    c = _frame_color(ctx)
    light = _luminance(c) > 0.55
    ink = "#111317" if light else "#ffffff"
    block = _mix_hex(c, "#000000" if light else "#ffffff", 0.08 if light else 0.12)
    track = "alpha(black, 0.14)" if light else "alpha(white, 0.18)"
    sel = ", ".join(f".{cls}.{cls}.{cls}.{cls}.{cls}.{cls}:not(.active)" for cls in ("tile", "slider-row", "media"))
    sheets = ("launcher-search", "launcher-results", "launcher-keys", "launcher-suggest")
    sheet_sel = ", ".join(f".{c3}.{c3}.{c3}" for c3 in sheets)
    sheet_text = ", ".join(f".{c3} label, .{c3} image" for c3 in sheets)
    return f"""
/* popups: flat blocks in the frame colour's tone, the launcher in the frame colour itself (generated) */
.quick-panel {{ background: none; border-color: transparent; color: {ink}; }}
{sel} {{ background: {block}; border: none; box-shadow: none; color: {ink}; }}
.quick-panel label, .quick-panel image {{ color: {ink}; }}
.quick-panel .tile.active label, .quick-panel .tile.active image {{ color: #ffffff; }}
.quick-panel scale trough {{ background: {track}; }}
/* the pages inside (Wi-Fi, sound output, power mode, power): one block, rows divided by a line */
.quick-panel list.boxed-list.boxed-list.boxed-list {{ background: {block}; color: {ink}; border: none; box-shadow: none; }}
.quick-panel list.boxed-list > row {{ background: none; color: {ink}; box-shadow: none; }}
.quick-panel list.boxed-list > row:not(:first-child) {{ border-top: 1px solid alpha({ink}, 0.10); }}
.quick-panel list.boxed-list > row.activatable:hover {{ background: alpha({ink}, 0.07); }}
.quick-panel row .title, .quick-panel row .subtitle, .quick-panel row label, .quick-panel row image {{ color: {ink}; }}
.quick-panel headerbar.flat.flat.flat {{ background: {block}; border-radius: 999px; box-shadow: none; margin-bottom: 8px; }}
.quick-panel headerbar, .quick-panel headerbar label, .quick-panel headerbar image, .quick-panel headerbar button {{ color: {ink}; }}
.quick-panel .quick-footer button.circular {{ background: {block}; color: {ink}; box-shadow: none; }}
.quick-panel .media button {{ background: alpha({ink}, 0.14); color: {ink}; box-shadow: none; }}
.quick-panel .notification-card, .quick-panel button.flat.pane {{ background: {block}; border: none; box-shadow: none; color: {ink}; }}
.osd.osd.osd {{ background: {block}; border: none; box-shadow: none; color: {ink}; }}
.osd image, .osd label {{ color: {ink}; text-shadow: none; }}
.osd levelbar, .osd levelbar trough {{ background: {track}; }}
{sheet_sel} {{ background: {c}; border: none; box-shadow: none; color: {ink}; }}  /* the launcher is the bar's own colour */
{sheet_text} {{ color: {ink}; }}
.launcher-row:hover {{ background: alpha({ink}, 0.08); }}
.launcher-results .launcher-row.selected label, .launcher-results .launcher-row.selected image {{ color: #ffffff; }}
"""


def _minimal(ctx) -> bool:
    return _appearance(ctx).get("ui_style") == "minimal"


def minimal_palette(dark: bool) -> dict[str, str]:
    """Interface style "minimal": a soft grey page, white (or near-black) cards, one ink colour
    for text and for the one filled control, hairlines instead of shadows."""
    if dark:
        return {"page": "#0e0e10", "card": "#1b1b1e", "ink": "#f4f4f6"}
    return {"page": "#ececef", "card": "#ffffff", "ink": "#111113"}


def minimal_css(ctx, t) -> str:
    """Bar, Quick Settings, OSD, notifications, tray menu and launcher as Modern Minimal cards."""
    if not _minimal(ctx):
        return ""
    m = minimal_palette(bool(t.dark))
    card, ink = m["card"], m["ink"]
    line, soft = f"alpha({ink}, 0.08)", f"alpha({ink}, 0.055)"
    sheets = ("launcher-search", "launcher-results", "launcher-keys", "launcher-suggest")
    sheet_sel = ", ".join(f".{c}.{c}.{c}" for c in sheets)
    sheet_text = ", ".join(f".{c} label, .{c} image" for c in sheets)
    tiles = ", ".join(f".{c}.{c}.{c}:not(.active)" for c in ("tile", "slider-row", "media"))
    return f"""
/* interface style: minimal (generated) - the bar is the page colour (like the frame), popups are cards, hairlines, one dark accent */
window.bar.bar {{ background: {m["page"]}; color: {ink}; border: none; border-radius: 0; box-shadow: none; }}
window.bar .module label, window.bar .module image, window.bar .clock, window.bar .status label {{ color: {ink}; text-shadow: none; }}
window.bar .workspace.workspace.workspace {{ border-radius: 999px; color: alpha({ink}, 0.6); }}
window.bar .workspace.focused.focused.focused {{ background: {ink}; color: {card}; }}
window.bar .workspace.visible.visible {{ background: {soft}; color: {ink}; }}
window.bar .mode.mode {{ background: {ink}; color: {card}; border-radius: 999px; }}
.quick-panel.quick-panel.quick-panel {{ background: {card}; color: {ink}; border: 1px solid {line}; border-radius: 26px; }}
.quick-panel label, .quick-panel image {{ color: {ink}; }}
{tiles} {{ background: {soft}; color: {ink}; border: none; box-shadow: none; }}
.tile.tile.tile.active {{ background: {ink}; color: {card}; border: none; }}
.quick-panel .tile.active label, .quick-panel .tile.active image {{ color: {card}; }}
.tile .tile-more:hover, .tile .tile-main:hover {{ background: alpha({ink}, 0.07); }}
.quick-panel .slider-row {{ border-radius: 999px; }}
.quick-panel .media {{ border-radius: 20px; }}
scale trough {{ background: alpha({ink}, 0.10); }}
scale highlight {{ background: {ink}; }}
scale slider {{ background: {card}; border: 1px solid {line}; }}
.quick-panel list.boxed-list.boxed-list.boxed-list {{ background: {soft}; border: none; border-radius: 20px; }}
.quick-panel list.boxed-list > row:not(:first-child) {{ border-top: 1px solid {line}; }}
.quick-panel headerbar.flat.flat.flat {{ background: {soft}; border-radius: 999px; }}
.quick-panel .quick-footer button.circular, .quick-panel .media button {{ background: {soft}; color: {ink}; box-shadow: none; }}
.quick-panel .notification-card, .quick-panel button.flat.pane {{ background: {soft}; border: none; color: {ink}; }}
.osd.osd.osd {{ background: {card}; color: {ink}; border: 1px solid {line}; box-shadow: none; }}
.osd image, .osd label {{ color: {ink}; }}
.osd levelbar, .osd levelbar trough {{ background: alpha({ink}, 0.10); }}
.osd levelbar block.filled {{ background: {ink}; }}
.notification-card.notification-card.notification-card {{ background: {card}; color: {ink}; border: 1px solid {line}; border-radius: 22px; }}
.notification-card label, .notification-card image {{ color: {ink}; }}
.notification-action {{ background: none; box-shadow: inset 0 0 0 1px alpha({ink}, 0.16); border-radius: 999px; }}
.tray-menu.tray-menu {{ background: {card}; color: {ink}; border: 1px solid {line}; border-radius: 18px; }}
.tray-menu-item:hover {{ background: {soft}; }}
{sheet_sel} {{ background: {card}; color: {ink}; border: 1px solid {line}; box-shadow: none; }}
{sheet_text} {{ color: {ink}; }}
.launcher-search.launcher-search.launcher-search {{ border-radius: 999px; }}
.launcher-results.launcher-results.launcher-results {{ border-radius: 26px; }}
.launcher-row:hover {{ background: {soft}; }}
.launcher-row.selected.selected, .launcher-app.selected .launcher-icon, .launcher-emoji-cell.selected {{ background: alpha({ink}, 0.08); }}
.launcher-results .launcher-row.selected label, .launcher-results .launcher-row.selected image {{ color: {ink}; text-shadow: none; }}
.launcher-mode {{ background: {ink}; color: {card}; }}
.launcher-entry {{ caret-color: {ink}; }}
"""


def minimal_settings_css(dark: bool) -> str:
    """The settings window in the same style: grey page, white cards with hairlines, pills, dark primary."""
    m = minimal_palette(dark)
    card, ink, page = m["card"], m["ink"], m["page"]
    line, soft = f"alpha({ink}, 0.08)", f"alpha({ink}, 0.055)"
    return f"""
/* interface style: minimal */
window.background {{ background: {page}; }}
.navigation-sidebar, .sidebar-pane, .sidebar {{ background: {card}; border-radius: 22px; }}
list.boxed-list, .card, preferencesgroup > box > list {{ background: {card}; border: 1px solid {line}; border-radius: 20px; box-shadow: none; }}
list.boxed-list > row {{ background: none; }}
list.boxed-list > row:not(:first-child) {{ border-top: 1px solid {line}; }}
.navigation-sidebar > row {{ border-radius: 14px; margin: 1px 8px; }}
.navigation-sidebar > row:selected {{ background: alpha({ink}, 0.08); color: {ink}; }}
headerbar {{ background: none; box-shadow: none; }}
button.suggested-action {{ background: {ink}; color: {card}; border-radius: 999px; box-shadow: none; }}
button:not(.flat):not(.circular):not(.suggested-action):not(.destructive-action) {{ border-radius: 999px; }}
entry, searchentry, spinbutton {{ border-radius: 999px; background: {soft}; box-shadow: none; }}
switch:checked {{ background: {ink}; }}
switch:checked slider {{ background: {card}; }}
scale trough {{ background: alpha({ink}, 0.10); }}
scale highlight {{ background: {ink}; }}
.chip {{ border-radius: 999px; border: 1px solid alpha({ink}, 0.16); }}
"""


DARK_SMOKE = 0.45


def _square(ctx) -> bool:
    """Interface style flat / floating: no rounded corners anywhere."""
    t = getattr(ctx, "theme", None)
    return t is not None and t.tokens["radius_lg"] == 0


def _panel_radius(k) -> float:
    """Popup panel corners: the large radius plus a little (none when square)."""
    return k["radius_lg"] + 6 if k["radius_lg"] else 0


SQUARE_CSS = """
/* interface style: square corners everywhere (generated) */
window.bar, window.bar .module, window.bar .workspaces, window.bar .workspace, window.bar .clock,
window.bar .status, window.bar .tray, window.bar .mode, window.bar .window-title,
.quick-panel, .quick-panel headerbar, .tile, .tile button, .tile-main, .tile-more, .slider-row, .media,
.quick-footer button, .media button, .osd, .osd levelbar, .osd levelbar trough, .osd levelbar block,
.notification-card, .notification-action, .notification-close, .notification-image,
.tray-menu, .tray-menu-item, .launcher-search, .launcher-results, .launcher-keys, .launcher-suggest,
.launcher-row, .launcher-mode, .launcher-kbd, .launcher-emoji-cell, .launcher-app .launcher-icon,
.launcher-thumb {
  border-radius: 0;
}
window.bar .workspace.workspace.workspace, window.bar .ws-blob.ws-blob { border-radius: 0; }
scale trough, scale highlight, scale slider { border-radius: 0; }
scale slider { min-width: 10px; }
"""


def _glass_opacity(ctx: Context, theme=None) -> float:
    """effects.glass_opacity as 0..1: how much the theme's surface color tints
    the glass (smoked on dark, milky on light)."""
    # Exactly the setting (0 = clear glass), only kept above 1%: the compositor
    # shapes the glass of popups by what's drawn, and fully clear isn't drawn.
    base = ((ctx.values or {}).get("effects") or {}).get("glass_opacity", 50)
    t = theme or ctx.theme
    return glass_tint(base, t is not None and t.dark)


def glass_tint(percent: float, dark: bool) -> float:
    """effects.glass_opacity (0-100) as the alpha of the glass's tint."""
    base = percent / 100
    if dark:
        # dark is smoked glass: dark even at 0, still clear (blur is "frost")
        return DARK_SMOKE + (1 - DARK_SMOKE) * base
    # 2% at least: the compositor shapes the glass by what's drawn, and an
    # 8-bit alpha of 1% rounds to 1-2/255 (holes in the shape)
    return max(base, 0.02)


def adaptive_css(pct: float, accent: str, accent_fg: str, extra_text: str = "", lens: bool = False) -> str:
    """Light/dark text per pane: `.on-dark` (smoked glass, light text) and
    `.on-light` (milky glass, dark text). The class is repeated to outrank the
    panes' own glass rules; the accent (active tiles) is left alone.

    `lens` (the compositor's liquid glass is on): what tools/liquid-demo.html
    settled — the capsules stay clear (no smoke/milk thickening), the ink is
    pure white or near-black and a halo (`halo-0..4`, tagged by swayctl-bar
    from how busy / mid-tone the backdrop is) carries the contrast; the ink
    glides to its new side instead of flipping."""
    if lens:
        return _lens_ink_css(accent_fg, extra_text)
    out = ["\n/* text that stands out on what's behind each pane */"]
    for cls, surface, text, tint, shadow, active, rim, inset in (
            ("on-dark", "#1c1c1e", "#f5f5f7", glass_tint(pct, True), "alpha(black, 0.35)", "alpha(white, 0.22)",
             "alpha(white, 0.14)", "alpha(white, 0.10)"),
            ("on-light", "#f5f5f7", "#1d1d1f", glass_tint(pct, False), "alpha(white, 0.45)", "alpha(black, 0.12)",
             "alpha(white, 0.55)", "alpha(white, 0.60)")):
        sel = f".{cls}.{cls}.{cls}"
        out.append(f"""
{sel}:not(.active):not(:selected) {{
  background: linear-gradient(180deg, alpha({surface}, {min(tint * 1.25, 1):.3f}), alpha({surface}, {tint * 0.75:.3f}));
  color: {text}; border-color: {rim}; box-shadow: inset 0 1px 0 {inset};
}}
.{cls} label, .{cls} image, .{cls} button, .{cls} text, .{cls} placeholder{extra_text} {{
  color: {text}; text-shadow: 0 1px 1px {shadow};
}}
.{cls} .workspace {{ color: alpha({text}, 0.75); }}
.{cls} .workspace.focused {{ background: {accent}; color: {accent_fg}; }}
.{cls} scale trough, .{cls} levelbar trough {{ background: alpha(black, 0.14); }}
.{cls} scale highlight {{ background: alpha({accent}, 0.95); }}
.{cls} scale slider {{ background: white; }}""")
    # glass thick enough for the hardest spot behind the pane (tagged tint-0..10)
    for step in range(11):
        for cls, surface in (("on-dark", "#1c1c1e"), ("on-light", "#f5f5f7")):
            a = step / 10
            out.append(f"\n.{cls}.{cls}.{cls}.tint-{step}:not(.active):not(:selected) {{ background: "
                       f"linear-gradient(180deg, alpha({surface}, {min(a * 1.1, 1):.2f}), alpha({surface}, {a * 0.9:.2f})); }}")
    out.append(f"""
.tile.active label, .tile.active image, :selected label, :selected image {{ color: {accent_fg}; text-shadow: none; }}
""")
    return "".join(out)


LENS_INK = (("on-dark", "#ffffff", "black"), ("on-light", "#111114", "white"))


def _halo(rgb: str, h: float) -> str:
    """The demo's halo at strength h (0..1): a tight edge plus a soft glow."""
    a = 0.35 + h * 0.6
    return (f"0 0 1px alpha({rgb}, {a:.2f}), 0 0 {4 + h * 6:.1f}px alpha({rgb}, {a:.2f}), "
            f"0 0 {h * 14:.1f}px alpha({rgb}, {a * 0.8:.2f})")


def _lens_ink_css(accent_fg: str, extra_text: str = "") -> str:
    out = ["\n/* liquid glass: ink that stands out on what's behind each capsule (tools/liquid-demo.html) */"]
    for cls, ink, halo in LENS_INK:
        out.append(f"""
.{cls}.{cls}.{cls}:not(.active):not(:selected) {{ color: {ink}; }}
.{cls} label, .{cls} image, .{cls} button, .{cls} text, .{cls} placeholder{extra_text} {{
  color: {ink}; text-shadow: {_halo(halo, 0.5)}; -gtk-icon-shadow: {_halo(halo, 0.5)};
}}
.{cls} .workspace {{ color: alpha({ink}, 0.78); }}
.{cls} scale trough, .{cls} levelbar trough, .{cls}.osd levelbar {{ background: alpha({'black, 0.18' if ink != '#ffffff' else 'white, 0.30'}); }}
.{cls} .tile-more:hover, .{cls} .tile-main:hover {{ background: alpha({'black, 0.07' if ink != '#ffffff' else 'white, 0.12'}); }}""")
        for step in range(5):
            out.append(f"\n.{cls}.halo-{step} label, .{cls}.halo-{step} image, .{cls}.halo-{step} button {{ "
                       f"text-shadow: {_halo(halo, step / 4)}; -gtk-icon-shadow: {_halo(halo, step / 4)}; }}")
    out.append(f"""
.workspace.focused label, .workspace.focused, .workspace.under-drop label, .workspace.under-drop, .tile.active label, .tile.active image, :selected label, :selected image {{
  color: {accent_fg}; text-shadow: 0 1px 2px alpha(black, 0.25); -gtk-icon-shadow: none;
}}
""")
    out.append(key_ink_css(accent_fg))
    return "".join(out)


# swayctl-fx's key ink (`glass_text auto`): text drawn in this colour over a
# pane of glass is inked light or dark by the compositor from what's behind
INK_KEY = "#FF00FE"


def key_ink_css(accent_fg: str) -> str:
    """swayctl-bar marks a window `.ink-key` when the compositor inks its text
    (swayctl-fx "glass-ink" with the glass on): every text and icon is drawn
    in the key, no halo; what sits on the accent (active tiles, the focused
    workspace, a selection) keeps its own colour."""
    k = INK_KEY
    return f"""
/* key ink: the compositor colours this text (swayctl-fx glass_text auto) */
window.ink-key label, window.ink-key image, window.ink-key button, window.ink-key text,
window.ink-key placeholder, window.ink-key .workspace, window.ink-key .window-title,
window.ink-key .tile:not(.active), window.ink-key .slider-row {{
  color: {k}; text-shadow: none; -gtk-icon-shadow: none;
}}
window.ink-key .workspace label {{ color: alpha({k}, 0.78); }}
window.ink-key .workspace.focused label, window.ink-key .workspace.focused,
window.ink-key .workspace.under-drop label, window.ink-key .workspace.under-drop,
window.ink-key .tile.active label, window.ink-key .tile.active image,
window.ink-key :selected label, window.ink-key :selected image,
window.ink-key .launcher-row.selected label, window.ink-key .launcher-row.selected image {{ color: {accent_fg}; }}
"""


def bar_size_css(height: int, border: float = 0, font_pt: float = 0) -> str:
    """swayctl-bar's modules sized from bar.height, both ways. The height
    alone only set the window's *minimum*: the pills kept their CSS sizes
    (4 px module margins, 3 px pill margins, GTK's 24 px button minimum), so
    the bar never got lower than ~34 px and a taller one just stretched the
    pills. Now each pill is the bar height less a small gap above and below,
    and what's inside it (workspace buttons, icons, text) grows or shrinks with it. 0 = fit the
    contents (no rules). `border`: the pills' border width (GTK's min-height
    is the content box: a 1.5 px glass rim adds 3 px to every pill).
    `font_pt`: the bar's font size; a bar lower than its text needs gets a
    smaller font instead of ignoring the height."""
    if not height:
        return ""
    h = max(int(height), 16)
    gap = min(6, max(1, round(h * 0.09)))   # air above/below each pill
    pill = h - 2 * gap - math.ceil(2 * border)
    inner = max(pill - 6, 8)                # workspace buttons: .workspaces pads 2 px, a focused one has a 1 px border
    # the text grows with the bar (the font size asked for at 30 px) and shrinks
    # to fit when the bar is lower; a line of text is ~1.3x the font's px size
    font = ""
    icon = max(round(inner * 0.9), 10)      # status / tray icons: 16 px in the 30 px bar
    if font_pt:
        px = max(min(font_pt * 4 / 3 * h / 30, inner / 1.3), 7)
        font = f"\nwindow.bar label {{ font-size: {px:.1f}px; }}"
    pills = ", ".join(f"window.bar .{c}" for c in ("workspaces", "clock", "status", "tray", "mode", "window-title"))
    return f"""
/* bar.height = {h}px: pills {pill}px with {gap}px above and below */
window.bar .module {{ margin-top: {gap}px; margin-bottom: {gap}px; }}
{pills} {{
  min-height: {pill}px; margin-top: {gap}px; margin-bottom: {gap}px;
  padding-top: 0; padding-bottom: 0;
}}
window.bar .workspaces {{ padding-top: 2px; padding-bottom: 2px; min-height: {pill - 4}px; }}
window.bar .workspace, window.bar .tray-item {{
  min-height: {inner}px; padding-top: 0; padding-bottom: 0; margin-top: 0; margin-bottom: 0;
}}
window.bar button {{ min-height: 0; }}
window.bar image {{ -gtk-icon-size: {icon}px; }}{font}
"""


def bar_padding_css(padding: int) -> str:
    """bar.padding: the room inside the bar's pills, left and right - the
    pills' own padding, each workspace button and tray icon, and the gap
    between the status icons (border-spacing on .status-row). 10 = the
    default look."""
    p = max(0, int(padding))
    ws = max(2, round(p * 0.6))
    return f"""
/* bar.padding = {p}px */
window.bar .clock, window.bar .status, window.bar .tray, window.bar .mode, window.bar .window-title {{
  padding-left: {p}px; padding-right: {p}px;
}}
window.bar .workspaces {{ padding-left: 2px; padding-right: 2px; }}
window.bar .workspace {{ padding-left: {ws}px; padding-right: {ws}px; min-width: {14 + p}px; }}
window.bar .tray-item {{ padding-left: {round(p / 2)}px; padding-right: {round(p / 2)}px; min-width: 0; }}
window.bar .status-row {{ border-spacing: {round(p * 0.8)}px 0; }}
"""


def bar_single_css(fill: str, rim: str, inset: str, radius: str = "999px") -> str:
    """bar.shape = single: the bar window is one pane (one capsule of glass
    when the compositor's glass is on: it shapes the glass by what's drawn),
    the groups inside are clear."""
    pills = ", ".join(f"window.bar .{c}" for c in ("workspaces", "clock", "status", "tray", "mode", "window-title"))
    return f"""
/* bar.shape = single: one bar of glass, the groups inside are clear */
window.bar {{ background: {fill}; border: {rim}; border-radius: {radius}; box-shadow: {inset}; }}
{pills} {{ background: none; border-color: transparent; box-shadow: none; }}
"""


def milk_fill(opacity: float) -> str:
    """OSD-style milky glass (volume/brightness pill): white fill whose
    thickness follows effects.glass_opacity (0..1). Never fully clear —
    shaped glass needs some alpha to follow."""
    a = max(opacity, 0.04)
    return (f"linear-gradient(180deg, alpha(white, {min(a * 0.84, 0.82):.3f}), "
            f"alpha(white, {min(a * 0.52, 0.62):.3f}))")


def shell_milk(base: float, glass: bool) -> float:
    """The shell's milk thickness (0..1) from effects.glass_opacity (0..100):
    the user's thickness only — no dark-theme smoke floor (the OSD look is the
    same either way). With the compositor's glass on, the demo precision lens
    wants a nearly clear body: milk only enough that shaped panes still draw
    (floor 4%). One formula for the bar, Quick Settings and this app."""
    a = max(base / 100, 0.04)
    if glass:
        # demo lens (winaviation): clear capsule, the rim is the effect
        return max(a * 0.20, 0.04)
    return a


def milk_opacity(ctx, theme=None) -> float:
    """effects.glass_opacity as 0..1 for milk glass (see shell_milk)."""
    base = ((ctx.values or {}).get("effects") or {}).get("glass_opacity", 50)
    return shell_milk(base, _glass(ctx))


# The shell's glass is the OSD look: milky pills, bright rim, dark content,
# accent-blue bars — not the theme's smoked surface + dark edge.
MILK_RIM = "1px solid alpha(white, 0.48)"
MILK_INSET = "inset 0 1px 0 alpha(white, 0.55)"
MILK_TEXT = "#1d1d1f"
# Demo precision lens (winaviation liquid-glass-demo capsule): bright white
# specular rim like the demo's edge highlight, soft bloom shadow under the
# capsule. The body tint is effects.glass_opacity (milk_opacity thins it while
# the compositor's glass is on, floor 4 % so shaped panes still draw).
LENS_RIM = "1.5px solid alpha(white, 0.88)"
LENS_INSET = "inset 0 1px 0 alpha(white, 0.55), inset 0 -1px 1px alpha(black, 0.10)"


GLASS_EDGE = MILK_RIM


def _text_shadow(k: dict) -> str:
    """Lifts text off the glass: a dark shadow under light text, a light glow under dark text."""
    if themes.luminance(k["text"]) < 0.5:
        return "0 1px 1px alpha(white, 0.45)"
    return "0 1px 2px alpha(black, 0.35)"


def _file_hash(path: Path) -> str:
    """Change marker for a user file we pass to a program by path."""
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest() + "\n"
    except OSError:
        return "missing\n"


def _render_template(path: str, theme, ctx: Context) -> str:
    text = theming.expand(path).read_text()  # OSError -> reported by apply_extra
    return theming.render(text, theming.placeholders(theme, (ctx.values or {}).get("font")))


def _rgb_triplet(hex_color: str) -> str:
    return ", ".join(str(int(hex_color[i:i + 2], 16)) for i in (1, 3, 5))


def read_base(path: str) -> Any:
    """The user's own config file (JSON with comments), or None."""
    if not path:
        return None
    return jsonc.loads(theming.expand(path).read_text())


def apply_map(cfg: dict, v: dict[str, Any], mapping: dict[str, str]) -> None:
    for key, cfg_key in mapping.items():
        cfg[cfg_key] = v[key]


def values_from(cfg: dict, mapping: dict[str, str]) -> dict[str, Any]:
    return {key: cfg[cfg_key] for key, cfg_key in mapping.items() if cfg_key in cfg}


class Component:
    name = ""
    depends_on: tuple[str, ...] = ("theme", "font", "effects")
    tolerated_errors = ()
    # pgrep arguments that find this program when someone else started it
    detect: list[list[str]] = []

    @property
    def sections(self) -> tuple[str, ...]:
        return (self.name,)

    def programs(self, v: dict[str, Any], ctx: Context) -> dict[str, list[str]]:
        """{unit suffix: argv}; "" for a single program."""
        raise NotImplementedError

    def program_env(self, suffix: str, v: dict[str, Any], ctx: Context) -> dict[str, str]:
        """Extra environment for one program's unit."""
        return {}

    def detect_for(self, suffix: str) -> list[list[str]]:
        """pgrep arguments finding someone else's copy of one program."""
        return self.detect

    def files(self, v: dict[str, Any], ctx: Context) -> dict[str, str]:
        """{file name: content} written to generated/<name>/"""
        return {}

    def reload(self, unit: str) -> None:
        """Pick up changed files without a restart where the program supports it."""
        units.stop(unit)  # the next apply_extra step starts it again

    def unit_name(self, suffix: str) -> str:
        return f"{units.PREFIX}{self.name}{'-' + suffix if suffix else ''}.service"

    def gen_dir(self, ctx: Context) -> Path:
        return ctx.data_dir / "generated" / self.name

    def commands(self, section, v, changed, ctx=None) -> list[str]:
        return []

    def _write_files(self, v, ctx) -> bool:
        changed = False
        d = self.gen_dir(ctx)
        for name, content in self.files(v, ctx).items():
            path = d / name
            try:
                if path.read_text() == content:
                    continue
            except OSError:
                pass
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            changed = True
        return changed

    def all_units(self, v, ctx) -> list[str]:
        return [self.unit_name(s) for s in self.programs(v, ctx)]

    def apply_extra(self, section: str, v: dict[str, Any], changed: set[str] | None,
                    ctx: Context | None = None) -> list[str]:
        wanted = {self.unit_name(s): argv for s, argv in self.programs(v, ctx).items()}
        if not v["managed"]:
            self.stop_all(v, ctx)
            return []
        try:
            files_changed = self._write_files(v, ctx)
        except OSError as e:
            return [f"{self.name}: {e}"]
        errors = []
        suffix_of = {self.unit_name(s): s for s in self.programs(v, ctx)}
        for unit, argv in wanted.items():
            if not units.installed(argv[0]):
                # an optional helper that isn't installed mustn't take the rest down
                errors.append(f"{argv[0]} is not installed")
                continue
            desc = f"swayctl-center {self.name}: {shlex.join(argv)}"
            st = units.state(unit)
            if st.active and units.from_other_session(unit):
                # left running from the last login: its environment (and so
                # everything it opens) points at a sway that's gone
                units.stop(unit)
                st = units.state(unit)
            if st.active and st.description == desc:
                if files_changed:
                    self.reload(unit)
                    if units.state(unit).active:
                        continue
                else:
                    continue
            elif st.active:
                units.stop(unit)
            suffix = unit[len(self.unit_name("")) - len(".service"):-len(".service")].lstrip("-")
            others = self.foreign(v, ctx, suffix)
            if others:
                others = self.adopt_strays(others)
            if others:
                errors.append(f"{self.name}: {argv[0]} is already running outside swayctl-center "
                              f"(pid {', '.join(map(str, others))}); remove it from your sway config "
                              "or turn off \"Managed by swayctl-center\"")
                return errors
            err = units.start(unit, argv, desc, extra_env=self.program_env(suffix_of[unit], v, ctx))
            if err:
                errors.append(f"{self.name}: could not start {argv[0]}: {err}")
        return errors

    def adopt_strays(self, pids: list[int]) -> list[int]:
        """Copies of the program that only look like someone else's setup (a key binding started
        one); they are ended so the managed one can run. Returns the pids that really are
        someone else's."""
        return pids

    def foreign(self, v, ctx, suffix: str | None = None) -> list[int]:
        own = self.all_units(v, ctx)
        patterns = self.detect if suffix is None else self.detect_for(suffix)
        pids: list[int] = []
        for args in patterns:
            pids += units.foreign_pids(args, own)
        return sorted(set(pids))

    def stop_all(self, v, ctx) -> None:
        for unit in self.all_units(v, ctx):
            if units.state(unit).active:
                units.stop(unit)

    def status(self, v, ctx) -> dict[str, Any]:
        progs = self.programs(v, ctx)
        missing = sorted({argv[0] for argv in progs.values() if not units.installed(argv[0])})
        running = [units.state(self.unit_name(s)).active for s, argv in progs.items()
                   if argv[0] not in missing]
        return {"managed": v["managed"], "running": bool(running) and all(running),
                "foreign_pids": self.foreign(v, ctx), "missing": missing}

    def is_running_elsewhere(self, suffix: str | None = None) -> bool:
        patterns = self.detect if suffix is None else self.detect_for(suffix)
        return any(units.foreign_pids(args, []) for args in patterns)

    def import_current(self, ipc: swayipc.Connection, config: swayconfig.Config,
                       ctx: Context) -> dict[str, dict[str, Any]]:
        # Already started by the user's setup: leave it to them.
        if self.is_running_elsewhere():
            return {self.name: {"managed": False}}
        return {}


# --- bar -------------------------------------------------------------------

# Icons are Nerd Font (Material Design) glyphs from ttf-nerd-fonts-symbols;
# the bar's CSS falls back to "Symbols Nerd Font" for them.
_VOLUME = ["\U000f057f", "\U000f0580", "\U000f057e"]
_WIFI = ["\U000f091f", "\U000f0922", "\U000f0925", "\U000f0928"]
# empty, 10%, 20% ... 90%, full; charging the same, with a bolt
_BATTERY = ["\U000f008e", "\U000f007a", "\U000f007b", "\U000f007c", "\U000f007d", "\U000f007e",
            "\U000f007f", "\U000f0080", "\U000f0081", "\U000f0082", "\U000f0079"]
_BATTERY_CHARGING = ["\U000f089f", "\U000f089c", "\U000f0086", "\U000f0087", "\U000f0088", "\U000f089d",
                     "\U000f0089", "\U000f089e", "\U000f008a", "\U000f008b", "\U000f0085"]
_BELL, _BELL_DOT, _BELL_OFF = "\U000f009a", "\U000f009c", "\U000f009b"

WAYBAR_MODULE_CONFIG: dict[str, dict[str, Any]] = {
    "sway/workspaces": {"disable-scroll": True},
    "sway/window": {"max-length": 60},
    "clock": {"format": "{:%H:%M}", "format-alt": "{:%a %d %b  %H:%M}",
              "tooltip-format": "<tt>{calendar}</tt>"},
    "tray": {"spacing": 8},
    "pulseaudio": {"format": "{icon}", "format-muted": "\U000f075f", "format-icons": {"default": _VOLUME},
                   "tooltip-format": "{volume}% · {desc}",
                   "on-click": "pavucontrol", "scroll-step": 5},
    "network": {"format-wifi": "{icon}", "format-icons": _WIFI, "format-ethernet": "\U000f0200",
                "format-disconnected": "\U000f092e", "tooltip-format": "{ifname} {ipaddr}",
                "tooltip-format-wifi": "{essid} {signalStrength}%\n{ipaddr}"},
    "bluetooth": {"format": "\U000f00af", "format-disabled": "", "format-off": "\U000f00b2",
                  "format-connected": "\U000f00b1", "tooltip-format-connected": "{device_enumerate}",
                  "tooltip-format-enumerate-connected": "{device_alias}"},
    # just the icon; the percentage and time left are in the tooltip
    "battery": {"format": "{icon}", "format-icons": {"default": _BATTERY, "charging": _BATTERY_CHARGING,
                                                     "plugged": _BATTERY_CHARGING},
                "tooltip-format": "{capacity}% · {timeTo}",
                "states": {"warning": 25, "critical": 10}},
    "backlight": {"format": "{icon}", "tooltip-format": "{percent}%", "format-icons": ["\U000f00de", "\U000f00df", "\U000f00e0"]},
    "cpu": {"format": "\U000f035b {usage}%"},
    "memory": {"format": "\U000f061a {}%"},
    "temperature": {"format": "\U000f050f {temperatureC}°C"},
    "idle_inhibitor": {"format": "{icon}", "format-icons": {"activated": "\U000f0176", "deactivated": "\U000f0faa"},
                       "tooltip-format-activated": "Staying awake", "tooltip-format-deactivated": "Locks when idle"},
    "power-profiles-daemon": {"format": "{icon}", "format-icons": {
        "performance": "\U000f04c5", "balanced": "\U000f0f85", "power-saver": "\U000f0f86", "default": "\U000f0f85"}},
    "keyboard-state": {"capslock": True, "format": "{icon}",
                       "format-icons": {"locked": "\U000f0a9b", "unlocked": ""}},
    "custom/notifications": {"exec": "swaync-client -swb", "return-type": "json", "format": "{icon}",
                             "format-icons": {"notification": _BELL_DOT, "none": _BELL,
                                              "dnd-notification": _BELL_OFF, "dnd-none": _BELL_OFF,
                                              "inhibited-notification": _BELL_DOT, "inhibited-none": _BELL,
                                              "dnd-inhibited-notification": _BELL_OFF, "dnd-inhibited-none": _BELL_OFF},
                             "on-click": "swaync-client -t -sw", "on-click-right": "swaync-client -d -sw",
                             "escape": True},
}


BAR_MAP = {
    "position": "position", "layer": "layer", "height": "height", "spacing": "spacing",
    "margin_top": "margin-top", "margin_right": "margin-right", "margin_bottom": "margin-bottom",
    "margin_left": "margin-left", "exclusive": "exclusive", "modules_left": "modules-left",
    "modules_center": "modules-center", "modules_right": "modules-right",
}


# waybar module -> swayctl-bar module; anything in STATUS_MODULES is shown by the
# one status cluster that opens Quick Settings
NATIVE_MODULES = {"sway/workspaces": "workspaces", "sway/mode": "mode", "sway/window": "window", "clock": "clock",
                  "tray": "tray"}
STATUS_MODULES = {"pulseaudio", "wireplumber", "network", "battery", "bluetooth", "backlight",
                  "power-profiles-daemon", "idle_inhibitor", "custom/notifications", "cpu", "memory"}
OSD_KEYS = (("XF86AudioRaiseVolume", "volume-up"), ("XF86AudioLowerVolume", "volume-down"),
            ("XF86AudioMute", "volume-mute"), ("XF86MonBrightnessUp", "brightness-up"),
            ("XF86MonBrightnessDown", "brightness-down"))


class BarModule(Component):
    name = "bar"
    # swayctl-bar also shows the notifications (settings in their own section)
    depends_on = Component.depends_on + ("notifications", "background", "launcher", "clipboard")
    detect = [["-x", "waybar"], ["-x", "swayctl-bar"]]

    def __init__(self):
        self._hidden: dict[str, str] = {}  # sway bar id -> its mode before we hid it

    # `swayctl-bar osd|quick|launcher|...` forwards to the running bar; with none running it
    # starts one instead - a bar nobody manages (and, with no --config-dir, one with no settings)
    STRAY_SUBCOMMANDS = ("osd", "quick", "launcher", "tray-menu", "dnd")

    @classmethod
    def is_stray(cls, argv: list[str]) -> bool:
        """Is this command line a swayctl-bar started by a key binding or a click, not the bar itself?"""
        if not argv or Path(argv[0]).name != "swayctl-bar":
            return False
        rest, skip = [], False
        for a in argv[1:]:
            if skip:
                skip = False
            elif a == "--config-dir":
                skip = True
            elif not a.startswith("--config-dir="):
                rest.append(a)
        return bool(rest) and rest[0] in cls.STRAY_SUBCOMMANDS

    def adopt_strays(self, pids: list[int]) -> list[int]:
        keep = []
        for pid in pids:
            try:
                argv = [a.decode() for a in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if a]
            except OSError:
                keep.append(pid)  # can't tell what it is: leave it to the caller, as before
                continue
            if not self.is_stray(argv):
                keep.append(pid)
                continue
            log.info("bar: ending a swayctl-bar that a key binding started (pid %s: %s)", pid, " ".join(argv))
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                continue
            for _ in range(40):  # up to 2 s for it to let go of the bar's windows and its D-Bus name
                if not Path(f"/proc/{pid}").exists():
                    break
                time.sleep(0.05)
        return keep

    def snapshot(self, ipc) -> dict[str, str]:
        """sway's own bars (`bar { }` in the config, e.g. the stock swaybar): {id: mode}."""
        return {bar_id: ipc.get_bar_config(bar_id).get("mode", "dock")
                for bar_id in ipc.get_bar_config() or []}

    def commands(self, section, v, changed, ctx=None) -> list[str]:
        """While waybar is managed, sway's own bars are made invisible so there
        aren't two bars (the stock config starts swaybar); they come back when
        the bar isn't managed any more. `sway reload` shows them again, and the
        re-apply after it hides them again."""
        bars = (ctx.live if ctx else None) or {}
        cmds = self.osd_keys(v)
        if v["managed"]:
            for bar_id, mode in bars.items():
                if mode != "invisible":
                    self._hidden[bar_id] = mode
                    cmds.append(f"bar {bar_id} mode invisible")
            return cmds
        cmds += [f"bar {bar_id} mode {mode}" for bar_id, mode in self._hidden.items()
                 if bars.get(bar_id) == "invisible"]
        self._hidden.clear()
        return cmds

    def osd_keys(self, v) -> list[str]:
        """Volume and brightness keys show swayctl-bar's OSD while it is the bar."""
        if v["managed"] and v["program"] == "swayctl-bar":
            self._osd_bound = True
            return [f"bindsym --no-warn --locked {key} exec swayctl-bar osd {what}" for key, what in OSD_KEYS]
        if getattr(self, "_osd_bound", False):
            self._osd_bound = False
            return [f"unbindsym --locked {key}" for key, _ in OSD_KEYS]
        return []

    def programs(self, v, ctx):
        d = self.gen_dir(ctx)
        if v["program"] == "swayctl-bar":
            return {"": ["swayctl-bar", "--config-dir", str(d)]}
        return {"": ["waybar", "-c", str(d / "config.json"), "-s", str(d / "style.css")]}

    def margins(self, v, ctx) -> dict[str, int]:
        # The bar is attached to the screen edge, one flat bar like the frame style's: never a floating pill.
        # The margin keys are hidden; values saved by older versions (8 px) must not detach it.
        return {k: 0 for k in ("top", "right", "bottom", "left")}

    def shape_css(self, v, ctx, t) -> str:
        """One flat bar (the default), or a piece per group."""
        if v.get("shape", "pieces") != "single":
            return ""
        k = ctx.theme.tokens if ctx.theme else {}
        # attached to the edge, solid, no rim and no rounding: like the frame style's bar
        return bar_single_css(k.get("surface", "@window_bg_color"), "none", "none", "0")

    def native_config(self, v, ctx) -> dict[str, Any]:
        """config.json for swayctl-bar: waybar module names map onto its few
        modules; everything status-like becomes the one Quick Settings cluster."""
        def side(names):
            out = []
            for n in names:
                m = schema.bar_module(n)
                if m and m not in out:
                    out.append(m)
            return out
        left, center, right = side(v["modules_left"]), side(v["modules_center"]), side(v["modules_right"])
        # one status cluster per bar: keep the last one (right side wins)
        for i, part in enumerate((left, center)):
            if "status" in part and "status" in (center + right if i == 0 else right):
                part.remove("status")
        if "status" not in left + center + right:
            right.append("status")  # Quick Settings must stay reachable
        m = self.margins(v, ctx)
        strip = schema.strftime_format
        return {"position": v["position"], "layer": v["layer"], "height": v["height"], "spacing": v["spacing"],
                "margins": [m["top"], m["right"], m["bottom"], m["left"]], "exclusive": v["exclusive"],
                "modules_left": left, "modules_center": center, "modules_right": right,
                "clock_format": strip(v["clock_format"]), "clock_format_alt": strip(v["clock_format_alt"]),
                "settings_command": "swayctl-center ui --page {page}",
                "icon_style": v.get("icon_style", "ipados"),
                "frame": self.frame_config(ctx),
                "wallpaper": self.wallpaper_config(ctx),
                "notifications": self.notifications_config(ctx),
                "backdrop": self.backdrop_config(ctx),
                "launcher": self.launcher_config(ctx)}

    @staticmethod
    def frame_config(ctx) -> dict[str, Any]:
        fx = (ctx.values or {}).get("effects") or {}
        pct = fx.get("glass_opacity", 10)
        return {"glass": glass_desk(ctx) and _glass(ctx), "radius": fx.get("corner_radius", 12),
                # the pane's white body: thin, but never none (shaped glass follows the alpha it reads)
                "tint": round(max(0.04, min(0.4, pct / 100 * 0.6)), 3)}

    @staticmethod
    def wallpaper_config(ctx) -> dict[str, Any]:
        from .background import video_path
        return {"video": video_path(ctx.values or {}, ctx.data_dir)}

    @staticmethod
    def launcher_config(ctx) -> dict[str, Any]:
        from .launcher import LauncherModule
        values = ctx.values or {}
        clip = (values.get("clipboard") or schema.defaults()["clipboard"]).get("managed", True)
        return LauncherModule.bar_config(values.get("launcher") or schema.defaults()["launcher"], clipboard=clip)

    @staticmethod
    def backdrop_config(ctx) -> dict[str, Any]:
        """What's behind the bar (it keeps windows off its strip): the
        wallpaper, so each module can pick light or dark text over it."""
        b = (ctx.values or {}).get("background") or {}
        color = b.get("color") or (ctx.theme.bg if ctx.theme else "#000000")
        image = str(ctx.data_dir / b["image"]) if b.get("image") else ""
        pct = ((ctx.values or {}).get("effects") or {}).get("glass_opacity", 50)
        # each module is smoked glass with light text or milky glass with dark
        # text, whichever stands out more there; these are the two tints
        fx = (ctx.values or {}).get("effects") or {}
        # with liquid glass on: the capsules' white body (glass_opacity, as
        # the CSS paints it) lifts what the text sits on, and frost
        # (glass_blur) wipes the detail a halo has to fight — the ink pick
        # follows both, like tools/liquid-demo.html
        # no liquid glass: the theme's own colours, text included, whatever is
        # behind (nothing to sample, no per-pane light/dark tags)
        # a glass frame under a clear bar: the text picks light or dark from what is behind it
        # (the wallpaper through the glass), not from the compositor's ink (the bar has no glass of its own)
        return {"adaptive": _glass(ctx), "image": image, "mode": b.get("mode", "fill"), "color": color,
                "tint_dark": glass_tint(pct, True), "tint_light": glass_tint(pct, False),
                "lens": _glass(ctx), "lens_tint": round(shell_milk(pct, True), 4),
                # without liquid glass the theme decides light or dark, like macOS' Appearance
                "theme": "" if _glass(ctx) or not ctx.theme else ("dark" if ctx.theme.dark else "light"),
                "frost": round(fx.get("glass_blur", 0) / 100, 3)}

    @staticmethod
    def notifications_config(ctx) -> dict[str, Any]:
        n = (ctx.values or {}).get("notifications") or {}
        return {"enabled": NotificationsModule.native(n),
                "position_x": n.get("position_x", "right"), "position_y": n.get("position_y", "top"),
                "output": n.get("output", ""), "width": n.get("width", 380),
                "timeout": n.get("timeout", 8), "timeout_low": n.get("timeout_low", 4),
                "timeout_critical": n.get("timeout_critical", 0), "max_visible": n.get("max_visible", 4),
                "dnd_on_start": n.get("dnd_on_start", False)}

    def native_css(self, ctx, t) -> str:
        k = t.tokens
        family, size = _font(ctx)
        modern = _modern(ctx)
        glass = _glass(ctx)
        radius = k["radius_lg"] if modern else 0
        # The OSD look is the shell's look: milky white panels, dark content,
        # accent-blue bars — with or without the compositor's glass on top.
        # When glass is on, panels stay clear (glass_css paints the pills only).
        smoked = modern and t.dark and not glass  # dark theme: smoked material, light text
        milk = "alpha(#1c1c1e, 0.84)" if smoked else "alpha(#ececf1, 0.82)"  # no blur behind: thicker
        chip = "alpha(white, 0.10)" if smoked else "alpha(white, 0.42)"
        rim = "alpha(white, 0.14)" if smoked else "alpha(white, 0.48)"
        ink = "#f5f5f7" if smoked else MILK_TEXT
        text = ink if modern else k["text"]
        # The bar is never glass: it is one plain material (the popups may be), whatever the glass setting
        # (attached to the screen edge, solid, square, no rim: like the frame style's bar)
        bar_text = k["text"]
        bar_bg = k["surface"]
        border = "border: none;"
        ws_color = k["text_secondary"]
        panel_bg = "none" if glass else (milk if modern else k["surface_overlay"])
        panel_border = "transparent" if glass else (rim if modern else k["outline"])
        tile_bg = "none" if glass else (chip if modern else f"alpha({k['text']}, 0.08)")
        return f"""/* generated by swayctl-center; edits are overwritten */
{theming.adwaita_css(t)}
* {{ font-family: "{family}", sans-serif; font-weight: {_font_weight(ctx)}; }}
window.bar {{ background: {bar_bg}; color: {bar_text}; border-radius: 0; {border} box-shadow: none; font-size: {size}pt; }}
.workspace, .clock, .status, .mode {{ border-radius: {k['radius_sm'] if modern else 0}px; }}
.workspace {{ color: {ws_color}; }}
.workspace.focused {{ background: {k['accent']}; color: {k['accent_fg']}; }}
.workspace.under-drop {{ color: {k['accent_fg']}; }}
.workspace.urgent {{ background: {k['error']}; color: #ffffff; }}
.battery-percent.warning {{ color: {k['warning']}; }}
.battery-percent.critical {{ color: {k['error']}; }}
.quick-panel {{ background: {panel_bg}; color: {text}; border-color: {panel_border};
  border-radius: {_panel_radius(k)}px; }}
.tile {{ background: {tile_bg}; color: {text}; }}
.tile.active {{ background: {k['accent']}; color: {k['accent_fg']}; }}
/* OSD: milky pill, macOS-like (dark icon/percent, accent-blue bar) */
.osd {{ background: {"alpha(#1c1c1e, 0.78)" if smoked else "alpha(white, 0.72)"}; color: {ink}; border-radius: 999px;
  border: 1px solid {rim}; }}
.osd image, .osd label {{ color: {ink}; }}
.osd label {{ font-weight: 600; font-size: 1.15em; }}
.osd levelbar, .osd levelbar trough {{ background: {"alpha(white, 0.20)" if smoked else "alpha(black, 0.14)"}; min-height: 12px;
  border-radius: 999px; border: none; }}
.osd levelbar block.filled {{ background: {k['accent']}; min-height: 12px; border-radius: 999px; }}
.notification-card {{ background: {panel_bg}; color: {text}; border-color: {panel_border};
  border-radius: {_panel_radius(k) if modern else k['radius_md']}px; font-size: {size}pt; }}
.notification-card.critical {{ border-color: {k['error']}; }}
""" + self.flat_modules_css() + (self.chips_css(smoked) if modern and not glass else "") + (self.glass_css(k, milk_opacity(ctx, t)) if glass else "") + (self.smoked_css(k) if smoked else "") + frame_css(ctx) + glass_desk_css(ctx) + popup_flat_css(ctx) + minimal_css(ctx, t)

    @staticmethod
    def flat_modules_css() -> str:
        """Without liquid glass the bar is one material (like the macOS menu bar):
        its modules are plain text on it, not a second pane each. The class is
        repeated to outrank the ink tags' (.on-dark / .on-light) own fills."""
        return """
/* one bar, flat modules (generated) */
window.bar .module.module.module.module.module { background: none; border-color: transparent; box-shadow: none; }
window.bar .workspaces.workspaces.workspaces.workspaces.workspaces { padding: 0 2px; }
"""

    @staticmethod
    def chips_css(smoked: bool) -> str:
        """Tiles, sliders and the media card as chips on the popup's material:
        white on the light panel, a lighter smoke on the dark one. Specific enough
        to beat the ink tags' fills."""
        fill = "alpha(white, 0.10)" if smoked else "alpha(white, 0.78)"
        rim = "alpha(white, 0.14)" if smoked else "alpha(black, 0.07)"
        sel = ", ".join(f".{c}.{c}.{c}.{c}.{c}.{c}:not(.active)" for c in ("tile", "slider-row", "media"))
        return f"""
/* chips on the popup material (generated) */
{sel} {{ background: {fill}; border: 1px solid {rim}; box-shadow: none; }}
/* a menu is read over any window: nearly solid */
.tray-menu.tray-menu {{ background: {"alpha(#1c1c1e, 0.93)" if smoked else "alpha(#f2f2f7, 0.94)"}; border: 1px solid {rim}; }}
"""

    @staticmethod
    def smoked_css(k) -> str:
        """The panes default.css paints milky (white fill, dark text), as smoked
        glass for a dark theme: Quick Settings' sliders and media card, the
        tray menu, the launcher's sheets, the notification actions."""
        ink, fill, rim, trough = "#f5f5f7", "alpha(#1c1c1e, 0.84)", "alpha(white, 0.14)", "alpha(white, 0.20)"
        return f"""
/* dark theme: smoked material (generated) */
.slider-row, .media {{ background: alpha(white, 0.10); color: {ink}; border-color: {rim}; }}
.media-title, .tile-title {{ color: {ink}; }}
scale trough {{ background: {trough}; }}
.tray-menu {{ background: {fill}; color: {ink}; border: 1px solid {rim}; }}
.tray-menu-item:hover {{ background: alpha(white, 0.10); }}
.launcher-search, .launcher-results, .launcher-keys, .launcher-suggest {{
  background: {fill}; color: {ink}; border-color: {rim}; box-shadow: inset 0 1px 0 alpha(white, 0.10);
}}
.launcher-row:hover {{ background: alpha(white, 0.08); }}
.quick-footer button, .media button {{ color: {ink}; }}
.notification-app, .notification-summary {{ color: {ink}; }}
"""

    @staticmethod
    def adaptive_css(ctx) -> str:
        """Every pane tagged by swayctl-bar from what's behind it (bar modules
        from the wallpaper, popups from a look at the screen as they open):
        smoked glass with light text (on-dark) or milky glass with dark text
        (on-light), whichever stands out more there."""
        return adaptive_css(((ctx.values or {}).get("effects") or {}).get("glass_opacity", 50),
                            (ctx.theme.tokens if ctx.theme else {}).get("accent", "#0a84ff"),
                            (ctx.theme.tokens if ctx.theme else {}).get("accent_fg", "#ffffff"),
                            lens=_glass(ctx))

    @staticmethod
    def glass_css(k, opacity: float = 0.08) -> str:
        """Demo precision lens (winaviation liquid-glass-demo capsule): the
        popups (Quick Settings, the volume pill, the launcher, notifications) are clear pills — the compositor's Snell bezel
        bends what's behind; CSS only draws a bright specular rim + soft bloom
        so the capsule reads like the demo, not a milky Tahoe panel."""
        # the pill tint follows effects.glass_opacity (milk_opacity thins it
        # while the compositor's glass is on, floor 4 % so shaped panes draw)
        # No *outer* box-shadow on the capsules: the compositor reads this
        # surface's alpha as the pane shape (glass.frag), and a drop shadow
        # lingers between capsules — the shader would take the whole panel
        # box for one pane.
        body = f"alpha(white, {opacity:.3f})"
        rim = LENS_RIM
        inset = LENS_INSET
        return f"""
/* liquid glass: demo precision lens — clear capsules, bright specular rim */
.osd {{
  background: {body};
  border: {rim};
  box-shadow: {inset};
  border-radius: 999px;
  color: {MILK_TEXT};
}}
.osd image, .osd label {{ color: {MILK_TEXT}; text-shadow: none; }}
.osd label {{ font-weight: 600; font-size: 1.15em; }}
.osd levelbar, .osd levelbar trough {{
  background: alpha(black, 0.14); border: none; box-shadow: none;
  border-radius: 999px; min-height: 12px;
}}
.osd levelbar block.filled {{
  background: {k['accent']}; border: none; border-radius: 999px; min-height: 12px;
}}
/* Quick Settings: no panel; every control is its own lens capsule */
window.quick-window, window.quick-catcher {{ background: none; background-color: transparent; }}
.quick-panel, .quick-main, .quick-panel > box, navigation-view, navigation-view > widget,
.quick-panel navigation-view {{ background: none; background-color: transparent;
  border: none; box-shadow: none; }}
.quick-panel {{ padding: 12px; }}
.slider-row {{
  background: {body};
  border: {rim};
  box-shadow: {inset};
  border-radius: 999px; padding: 8px 16px;
  color: {MILK_TEXT};
}}
.slider-row image, .slider-row button {{ color: {MILK_TEXT}; }}
/* a tray item's menu: one pane of glass under the icon */
.tray-menu {{
  background: {body};
  border: {rim};
  box-shadow: {inset};
  border-radius: 22px;
  color: {MILK_TEXT};
}}
.tray-menu label, .tray-menu image {{ color: {MILK_TEXT}; }}
.quick-panel headerbar {{
  background: {body}; border-radius: 999px; margin-bottom: 8px;
  border: {rim}; box-shadow: {inset};
  color: {MILK_TEXT};
}}
/* label alone already styles every label; a window.bar label here would
   outrank adaptive .on-dark label and pin bar text dark even on smoked
   glass. */
.tile:not(.active) {{ color: {MILK_TEXT}; }}
.tile {{
  background: {body};
  border: {rim};
  box-shadow: {inset}, inset 0 -1px 0 alpha(black, 0.05);
}}
.tile.active {{
  background: linear-gradient(180deg, alpha({k['accent']}, 0.96), alpha({k['accent']}, 0.80));
  border: 1px solid alpha(white, 0.35);
  box-shadow: inset 0 1px 0 alpha(white, 0.35);
  color: {k['accent_fg']};
}}
.tile.active label {{ color: {k['accent_fg']}; text-shadow: none; }}
.quick-footer button, .media button {{
  background: {body};
  border: {rim};
  box-shadow: {inset};
  color: {MILK_TEXT};
}}
.media {{
  background: {body}; border: {rim}; box-shadow: {inset};
  color: {MILK_TEXT};
}}
.media-title {{ color: {MILK_TEXT}; }}
/* Spotlight launcher: search capsule, results sheet, key hints — each a lens.
   A thicker body than the bar's (at least 16 %, tools/spotlight-demo.html's
   "spotlight" preset): rows of small text over whatever page is behind. */
window.launcher-window {{ background: none; background-color: transparent; }}
.launcher-search, .launcher-results, .launcher-suggest, .launcher-keys {{
  background: alpha(white, {max(opacity, 0.16):.3f}); border: {rim}; box-shadow: {inset}; color: {MILK_TEXT};
}}
/* macOS-style bars everywhere: accent fill on a soft dark trough */
scale trough {{ background: alpha(black, 0.14); min-height: 12px; border-radius: 999px; border: none; }}
scale highlight {{ background: {k['accent']}; min-height: 12px; border-radius: 999px; }}
scale slider {{ background: white; box-shadow: 0 0 0 1px alpha(black, 0.12), 0 1px 4px alpha(black, 0.25); }}
.workspace.focused {{
  background: alpha({k['accent']}, 0.92); color: {k['accent_fg']};
  border: 1px solid alpha(white, 0.35);
  box-shadow: inset 0 1px 0 alpha(white, 0.30);
}}
.workspace.focused label, .workspace.under-drop label {{ color: {k['accent_fg']}; }}
.workspace.under-drop {{ color: {k['accent_fg']}; }}
/* sub-pages (Wi-Fi, Sound Output, Power Mode, Power): header, rows, buttons
   are clear lens capsules like the demo */
.quick-panel headerbar {{
  background: {body};
  border: {rim}; border-radius: 999px; margin-bottom: 10px; min-height: 40px;
  box-shadow: {inset};
}}
.quick-panel headerbar button {{ border-radius: 999px; color: {MILK_TEXT}; }}
.quick-panel list.boxed-list {{ background: none; border: none; box-shadow: none; }}
.quick-panel list.boxed-list > row {{
  background: {body};
  border: {rim}; border-radius: 999px; margin-bottom: 6px;
  box-shadow: {inset};
}}
.quick-panel list.boxed-list > row:hover {{ background: alpha(black, 0.06); }}
.quick-panel list.boxed-list > row:focus-visible {{ outline: none; background: alpha(black, 0.08); }}
.quick-panel list.boxed-list > row > label {{ margin: 12px; color: {MILK_TEXT}; }}
.quick-panel scrolledwindow, .quick-panel scrolledwindow > viewport {{ background: none; }}
.quick-panel checkbutton check {{ background: alpha(black, 0.14); border: none; }}
.quick-panel checkbutton check:checked {{ background: {k['accent']}; }}
.quick-panel button.flat:not(.circular):not(.pill-button) {{
  background: {body}; border: {rim}; border-radius: 999px;
  box-shadow: {inset}; padding: 8px 16px; color: {MILK_TEXT};
}}
.quick-panel headerbar button.flat {{ background: none; border: none; box-shadow: none; padding: 4px; }}
/* notifications: each card is a clear lens capsule (shaped by its alpha) */
.notification-card {{
  background: {body};
  border: {rim};
  box-shadow: {inset}, inset 0 0 0 1px alpha(white, 0.08);
  color: {MILK_TEXT};
}}
.notification-card.critical {{ box-shadow: inset 0 0 0 1px alpha({k['error']}, 0.85), {inset}; }}
.notification-card label {{ text-shadow: none; color: {MILK_TEXT}; }}
.notification-app {{ color: alpha({MILK_TEXT}, 0.70); }}
.notification-action, .notification-close {{
  background: alpha(white, 0.18);
  box-shadow: {inset}; border: {rim}; border-radius: 999px;
  color: {MILK_TEXT};
}}
/* the "Notifications / Clear" heading sits on glass too */
.quick-notifications > box:first-child {{
  background: {body}; border: {rim}; border-radius: 999px; padding: 2px 4px 2px 14px;
  box-shadow: {inset};
  color: {MILK_TEXT};
}}
.quick-notifications .notification-card {{
  background: {body};
}}
"""

    def config(self, v, ctx) -> dict[str, Any]:
        base = read_base(v["config_file"])
        if isinstance(base, list):  # several bars: settings apply to the first
            base = base[0] if base else {}
        cfg = copy.deepcopy(base) if isinstance(base, dict) else {}
        if v["config_file"] and "include" in cfg:
            # relative includes were relative to the user's file, not ours
            here = theming.expand(v["config_file"]).parent
            inc = cfg["include"] if isinstance(cfg["include"], list) else [cfg["include"]]
            cfg["include"] = [str((here / Path(i).expanduser()).resolve()) for i in inc]
        # modules the base config already uses keep waybar's own defaults;
        # only ones added here get our built-in settings
        known = {m for k in ("modules-left", "modules-center", "modules-right") for m in cfg.get(k, [])}
        apply_map(cfg, v, BAR_MAP)
        if not v["height"]:
            cfg.pop("height")  # 0 = let waybar size it
        for m in v["modules_left"] + v["modules_center"] + v["modules_right"]:
            if m not in cfg and m not in known:
                cfg[m] = copy.deepcopy(WAYBAR_MODULE_CONFIG.get(m, {}))
        clock = cfg.setdefault("clock", copy.deepcopy(WAYBAR_MODULE_CONFIG["clock"]))
        clock["format"], clock["format-alt"] = v["clock_format"], v["clock_format_alt"]
        if _modern(ctx) and not any(v[f"margin_{k}"] for k in ("top", "right", "bottom", "left")):
            for k, n in self.margins(v, ctx).items():
                cfg[f"margin-{k}"] = n
        return cfg

    def values_from_config(self, cfg: Any) -> dict[str, Any]:
        if isinstance(cfg, list):
            cfg = cfg[0] if cfg else {}
        if not isinstance(cfg, dict):
            return {}
        found = values_from(cfg, BAR_MAP)
        if "height" not in cfg:
            found["height"] = 0
        for key in ("modules_left", "modules_center", "modules_right"):
            found.setdefault(key, [])
        clock = cfg.get("clock") or {}
        if "format" in clock:
            found["clock_format"] = clock["format"]
        if "format-alt" in clock:
            found["clock_format_alt"] = clock["format-alt"]
        return found

    def before_set(self, section, name, value, ctx):
        # the user's own files become the app's: copied in, scripts and all
        if name == "config_file":
            return owned.adopt(value, ctx.data_dir, "bar", "base.jsonc", with_references=True)
        if name == "style_template":
            return owned.adopt(value, ctx.data_dir, "bar", "style.css.template")
        return value

    def related_values(self, section, name, value, ctx) -> dict[str, Any]:
        """Choosing a base config adopts its layout, so nothing jumps around."""
        if name == "config_file" and value:
            return self.values_from_config(read_base(value))
        return {}

    def import_current(self, ipc, config, ctx):
        found = super().import_current(ipc, config, ctx).get(self.name, {})
        base = (ctx.values or {}).get(self.name, {}).get("config_file")
        if base:
            try:
                found.update(self.values_from_config(read_base(base)))
            except (OSError, ValueError):
                pass
        return {self.name: found} if found else {}

    def theme(self, v, ctx):
        """The bar can have its own theme, e.g. dark on a light desktop."""
        if v["theme"]:
            t = themes.load_all(ctx.data_dir).get(v["theme"])
            if t is not None:
                return t
        return ctx.theme

    def files(self, v, ctx):
        t = self.theme(v, ctx)
        if v["program"] == "swayctl-bar":
            style = _render_template(v["style_template"], t, ctx) if v["style_template"] else self.native_css(ctx, t)
            # the adaptive rules (.on-dark/.on-light, .tint-N) always go with
            # the sheet: the bar tags its panes from what's behind them and
            # those classes would have nothing to select otherwise
            # ... and the module sizes from bar.height (last: they size the
            # same selectors the look above styles)
            return {"config.json": json.dumps(self.native_config(v, ctx), indent=2, ensure_ascii=False) + "\n",
                    "style.css": style + self.adaptive_css(ctx)
                    + bar_size_css(v["height"], 0, _font(ctx)[1])
                    + bar_padding_css(v.get("padding", 10))
                    + self.shape_css(v, ctx, t)
                    + (SQUARE_CSS if _square(ctx) else "")}
        style = _render_template(v["style_template"], t, ctx) if v["style_template"] else self.css(ctx, t)
        return {"config.json": json.dumps(self.config(v, ctx), indent=2, ensure_ascii=False) + "\n",
                "style.css": style}

    def css(self, ctx: Context, t=None) -> str:
        t = t or ctx.theme
        k = t.tokens
        family, size = _font(ctx)
        px = round(size * 4 / 3)
        head = f"""/* generated by swayctl-center; edits are overwritten */
* {{ font-family: "{family}", "Symbols Nerd Font", sans-serif; font-weight: {_font_weight(ctx)}; font-size: {px}px; min-height: 0; border: none; border-radius: 0; }}
"""
        if _modern(ctx):
            r, rs = k["radius_lg"], k["radius_sm"]
            body = f"""window#waybar {{ background: alpha({k['surface']}, {k['panel_opacity']}); color: {k['text']};
  border: 1px solid alpha({k['outline']}, 0.9); border-radius: {r}px; }}
tooltip {{ background: {k['surface_overlay']}; color: {k['text']}; border: 1px solid {k['outline']}; border-radius: {rs + 2}px; }}
tooltip label {{ padding: 2px 4px; }}
.modules-left {{ margin-left: 4px; }}
.modules-right {{ margin-right: 4px; }}
#workspaces button {{ padding: 0 8px; margin: 4px 1px; color: {k['text_secondary']}; background: transparent; box-shadow: none; border-radius: {rs}px; transition: background 150ms ease, color 150ms ease; }}
#workspaces button:hover {{ color: {k['text']}; background: alpha({k['text']}, 0.08); }}
#workspaces button.focused {{ color: {k['accent_fg']}; background: {k['accent']}; }}
#workspaces button.urgent {{ color: #ffffff; background: {k['error']}; }}
#mode {{ color: {k['accent_fg']}; background: {k['accent']}; padding: 0 10px; margin: 4px; border-radius: {rs}px; }}
.modules-right > widget > *, .modules-center > widget > *, .modules-left > widget > label {{ padding: 0 8px; margin: 4px 1px; border-radius: {rs}px; }}
.modules-right > widget > *:hover, .modules-center > widget > *:hover {{ background: alpha({k['text']}, 0.08); }}
#battery.warning {{ color: {k['warning']}; }}
#battery.critical:not(.charging) {{ color: #ffffff; background: {k['error']}; }}
#idle_inhibitor.activated, #custom-notifications.notification {{ color: {k['accent']}; }}
"""
        else:
            body = f"""window#waybar {{ background: {t.bg}; color: {t.fg}; }}
tooltip {{ background: {t.bg}; color: {t.fg}; border: 1px solid {t.muted}; }}
#workspaces button {{ padding: 0 8px; color: {t.muted}; background: transparent; box-shadow: none; }}
#workspaces button:hover {{ color: {t.fg}; background: alpha({t.muted}, 0.25); }}
#workspaces button.focused {{ color: {k['accent_fg']}; background: {t.accent}; }}
#workspaces button.urgent {{ color: {t.bg}; background: {k['error']}; }}
#mode {{ color: {k['accent_fg']}; background: {t.accent}; padding: 0 8px; }}
.modules-right > widget > *, .modules-center > widget > *, .modules-left > widget > label {{ padding: 0 8px; }}
#battery.warning {{ color: {k['warning']}; }}
#battery.critical:not(.charging) {{ color: #ffffff; background: {k['error']}; }}
#idle_inhibitor.activated, #custom-notifications.notification {{ color: {t.accent}; }}
"""
        return head + body

    def reload(self, unit):
        if ": swayctl-bar " in units.state(unit).description:
            return  # it watches its own config.json and style.css
        # Not SIGUSR2: waybar 0.15 aborts (core dump) while reloading on it.
        units.restart(unit)


# --- notifications ---------------------------------------------------------

NOTIFICATIONS_MAP = {
    "position_x": "positionX", "position_y": "positionY", "layer": "layer",
    "width": "notification-window-width", "control_center_width": "control-center-width",
    "control_center_height": "control-center-height", "fit_to_screen": "fit-to-screen",
    "timeout": "timeout", "timeout_low": "timeout-low", "timeout_critical": "timeout-critical",
    "grouping": "notification-grouping", "relative_timestamps": "relative-timestamps",
    "image_visibility": "image-visibility", "hide_on_clear": "hide-on-clear",
    "hide_on_action": "hide-on-action", "keyboard_shortcuts": "keyboard-shortcuts",
}

NOTIFICATIONS_OUTPUT_KEYS = ("notification-window-preferred-output", "control-center-preferred-output")


class NotificationsModule(Component):
    name = "notifications"
    detect = [["-x", "swaync"], ["-x", "mako"], ["-x", "dunst"]]
    # The swaync package's own unit is D-Bus activated and restarts on
    # failure: left alone it respawns the moment ours isn't up yet.
    distro_unit = "swaync.service"

    def apply_extra(self, section, v, changed, ctx=None):
        if self.native(v):
            # switched from swaync: ours would keep the bus name from swayctl-bar
            old = self.unit_name("")
            if units.state(old).active:
                units.stop(old)
        if v["managed"]:
            units.mask_runtime(self.distro_unit)
        else:
            units.unmask_runtime(self.distro_unit)
        return super().apply_extra(section, v, changed, ctx)

    @staticmethod
    def native(v: dict[str, Any]) -> bool:
        """swayctl-bar is the notification server (not swaync)."""
        return bool(v.get("managed", True)) and v.get("program", "swayctl-bar") == "swayctl-bar"

    def programs(self, v, ctx):
        if self.native(v):
            return {}  # swayctl-bar (the bar's unit) serves them
        d = self.gen_dir(ctx)
        return {"": ["swaync", "-c", str(d / "config.json"), "-s", str(d / "style.css")]}

    def status(self, v, ctx):
        if not self.native(v):
            return super().status(v, ctx)
        bar = units.state(BarModule().unit_name(""))
        missing = [] if units.installed("swayctl-bar") else ["swayctl-bar"]
        return {"managed": v["managed"], "running": bar.active, "foreign_pids": self.foreign(v, ctx),
                "missing": missing}

    def files(self, v, ctx):
        if self.native(v):
            return {}
        return self._swaync_files(v, ctx)

    def session_start(self, section, v):
        if self.native(v):
            return []  # swayctl-bar reads dnd_on_start from its config
        if not (v["managed"] and v["dnd_on_start"]):
            return []
        # swaync may still be starting; retry briefly
        return ["exec sh -c 'for i in $(seq 20); do swaync-client --dnd-on >/dev/null 2>&1 && exit; sleep 0.5; done'"]

    def config(self, v, ctx) -> dict[str, Any]:
        base = read_base(v["config_file"])
        cfg = copy.deepcopy(base) if isinstance(base, dict) else {
            "widgets": ["title", "dnd", "notifications"],
            "widget-config": {
                "title": {"text": "Notifications", "clear-all-button": True, "button-text": "Clear"},
                "dnd": {"text": "Do not disturb"},
            },
        }
        apply_map(cfg, v, NOTIFICATIONS_MAP)
        # "" = no preferred output: sway puts pop-ups on the focused monitor
        for cfg_key in NOTIFICATIONS_OUTPUT_KEYS:
            if v["output"]:
                cfg[cfg_key] = v["output"]
            else:
                cfg.pop(cfg_key, None)
        return cfg

    def values_from_config(self, cfg: Any) -> dict[str, Any]:
        if not isinstance(cfg, dict):
            return {}
        out = values_from(cfg, NOTIFICATIONS_MAP)
        if isinstance(cfg.get(NOTIFICATIONS_OUTPUT_KEYS[0]), str):
            out["output"] = cfg[NOTIFICATIONS_OUTPUT_KEYS[0]]
        return out

    def before_set(self, section, name, value, ctx):
        if name == "config_file":
            return owned.adopt(value, ctx.data_dir, "notifications", "base.json", with_references=True)
        if name == "style_template":
            return owned.adopt(value, ctx.data_dir, "notifications", "style.css.template")
        return value

    def related_values(self, section, name, value, ctx) -> dict[str, Any]:
        if name == "config_file" and value:
            return self.values_from_config(read_base(value))
        return {}

    def import_current(self, ipc, config, ctx):
        found = super().import_current(ipc, config, ctx).get(self.name, {})
        base = (ctx.values or {}).get(self.name, {}).get("config_file")
        if base:
            try:
                found.update(self.values_from_config(read_base(base)))
            except (OSError, ValueError):
                pass
        return {self.name: found} if found else {}

    def _swaync_files(self, v, ctx):
        style = _render_template(v["style_template"], ctx.theme, ctx) if v["style_template"] else self.css(ctx)
        return {"config.json": json.dumps(self.config(v, ctx), indent=2, ensure_ascii=False) + "\n",
                "style.css": style}

    def css(self, ctx: Context) -> str:
        k = ctx.theme.tokens
        family, _size = _font(ctx)
        default_css = Path("/etc/xdg/swaync/style.css")
        imp = f'@import url("file://{default_css}");\n' if default_css.exists() else ""
        return f"""/* generated by swayctl-center; edits are overwritten */
{imp}:root {{
  --cc-bg: alpha(white, 0.72);
  --noti-bg: 255, 255, 255;
  --noti-bg-alpha: 0.65;
  --noti-bg-darker: alpha(white, 0.55);
  --noti-bg-hover: alpha(black, 0.06);
  --noti-bg-focus: alpha(black, 0.08);
  --noti-close-bg: alpha(black, 0.08);
  --noti-close-bg-hover: alpha(black, 0.14);
  --noti-border-color: alpha(white, 0.42);
  --text-color: {MILK_TEXT};
  --text-color-disabled: alpha({MILK_TEXT}, 0.45);
  --bg-selected: {k['accent']};
  --border-radius: {k['radius_lg'] if _modern(ctx) else k['radius_md']}px;
}}
.notification.critical {{ border: 1px solid {k['error']}; }}
* {{ font-family: "{family}", sans-serif; font-weight: {_font_weight(ctx)}; }}
""" + (self.glass_css(k, milk_opacity(ctx)) if _glass(ctx) else "")

    @staticmethod
    def glass_css(k, opacity: float = 0.08) -> str:
        """swaync fallback: same OSD milky look as the native cards."""
        a = max(opacity, 0.04)
        top = min(a * 0.84, 0.82)
        bot = min(a * 0.52, 0.62)
        return f"""
/* liquid glass: OSD milk */
:root {{
  --noti-bg: 255, 255, 255;
  --noti-bg-alpha: {top:.3f};
  --noti-bg-darker: alpha(white, {bot:.3f});
  --cc-bg: alpha(white, {top:.3f});
  --noti-bg-hover: alpha(black, 0.06);
  --noti-bg-focus: alpha(black, 0.08);
  --noti-close-bg: alpha(black, 0.08);
  --noti-close-bg-hover: alpha(black, 0.14);
  --noti-border-color: alpha(white, 0.48);
  --text-color: {MILK_TEXT};
  --bg-selected: {k['accent']};
  --border: 1px solid alpha(white, 0.48);
  --border-radius: 20px;
  --notification-shadow: none;
}}
.notification, .control-center {{
  color: {MILK_TEXT};
  box-shadow: {MILK_INSET};
}}
.notification label, .control-center label {{ color: {MILK_TEXT}; text-shadow: none; }}
.notification-action, .widget-dnd > switch, .widget-title > button {{
  background: alpha(black, 0.08);
  box-shadow: {MILK_INSET};
  border: {MILK_RIM}; border-radius: 999px; color: {MILK_TEXT};
}}
.widget-dnd > switch:checked {{ background: {k['accent']}; }}
/* cards inside the notification center: milky pills on the glass panel */
.control-center .notification-row,
.control-center .notification-row .notification-background,
.control-center .notification-group,
.control-center .notification-group .notification-group-headers {{ background: none; box-shadow: none; }}
.control-center .notification-row .notification-background .notification,
.control-center .control-center-list .notification {{
  background: alpha(white, {bot:.3f});
  box-shadow: {MILK_INSET}, inset 0 0 0 1px alpha(white, 0.48);
}}
"""

    def reload(self, unit):
        # (only swaync has a unit of ours) swaync can reload both without restarting (and losing notifications)
        import subprocess
        subprocess.run(["swaync-client", "--reload-config"], capture_output=True)
        subprocess.run(["swaync-client", "--reload-css"], capture_output=True)


# --- idle and lock ---------------------------------------------------------

def lock_command(ctx: Context) -> list[str]:
    a = (ctx.values or {}).get("auth") or {}
    if a.get("lock_screen") == "swayctl-lock":
        # asks the password and the fingerprint at once; style comes from swayctl-bar's
        # --daemonize: return once locked, like swaylock -f (swayidle waits on it before sleep)
        argv = ["swayctl-lock", "--daemonize", "--style", str(ctx.data_dir / "generated" / "bar" / "style.css")]
        if a.get("fingerprint_lock"):
            argv.append("--fingerprint")
        if a.get("face_lock"):
            argv.append("--face")
        # blurred behind its panes of glass
        image = ((ctx.values or {}).get("background") or {}).get("image")
        if image:
            argv += ["--wallpaper", str(ctx.data_dir / image)]
        return argv
    t = ctx.theme
    idle = (ctx.values or {}).get("idle") or {}
    bare = {k: getattr(t, k).lstrip("#") for k in ("bg", "fg", "accent", "muted")}
    tok = {k: v.lstrip("#") for k, v in t.tokens.items() if isinstance(v, str)}
    argv = ["swaylock", "-f", "-c", bare["bg"], "--inside-color", bare["bg"],
            "--ring-color", bare["fg"], "--line-color", bare["fg"], "--text-color", bare["fg"],
            "--key-hl-color", bare["accent"], "--separator-color", bare["fg"],
            "--ring-wrong-color", tok["error"], "--text-wrong-color", tok["error"],
            "--ring-ver-color", bare["accent"], "--text-ver-color", bare["fg"],
            "--inside-ver-color", bare["bg"], "--inside-wrong-color", bare["bg"],
            "--bs-hl-color", tok["warning"]]
    image = ((ctx.values or {}).get("background") or {}).get("image")
    if idle.get("lock_background") == "wallpaper" and image:
        argv += ["-i", str(ctx.data_dir / image), "-s", "fill"]
    if idle.get("show_failed_attempts"):
        argv.append("-F")
    if idle.get("ignore_empty_password"):
        argv.append("-e")
    return argv


class IdleModule(Component):
    name = "idle"
    depends_on = ("theme", "background")
    detect = [["-x", "swayidle"]]

    def programs(self, v, ctx):
        lock = shlex.join(lock_command(ctx))
        argv = ["swayidle", "-w"]
        if v["lock_after"]:
            argv += ["timeout", str(v["lock_after"]), lock]
        if v["screen_off_after"]:
            argv += ["timeout", str(v["screen_off_after"]), 'swaymsg "output * power off"',
                     "resume", 'swaymsg "output * power on"']
        if v["suspend_after"]:
            argv += ["timeout", str(v["suspend_after"]), "systemctl suspend"]
        if v["lock_before_sleep"]:
            argv += ["before-sleep", lock]
        return {"": argv}

    _TIMEOUT_RE = re.compile(r"timeout\s+(\d+)\s+('[^']*'|\"(?:[^\"\\\\]|\\\\.)*\"|\S+)")

    def import_current(self, ipc, config, ctx):
        found: dict[str, Any] = {}
        running = self.is_running_elsewhere()
        if running:
            found["managed"] = False
        # timeouts from the user's `exec swayidle ...` line, whether or not it runs now
        for line in config.top_level():
            if not re.match(r"^exec(_always)?\s+(\S*/)?swayidle\b", line):
                continue
            for secs, cmd in self._TIMEOUT_RE.findall(line):
                if "lock" in cmd and "lock_after" not in found:
                    found["lock_after"] = int(secs)
                elif ("power off" in cmd or "dpms off" in cmd) and "screen_off_after" not in found:
                    found["screen_off_after"] = int(secs)
            found["lock_before_sleep"] = "before-sleep" in line
        return {self.name: found} if found else {}


# --- clipboard -------------------------------------------------------------

class ClipboardModule(Component):
    name = "clipboard"
    depends_on = ()
    detect = [["-f", r"^(\S*/)?wl-paste .*--watch cliphist"]]

    def programs(self, v, ctx):
        store = ["cliphist", "-max-items", str(v["max_items"]), "store"]
        progs = {"text": ["wl-paste", "--type", "text", "--watch", *store]}
        if v["images"]:
            progs["image"] = ["wl-paste", "--type", "image", "--watch", *store]
        if v["persist"]:
            progs["persist"] = ["wl-clip-persist", "--clipboard", "regular"]
        return progs

    def detect_for(self, suffix):
        return [["-x", "wl-clip-persist"]] if suffix == "persist" else self.detect

    def all_units(self, v, ctx):
        # all of them, so turning an option off also stops its program
        return [self.unit_name(s) for s in ("text", "image", "persist")]

    def apply_extra(self, section, v, changed, ctx=None):
        for option, suffix in (("images", "image"), ("persist", "persist")):
            if not v[option] and units.state(self.unit_name(suffix)).active:
                units.stop(self.unit_name(suffix))
        return super().apply_extra(section, v, changed, ctx)


    def import_current(self, ipc, config, ctx):
        found = super().import_current(ipc, config, ctx).get(self.name, {})
        if self.is_running_elsewhere("persist"):
            found["persist"] = False
        conf = Path.home() / ".config/cliphist/config"
        try:
            m = re.search(r"^max-items\s+(\d+)", conf.read_text(), re.M)
            if m:
                found["max_items"] = int(m.group(1))
        except OSError:
            pass
        return {self.name: found} if found else {}


# --- input method ----------------------------------------------------------

class InputMethodModule(Component):
    name = "input_method"
    depends_on = ()
    detect = [["-x", "fcitx5"]]

    def programs(self, v, ctx):
        return {"": ["fcitx5"]}


# --- polkit agent ----------------------------------------------------------

POLKIT_GNOME = "/usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1"


class PolkitAgentModule(Component):
    """The password prompt behind pkexec (turning on system services, setting
    up smooth scrolling...). Desktops start one; plain sway doesn't."""
    name = "polkit_agent"
    depends_on = ()
    detect = [["-f", r"polkit.*agent|policykit-agent|lxpolkit|xfce-polkit|soteria"]]

    def programs(self, v, ctx):
        return {"": [POLKIT_GNOME]}

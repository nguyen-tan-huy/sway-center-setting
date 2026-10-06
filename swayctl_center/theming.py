"""Theme placeholders for user templates: any config file can follow the
active theme and font by writing @BG@, @FG@... where colors go, the same
convention the "paper" theme scripts used.

  @BG@ @FG@ @ACCENT@ @MUTED@      colors as bare hex (282828); append alpha
  @BORDER@ (= @ACCENT@)           yourself where a program wants it (@BG@f2)
  @MATCH@ (= @MUTED@)
  @BG_HEX@ @FG_HEX@ ...           the same with a leading #
  @FONT@ @FONT_SIZE@ @FONT_SIZE_PX@ @MONO_FONT@ @MONO_FONT_SIZE@
  @FONT_WEIGHT@ @MONO_FONT_WEIGHT@ CSS weights (400 regular, 700 bold...)
  @VARIANT@                       light | dark
  @THEME@                         the theme's name (light or dark)

Design tokens (themes.Theme.tokens), colors as bare hex plus a _HEX form:
  @SURFACE@ @SURFACE_RAISED@ @SURFACE_OVERLAY@ @TEXT@ @TEXT_SECONDARY@
  @TEXT_DISABLED@ @ACCENT_FG@ @OUTLINE@ @OUTLINE_STRONG@ @FOCUS_RING@
  @SUCCESS@ @WARNING@ @ERROR@
and sizes as plain numbers: @RADIUS_SM@ @RADIUS_MD@ @RADIUS_LG@ @GAP@
  @BORDER_WIDTH@ @BLUR@ @PANEL_OPACITY@ (0..1) @PANEL_ALPHA@ (2-digit hex, for @SURFACE@@PANEL_ALPHA@)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .modules.font import css_weight
from .themes import COLOR_TOKENS, Theme


def placeholders(theme: Theme, font: dict[str, Any] | None) -> dict[str, str]:
    font = font or {"family": "sans-serif", "size": 10, "monospace_family": "monospace", "monospace_size": 10}
    colors = {"BG": theme.bg, "FG": theme.fg, "ACCENT": theme.accent, "MUTED": theme.muted,
              "BORDER": theme.accent, "MATCH": theme.muted}
    tokens = theme.tokens
    colors.update({k.upper(): v for k, v in tokens.items() if k in COLOR_TOKENS and k.upper() not in colors})
    out = {f"@{k}@": v.lstrip("#") for k, v in colors.items()}
    out.update({f"@{k}_HEX@": v for k, v in colors.items()})
    out.update({f"@{k.upper()}@": f"{v:g}" for k, v in tokens.items() if k not in COLOR_TOKENS})
    out["@PANEL_ALPHA@"] = f"{round(tokens['panel_opacity'] * 255):02x}"
    out.update({
        "@FONT@": font["family"], "@FONT_SIZE@": str(font["size"]),
        "@FONT_SIZE_PX@": str(round(font["size"] * 4 / 3)),
        "@MONO_FONT@": font.get("monospace_family", "monospace"),
        "@MONO_FONT_SIZE@": str(font.get("monospace_size", 10)),
        "@FONT_WEIGHT@": str(css_weight(font.get("weight", "regular"))),
        "@MONO_FONT_WEIGHT@": str(css_weight(font.get("monospace_weight", "regular"))),
        "@VARIANT@": "dark" if theme.dark else "light",
        "@THEME@": theme.name,
    })
    return out


def adwaita_css(theme: Theme | dict) -> str:
    """libadwaita (1.6+) named colors and CSS variables for the theme (or its
    tokens), for gtk-4.0/gtk.css or a GtkCssProvider in our own apps."""
    t = theme if isinstance(theme, dict) else theme.tokens
    names = {
        "accent_bg_color": t["accent"], "accent_fg_color": t["accent_fg"], "accent_color": t["accent"],
        "window_bg_color": t["surface"], "window_fg_color": t["text"],
        "view_bg_color": t["surface"], "view_fg_color": t["text"],
        "headerbar_bg_color": t["surface_raised"], "headerbar_fg_color": t["text"],
        "sidebar_bg_color": t["surface_raised"], "sidebar_fg_color": t["text"],
        "card_bg_color": t["surface_raised"], "card_fg_color": t["text"],
        "popover_bg_color": t["surface_overlay"], "popover_fg_color": t["text"],
        "dialog_bg_color": t["surface_raised"], "dialog_fg_color": t["text"],
        "success_color": t["success"], "warning_color": t["warning"],
        "error_color": t["error"], "destructive_color": t["error"],
    }
    lines = [f"@define-color {k} {v};" for k, v in names.items()]
    lines.append(":root {")
    lines += [f"  --{k.replace('_', '-')}: {v};" for k, v in names.items()]
    lines.append(f"  --window-radius: {t['radius_lg']:g}px;")
    lines.append("}")
    return "\n".join(lines) + "\n"


_TOKEN = re.compile(r"@[A-Z_]+@")


def render(text: str, values: dict[str, str]) -> str:
    return _TOKEN.sub(lambda m: values.get(m.group(0), m.group(0)), text)


def expand(path: str) -> Path:
    return Path(path).expanduser()

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
  @THEME@                         the theme's name (gruvbox-dark, nord...)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .modules.font import css_weight
from .themes import Theme


def placeholders(theme: Theme, font: dict[str, Any] | None) -> dict[str, str]:
    font = font or {"family": "sans-serif", "size": 10, "monospace_family": "monospace", "monospace_size": 10}
    colors = {"BG": theme.bg, "FG": theme.fg, "ACCENT": theme.accent, "MUTED": theme.muted,
              "BORDER": theme.accent, "MATCH": theme.muted}
    out = {f"@{k}@": v.lstrip("#") for k, v in colors.items()}
    out.update({f"@{k}_HEX@": v for k, v in colors.items()})
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


_TOKEN = re.compile(r"@[A-Z_]+@")


def render(text: str, values: dict[str, str]) -> str:
    return _TOKEN.sub(lambda m: values.get(m.group(0), m.group(0)), text)


def expand(path: str) -> Path:
    return Path(path).expanduser()

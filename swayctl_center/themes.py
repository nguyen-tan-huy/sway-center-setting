"""Color themes. A theme is four colors - the same roles the "paper" themes
used: background, foreground, accent (focused borders) and muted (inactive).
Built-in themes live here; users can add their own as JSON files in
<app folder>/themes/<name>.json with the same four keys, or with just
{"accent": "#rrggbb", "variant": "dark"} to have the rest derived.

Everything else a modern UI needs (raised surfaces, secondary text, borders,
status colors, radii...) comes from Theme.tokens, derived from the four
colors in OKLab so mixes stay even across hues. A theme JSON may override any
token under "tokens".
"""
from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_HEX = re.compile(r"#[0-9a-fA-F]{6}")


# ---- color math (sRGB <-> OKLab, https://bottosson.github.io/posts/oklab/) ----

def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _from_linear(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _rgb(hex_: str) -> tuple[float, float, float]:
    return tuple(int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(min(1.0, max(0.0, c)) * 255):02x}" for c in rgb)


def to_oklab(hex_: str) -> tuple[float, float, float]:
    r, g, b = (_to_linear(c) for c in _rgb(hex_))
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def _oklab_rgb(L: float, a: float, b: float) -> tuple[float, float, float]:
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def from_oklab(L: float, a: float, b: float) -> str:
    return _hex(tuple(_from_linear(max(0.0, c)) for c in _oklab_rgb(L, a, b)))


def oklch(L: float, C: float, h: float) -> str:
    """Color from OKLCh (h in degrees); chroma is reduced until it fits sRGB."""
    while True:
        a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
        rgb = _oklab_rgb(L, a, b)
        if all(-1e-4 <= c <= 1 + 1e-4 for c in rgb) or C <= 0:
            return from_oklab(L, a, b)
        C = max(0.0, C - 0.005)


def hue(hex_: str) -> float:
    _, a, b = to_oklab(hex_)
    return math.degrees(math.atan2(b, a)) % 360


def mix(a: str, b: str, t: float) -> str:
    """a blended toward b by t (0..1), in OKLab."""
    pa, pb = to_oklab(a), to_oklab(b)
    return from_oklab(*(x + (y - x) * t for x, y in zip(pa, pb)))


def mix_readable(fg: str, bg: str, t: float, min_contrast: float) -> str:
    """fg faded toward bg by up to t, but no further than keeps min_contrast
    against bg (or fg itself when even that is too faint)."""
    while t > 0:
        c = mix(fg, bg, t)
        if contrast(c, bg) >= min_contrast:
            return c
        t = round(t - 0.02, 4)
    return fg


def luminance(hex_: str) -> float:
    r, g, b = (_to_linear(c) for c in _rgb(hex_))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# ---- tokens -------------------------------------------------------------------

# Non-color tokens: sizes in px, opacity 0..1. Same for every theme unless the
# theme JSON overrides them.
SHAPE = {"radius_sm": 6, "radius_md": 10, "radius_lg": 14, "gap": 8,
         "border_width": 2, "blur": 12, "panel_opacity": 0.88}

COLOR_TOKENS = ("surface", "surface_raised", "surface_overlay", "text", "text_secondary",
                "text_disabled", "accent", "accent_fg", "outline", "outline_strong",
                "focus_ring", "success", "warning", "error")


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    fg: str
    accent: str
    muted: str
    overrides: dict = field(default_factory=dict, compare=False)

    @property
    def dark(self) -> bool:
        r, g, b = (int(self.bg[i:i + 2], 16) for i in (1, 3, 5))
        return (r * 299 + g * 587 + b * 114) / 1000 < 128

    @property
    def tokens(self) -> dict:
        bg, fg, dark = self.bg, self.fg, self.dark
        # status colors keep a fixed hue but sit at a lightness that reads on bg
        L = 0.74 if dark else 0.56
        t = {
            "surface": bg,
            "surface_raised": mix(bg, fg, 0.06 if dark else 0.035),
            "surface_overlay": mix(bg, fg, 0.11 if dark else 0.07),
            "text": fg,
            "text_secondary": mix_readable(fg, bg, 0.32, 3.5),
            "text_disabled": mix(fg, bg, 0.6),
            "accent": self.accent,
            # white labels on saturated accents (GNOME blue: 3.9) read better than
            # the black that pure contrast math would pick
            "accent_fg": "#ffffff" if contrast(self.accent, "#ffffff") >= 3.5 else "#000000",
            "outline": mix(bg, fg, 0.14),
            "outline_strong": self.muted,
            "focus_ring": self.accent,
            "success": oklch(L, 0.14, 150),
            "warning": oklch(L + 0.06, 0.14, 75),
            "error": oklch(L - 0.02, 0.16, 25),
        } | SHAPE
        t.update(self.overrides)
        return t

    def to_json(self) -> dict:
        return {"name": self.name, "bg": self.bg, "fg": self.fg, "accent": self.accent,
                "muted": self.muted, "dark": self.dark, "tokens": self.tokens}


def from_accent(name: str, accent: str, dark: bool, overrides: dict | None = None) -> Theme:
    """A neutral theme tinted toward accent's hue: only the accent is chosen."""
    h = hue(accent)
    if dark:
        bg, fg, muted = oklch(0.2, 0.012, h), oklch(0.94, 0.008, h), oklch(0.52, 0.02, h)
    else:
        bg, fg, muted = oklch(0.975, 0.006, h), oklch(0.24, 0.012, h), oklch(0.66, 0.018, h)
    return Theme(name, bg, fg, accent, muted, dict(overrides or {}))


# Just two looks, both made for the liquid glass shell: light glass with black
# text, dark glass with light text.
BUILTIN = {t.name: t for t in (
    Theme("light", "#f5f5f7", "#1d1d1f", "#0a84ff", "#a1a1a6"),
    Theme("dark", "#1c1c1e", "#f5f5f7", "#0a84ff", "#636366"),
)}

# themes of earlier versions: settings that still name one get the matching look
LEGACY = {"gruvbox-light": "light", "modern-light": "light",
          "gruvbox-dark": "dark", "modern-dark": "dark", "nord": "dark", "dracula": "dark",
          "solarized-dark": "dark"}


def user_theme_dir(data_dir: Path) -> Path:
    return data_dir / "themes"


def _overrides(raw: dict) -> dict:
    tokens = raw.get("tokens", {})
    if not isinstance(tokens, dict):
        raise ValueError("tokens must be an object")
    out = {}
    for k, v in tokens.items():
        if k in COLOR_TOKENS:
            if not (isinstance(v, str) and _HEX.fullmatch(v)):
                raise ValueError(f"token {k} must be #rrggbb")
        elif k in SHAPE:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                raise ValueError(f"token {k} must be a number >= 0")
        else:
            raise ValueError(f"unknown token {k}")
        out[k] = v
    return out


def load_all(data_dir: Path | None) -> dict[str, Theme]:
    themes = dict(BUILTIN)
    if data_dir is None:
        return themes
    for path in sorted(user_theme_dir(data_dir).glob("*.json")):
        try:
            raw = json.loads(path.read_text())
            overrides = _overrides(raw)
            if "bg" not in raw and "accent" in raw:
                if not (isinstance(raw["accent"], str) and _HEX.fullmatch(raw["accent"])):
                    raise ValueError("accent must be #rrggbb")
                if raw.get("variant", "dark") not in ("dark", "light"):
                    raise ValueError("variant must be dark or light")
                themes[path.stem] = from_accent(path.stem, raw["accent"],
                                                raw.get("variant", "dark") == "dark", overrides)
                continue
            colors = {k: raw[k] for k in ("bg", "fg", "accent", "muted")}
            if not all(isinstance(v, str) and _HEX.fullmatch(v) for v in colors.values()):
                raise ValueError("colors must be #rrggbb")
            themes[path.stem] = Theme(path.stem, **colors, overrides=overrides)
        except (OSError, KeyError, ValueError, TypeError) as e:
            log.warning("ignoring theme %s: %s", path, e)
    return themes

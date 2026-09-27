"""Fonts: sway window titles plus the GTK interface and monospace fonts
(org.gnome.desktop.interface, which GTK apps and the portal read)."""
from __future__ import annotations

import re
from typing import Any

from .. import swayconfig, swayipc
from . import Context

_FONT_RE = re.compile(r"^font\s+(?:pango:)?(.+?)\s+(\d+(?:\.\d+)?)$")
GSETTINGS_SCHEMA = "org.gnome.desktop.interface"


# weight -> (CSS number, the word Pango font strings use; "" = regular)
WEIGHTS = {"thin": (100, "Thin"), "light": (300, "Light"), "regular": (400, ""), "medium": (500, "Medium"),
           "semibold": (600, "Semi-Bold"), "bold": (700, "Bold"), "heavy": (900, "Heavy")}
# what font names end with, e.g. "Inter SemiBold" or "JetBrains Mono ExtraBold"
_WEIGHT_WORDS = {"thin": "thin", "hairline": "thin", "extralight": "light", "ultralight": "light",
                 "light": "light", "regular": "regular", "normal": "regular", "book": "regular",
                 "medium": "medium", "semibold": "semibold", "demibold": "semibold", "bold": "bold",
                 "extrabold": "heavy", "ultrabold": "heavy", "black": "heavy", "heavy": "heavy"}


def css_weight(weight: str) -> int:
    return WEIGHTS.get(weight, WEIGHTS["regular"])[0]


def pango_font(family: str, weight: str, size: int) -> str:
    """"Inter", "bold", 11 -> "Inter Bold 11" (sway's `font pango:`, gsettings)."""
    word = WEIGHTS.get(weight, WEIGHTS["regular"])[1]
    return " ".join(p for p in (family, word, str(size)) if p)


def split_weight(family: str) -> tuple[str, str]:
    """"Inter SemiBold" -> ("Inter", "semibold"); "Inter" -> ("Inter", "regular")."""
    parts = family.rsplit(None, 1)
    if len(parts) == 2:
        word = _WEIGHT_WORDS.get(parts[1].lower().replace("-", ""))
        if word:
            return parts[0], word
    return family, "regular"


def split_font(text: str) -> tuple[str, int] | None:
    """"Inter SemiBold 12" -> ("Inter SemiBold", 12)."""
    m = re.match(r"^(.+?)\s+(\d+(?:\.\d+)?)$", text.strip())
    if not m:
        return None
    return m.group(1), round(float(m.group(2)))


def _gsettings():
    """Gio.Settings for the interface schema, or None if it isn't installed."""
    from gi.repository import Gio
    source = Gio.SettingsSchemaSource.get_default()
    if source is None or source.lookup(GSETTINGS_SCHEMA, True) is None:
        return None
    return Gio.Settings.new(GSETTINGS_SCHEMA)


class FontModule:
    sections = ("font",)
    tolerated_errors = ()

    def commands(self, section: str, v: dict[str, Any], changed: set[str] | None,
                 ctx: Context | None = None) -> list[str]:
        return [f"font pango:{pango_font(v['family'], v.get('weight', 'regular'), v['size'])}"]

    def gsettings_values(self, v: dict[str, Any]) -> dict[str, str]:
        return {
            "font-name": pango_font(v["family"], v.get("weight", "regular"), v["size"]),
            "monospace-font-name": pango_font(v["monospace_family"], v.get("monospace_weight", "regular"), v["monospace_size"]),
        }

    def apply_extra(self, section: str, v: dict[str, Any], changed: set[str] | None,
                    ctx: Context | None = None) -> list[str]:
        settings = _gsettings()
        if settings is None:
            return [f"{GSETTINGS_SCHEMA} is not installed; GTK fonts not set"]
        for key, value in self.gsettings_values(v).items():
            if settings.get_string(key) != value:
                settings.set_string(key, value)
        from gi.repository import Gio
        Gio.Settings.sync()
        return []

    def import_current(self, ipc: swayipc.Connection, config: swayconfig.Config,
                       ctx: Context) -> dict[str, dict[str, Any]]:
        found: dict[str, Any] = {}
        for line in config.top_level():
            m = _FONT_RE.match(line)
            if m:
                found["family"], found["size"] = m.group(1), round(float(m.group(2)))
                found["family"], found["weight"] = split_weight(found["family"])
        settings = _gsettings()
        if settings is not None:
            mono = split_font(settings.get_string("monospace-font-name"))
            if mono:
                found["monospace_family"], found["monospace_size"] = mono
                found["monospace_family"], found["monospace_weight"] = split_weight(mono[0])
            if "family" not in found:
                ui = split_font(settings.get_string("font-name"))
                if ui:
                    found["family"], found["size"] = ui
                    found["family"], found["weight"] = split_weight(ui[0])
        return {"font": found}

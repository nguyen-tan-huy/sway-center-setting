"""Looks that set several settings at once (action preset.<name>). Each only
touches the keys listed; everything else the user set stays. "classic" puts
those keys back to their defaults."""
from __future__ import annotations

from typing import Any

from . import schema

MODERN: dict[str, dict[str, Any]] = {
    "appearance": {"style": "modern", "light_theme": "light", "dark_theme": "dark"},
    "layout": {"gaps_inner": 8, "gaps_outer": 4, "border": 2, "floating_border": 2,
               "border_style": "pixel", "smart_gaps": "off"},
    "bar": {"height": 34, "theme": ""},
    # only take effect under SwayFX (swayctl-fx); harmless on plain sway
    "effects": {"corner_radius": 10, "shadows": True, "blur": True, "dim_inactive": 0.06,
                "panels": True, "glass": True},
}


def _defaults_for(keys: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    d = schema.defaults()
    return {section: {name: d[section][name] for name in items} for section, items in keys.items()}


PRESETS = {"modern": MODERN, "classic": _defaults_for(MODERN)}


def values(name: str) -> dict[str, dict[str, Any]]:
    return PRESETS[name]


def current(effective: dict[str, dict[str, Any]]) -> str | None:
    """The preset the settings match exactly, if any."""
    for name, preset in PRESETS.items():
        if all(effective[s][k] == v for s, items in preset.items() for k, v in items.items()):
            return name
    return None

"""Color theme and light/dark switching.

The active theme is sway's window colors plus the desktop-wide dark/light
preference (org.gnome.desktop.interface color-scheme), which the XDG portal
relays to GTK4, Qt 6 and browsers. Other modules that use theme colors (e.g.
the wallpaper's fallback color) declare depends_on = ("theme",).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .. import schedule, swayconfig, swayipc, themes
from . import Context

GSETTINGS_SCHEMA = "org.gnome.desktop.interface"
# Only swapped when the user is on one of these, so a custom GTK theme is left alone.
ADWAITA = {"Adwaita": "Adwaita-dark", "Adwaita-dark": "Adwaita"}


@dataclass(frozen=True)
class Resolved:
    theme: themes.Theme
    variant: str               # "light" | "dark"
    source: str                # "fixed" | "schedule" | "override"
    next_change: datetime | None
    missing: str | None = None  # configured theme name that doesn't exist


def resolve(values: dict[str, dict[str, Any]], available: dict[str, themes.Theme],
            now: datetime, override: dict | None = None) -> Resolved:
    """Which theme should be active at `now`. `override` is a toggle made while
    on the automatic schedule: {"variant": ..., "until": iso-datetime}."""
    a = values["appearance"]
    next_change = None
    if a["mode"] in ("light", "dark"):
        variant, source = a["mode"], "fixed"
    else:
        loc = schedule.resolve_location(values["location"])
        variant, next_change = schedule.variant_at(now, a["schedule"], loc, a["light_at"], a["dark_at"])
        source = "schedule"
        if override and datetime.fromisoformat(override["until"]) > now:
            variant, source = override["variant"], "override"
    name = a["light_theme"] if variant == "light" else a["dark_theme"]
    missing = None
    if name not in available:
        missing = name
        name = "gruvbox-light" if variant == "light" else "gruvbox-dark"
    return Resolved(available[name], variant, source, next_change, missing)


def client_colors(t: themes.Theme) -> list[str]:
    # border, background, text, indicator, child_border
    return [
        f"client.focused {t.accent} {t.bg} {t.fg} {t.accent} {t.accent}",
        f"client.focused_inactive {t.muted} {t.bg} {t.muted} {t.muted} {t.muted}",
        f"client.unfocused {t.muted} {t.bg} {t.muted} {t.muted} {t.muted}",
        f"client.urgent {t.accent} {t.bg} {t.accent} {t.accent} {t.accent}",
    ]


def _gsettings():
    from gi.repository import Gio
    source = Gio.SettingsSchemaSource.get_default()
    if source is None or source.lookup(GSETTINGS_SCHEMA, True) is None:
        return None
    return Gio.Settings.new(GSETTINGS_SCHEMA)


class AppearanceModule:
    sections = ("appearance",)
    tolerated_errors = ()
    depends_on = ("location", "theme")

    def commands(self, section: str, v: dict[str, Any], changed: set[str] | None,
                 ctx: Context | None = None) -> list[str]:
        if ctx is None or ctx.theme is None:
            return []
        return client_colors(ctx.theme)

    def apply_extra(self, section: str, v: dict[str, Any], changed: set[str] | None,
                    ctx: Context | None = None) -> list[str]:
        if ctx is None or ctx.theme is None:
            return []
        settings = _gsettings()
        if settings is None:
            return [f"{GSETTINGS_SCHEMA} is not installed; apps won't follow dark/light"]
        scheme = "prefer-dark" if ctx.theme.dark else "prefer-light"
        if settings.get_string("color-scheme") != scheme:
            settings.set_string("color-scheme", scheme)
        gtk_theme = settings.get_string("gtk-theme")
        want = "Adwaita-dark" if ctx.theme.dark else "Adwaita"
        if gtk_theme in ADWAITA and gtk_theme != want:
            settings.set_string("gtk-theme", want)
        from gi.repository import Gio
        Gio.Settings.sync()
        return []

    def import_current(self, ipc: swayipc.Connection, config: swayconfig.Config,
                       ctx: Context) -> dict[str, dict[str, Any]]:
        return {}  # defaults: automatic gruvbox light/dark


class LocationModule:
    """Only data; appearance and night light re-apply when it changes."""
    sections = ("location",)
    tolerated_errors = ()

    def commands(self, section, v, changed, ctx=None) -> list[str]:
        return []

    def import_current(self, ipc, config, ctx) -> dict[str, dict[str, Any]]:
        return {}

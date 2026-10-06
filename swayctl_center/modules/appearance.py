"""Color theme and light/dark switching.

The active theme is sway's window colors plus the desktop-wide dark/light
preference (org.gnome.desktop.interface color-scheme), which the XDG portal
relays to GTK4, Qt 6 and browsers. Other modules that use theme colors (e.g.
the wallpaper's fallback color) declare depends_on = ("theme",).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import appthemes, schedule, swayconfig, swayipc, theming, themes
from . import Context

GSETTINGS_SCHEMA = "org.gnome.desktop.interface"
# Only swapped when the user is on one of these, so a custom GTK theme is left alone.


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
        if name not in themes.LEGACY:
            missing = name
        name = variant  # the built-in "light" / "dark"
    return Resolved(available[name], variant, source, next_change, missing)


def client_colors(t: themes.Theme) -> list[str]:
    # border, background, text, indicator, child_border
    k = t.tokens
    return [
        f"client.focused {t.accent} {t.bg} {t.fg} {t.accent} {t.accent}",
        f"client.focused_inactive {t.muted} {t.bg} {t.muted} {t.muted} {t.muted}",
        f"client.unfocused {t.muted} {t.bg} {t.muted} {t.muted} {t.muted}",
        f"client.urgent {k['error']} {t.bg} {k['error']} {k['error']} {k['error']}",
    ]


# GTK 4 / libadwaita colors: our CSS lives in the app folder and the user's
# gtk.css only gets an @import between these markers, so the rest of their
# file is never touched and turning the option off removes just our lines.
GTK_BEGIN = "/* >>> swayctl-center theme (managed; remove with the GTK option off) */"
GTK_END = "/* <<< swayctl-center theme */"
_GTK_BLOCK = re.compile(re.escape(GTK_BEGIN) + r".*?" + re.escape(GTK_END) + r"\n?", re.S)


def gtk_css_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "gtk-4.0" / "gtk.css"


def sync_gtk_css(enabled: bool, theme: themes.Theme, data_dir: Path, target: Path | None = None) -> None:
    target = target or gtk_css_path()
    ours = data_dir / "generated" / "gtk-4.0.css"
    try:
        text = target.read_text()
    except FileNotFoundError:
        text = ""
    rest = _GTK_BLOCK.sub("", text)
    if enabled:
        ours.parent.mkdir(parents=True, exist_ok=True)
        ours.write_text(theming.adwaita_css(theme))
        block = f'{GTK_BEGIN}\n@import url("file://{ours}");\n{GTK_END}\n'
        new = block + rest  # @import must come before other rules
    else:
        new = rest
    if new != text:
        if not new and not text.strip():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new)


def _gsettings():
    from gi.repository import Gio
    source = Gio.SettingsSchemaSource.get_default()
    if source is None or source.lookup(GSETTINGS_SCHEMA, True) is None:
        return None
    return Gio.Settings.new(GSETTINGS_SCHEMA)


class AppearanceModule:
    sections = ("appearance",)
    _qt_done = False
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
        try:
            sync_gtk_css(v["gtk_css"], ctx.theme, ctx.data_dir)
        except OSError as e:
            return [f"GTK 4 colors: {e}"]
        variant = "dark" if ctx.theme.dark else "light"
        home = Path.home()
        errors: list[str] = []
        if v.get("apps_follow", True):
            try:
                appthemes.gtk3_settings_ini(variant, home)
                errors += appthemes.sync_terminals(variant, home)
            except OSError as e:
                errors.append(f"apps light/dark: {e}")
            if not self._qt_done:
                self._qt_done = True
                errors += appthemes.qt_environment()
        settings = _gsettings()
        if settings is None:
            return errors + [f"{GSETTINGS_SCHEMA} is not installed; apps won't follow dark/light"]
        scheme = "prefer-dark" if ctx.theme.dark else "prefer-light"
        if settings.get_string("color-scheme") != scheme:
            settings.set_string("color-scheme", scheme)
        # GTK 3 apps, and browsers / Electron that go by the GTK theme
        want = appthemes.gtk3_theme(variant, settings.get_string("gtk-theme"), home)
        if want and settings.get_string("gtk-theme") != want:
            settings.set_string("gtk-theme", want)
        from gi.repository import Gio
        Gio.Settings.sync()
        return errors

    def import_current(self, ipc: swayipc.Connection, config: swayconfig.Config,
                       ctx: Context) -> dict[str, dict[str, Any]]:
        return {}  # defaults: automatic light/dark


class LocationModule:
    """Only data; appearance and night light re-apply when it changes."""
    sections = ("location",)
    tolerated_errors = ()

    def commands(self, section, v, changed, ctx=None) -> list[str]:
        return []

    def import_current(self, ipc, config, ctx) -> dict[str, dict[str, Any]]:
        return {}

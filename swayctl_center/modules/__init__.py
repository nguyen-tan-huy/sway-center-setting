"""Modules turn a section's values into sway commands.

A module must keep `commands()` pure (values in, command strings out) so it can
be unit tested without sway. `import_current()` reads what sway is running with
right now, so the first start adopts the user's existing setup instead of
resetting it to schema defaults.

Optional hooks, looked up with getattr by the daemon:
  snapshot(ipc) -> Any                      live state handed to commands() as ctx.live
  apply_extra(section, values, changed, ctx) -> list[str]   non-sway side effects; returns errors
  before_set(section, name, value, ctx) -> value            e.g. copy a file into the app folder
  session_start(section, values) -> list[str]               sway commands run once per login
  depends_on: tuple[str, ...]   sections (or "theme" for the active theme) whose change
                                means this section must be re-applied too
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .. import swayconfig, swayipc


@dataclass
class Context:
    data_dir: Path             # the app's config folder (wallpapers etc. live here)
    old: dict[str, Any] | None = None  # the section's values before this change
    live: Any = None           # whatever snapshot() returned
    values: dict[str, dict[str, Any]] = field(default_factory=dict)  # all sections
    theme: Any = None          # the active themes.Theme


class Module(Protocol):
    sections: tuple[str, ...]
    # sway errors that are expected and harmless for this module's commands
    tolerated_errors: tuple[str, ...]

    def commands(self, section: str, values: dict[str, Any], changed: set[str] | None,
                 ctx: Context | None = None) -> list[str]:
        """`changed` is None for a full re-apply (startup, sway reload),
        otherwise the names of the keys the user just changed."""
        ...

    def import_current(self, ipc: swayipc.Connection, config: swayconfig.Config,
                       ctx: Context) -> dict[str, dict[str, Any]]:
        ...


def all_modules() -> list[Module]:
    from . import (appearance, autostart, background, components, font, input, keybindings, keyremap,
                   launcher, layout, night_light, outputs, scrolling, theming)
    return [layout.LayoutModule(), scrolling.ScrollingModule(), input.InputModule(), outputs.OutputsModule(),
            appearance.AppearanceModule(), appearance.LocationModule(),
            night_light.NightLightModule(), background.BackgroundModule(), font.FontModule(),
            keybindings.KeybindingsModule(), keyremap.KeyremapModule(), components.BarModule(), components.NotificationsModule(),
            components.IdleModule(), components.ClipboardModule(), components.InputMethodModule(),
            components.PolkitAgentModule(),
            launcher.LauncherModule(), theming.ThemingModule(), autostart.AutostartModule()]


def by_section() -> dict[str, Module]:
    return {section: m for m in all_modules() for section in m.sections}

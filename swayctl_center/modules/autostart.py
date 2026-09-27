"""Programs started once per login, launched through sway (`exec`) so they get
the session's environment.

Nothing is imported from the user's config on first start: those `exec` lines
keep running from the config, and adopting them would start everything twice.
"""
from __future__ import annotations

from typing import Any

from .. import swayconfig, swayipc
from . import Context


class AutostartModule:
    sections = ("autostart",)
    tolerated_errors = ()

    def commands(self, section: str, v: dict[str, Any], changed: set[str] | None,
                 ctx: Context | None = None) -> list[str]:
        return []  # nothing to (re)apply; see session_start

    def session_start(self, section: str, v: dict[str, Any]) -> list[str]:
        return [f"exec {a['command']}" for a in v["commands"] if a["enabled"]]

    def import_current(self, ipc: swayipc.Connection, config: swayconfig.Config,
                       ctx: Context) -> dict[str, dict[str, Any]]:
        return {}

"""Face and fingerprint unlock settings. Nothing is applied from the daemon:
PAM is system-wide and needs root, so the page applies it on request through
pkexec (auth.apply_script); the daemon only reports what's in place."""
from __future__ import annotations

from typing import Any

from .. import auth


class UnlockModule:
    sections = ("auth",)
    tolerated_errors = ()
    depends_on: tuple[str, ...] = ()

    def commands(self, section, v, changed, ctx=None) -> list[str]:
        return []

    def status(self, v: dict[str, Any]) -> dict[str, Any]:
        return auth.status(v)

    def import_current(self, ipc, config, ctx) -> dict[str, dict[str, Any]]:
        return {}

"""Process priority: builds and indexers wait behind the program you use.

The decisions live in governor.py; this is the daemon-facing part. It makes no
sway commands. The daemon calls `tick()` on a one second timer (it only does
work every `interval` seconds, or at once when the focus or the settings
changed) and `window_event()` for sway's window events.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .. import governor, swayconfig, swayipc
from . import Context

log = logging.getLogger(__name__)


def settings_from(values: dict[str, Any]) -> governor.Settings:
    return governor.Settings(
        rules=governor.compile_rules(values["rules"]),
        protect=governor.protect_pattern(values["protect"]),
        background_nice=values["background_nice"],
        focus_boost=values["focus_boost"],
        favor_windows=values["favor_windows"],
        focus_nice=values["focus_nice"],
        ui_nice=values["ui_nice"],
        pressure_guard=values["pressure_guard"],
        compositor_realtime=values["compositor_realtime"],
        # on battery the ceiling is lower: less heat and a longer charge, the interface unaffected
        cpu_cap=values["cpu_cap_battery"] if governor.on_battery() else values["cpu_cap"],
        gpu_guard=values["gpu_guard"],
        gpu_limit=values["gpu_limit"],
    )


class PriorityModule:
    sections = ("priority",)
    tolerated_errors: tuple[str, ...] = ()

    def __init__(self, gov: governor.Governor | None = None):
        self.gov = gov or governor.Governor()
        self.focus_pid: int | None = None
        self._next = 0.0           # monotonic time of the next scan
        self._enabled = False
        self.last: dict[str, Any] = {}

    def commands(self, section, values, changed, ctx=None) -> list[str]:
        return []

    def import_current(self, ipc: swayipc.Connection, config: swayconfig.Config,
                       ctx: Context) -> dict[str, dict[str, Any]]:
        return {}

    def apply_extra(self, section: str, values: dict[str, Any], changed: set[str] | None,
                    ctx: Context | None = None) -> list[str]:
        was, self._enabled = self._enabled, bool(values["enabled"])
        if was and not self._enabled:
            n = self.gov.restore_all()
            log.info("priority: switched off, %d programs back to their own priority", n)
        if not (self._enabled and values["compositor_realtime"]):
            self.gov.release_realtime()
        self._next = 0.0  # look again at the next tick with the new rules
        return []

    # --- driven by the daemon ---------------------------------------------

    def window_event(self, payload: Any) -> None:
        if (payload or {}).get("change") == "focus":
            pid = ((payload.get("container") or {}).get("pid")) or None
            if pid != self.focus_pid:
                self.focus_pid = pid
                self._next = 0.0

    def tick(self, ipc: swayipc.Connection | None, values: dict[str, Any], now: float | None = None) -> bool:
        """Scan if it is time. Returns True when a scan ran."""
        if not values.get("enabled"):
            return False
        now = time.monotonic() if now is None else now
        # something new started: look now rather than at the next interval
        if now < self._next and not self.gov.new_pids():
            return False
        self._next = now + values["interval"]
        if self.focus_pid is None and ipc is not None and values["focus_boost"]:
            try:
                self.focus_pid = governor.focused_pid(ipc.request(swayipc.GET_TREE))
            except (swayipc.IPCError, OSError):
                pass
        try:
            wanted = self.gov.tick(settings_from(values), self.focus_pid,
                                   values["pressure_cpu"], values["pressure_io"])
        except Exception as e:  # noqa: BLE001 - a bad scan must never take the daemon down
            self.gov.last_error = str(e)
            log.warning("priority scan failed: %s", e)
            return True
        self.last = {"wanted": len(wanted)}
        return True

    def stop_priorities(self) -> None:
        """Put every program back (the session is ending)."""
        self.gov.restore_all()

    def status(self) -> dict[str, Any]:
        out = self.gov.status()
        out["enabled"] = self._enabled
        out["focus_pid"] = self.focus_pid
        out["error"] = self.gov.last_error
        return out

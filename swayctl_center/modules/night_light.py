"""Blue-light filter. wlsunset runs as its own transient systemd user unit, so
it keeps running (and logging to the journal) independently of the daemon, and
is only restarted when its arguments actually change - restarting it makes the
screen flash back to full color for a moment.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from .. import schedule, swayconfig, swayipc, units
from . import Context

UNIT = f"{units.PREFIX}night-light.service"
_DESC_PREFIX = "swayctl-center night light "
DAY_TEMP = 6500


def wlsunset_args(v: dict[str, Any], loc: schedule.Location) -> list[str] | None:
    t = str(v["temperature"])
    if v["mode"] == "off":
        return None
    if v["mode"] == "always":
        # sunrise == sunset collapses "day" to nothing: always at -t
        # (-T must still be higher than -t, or wlsunset refuses to start)
        return ["-S", "00:00", "-s", "00:00", "-t", t, "-T", str(DAY_TEMP + 1)]
    if v["mode"] == "sun":
        return ["-l", f"{loc.latitude:.4f}", "-L", f"{loc.longitude:.4f}", "-t", t, "-T", str(DAY_TEMP)]
    return ["-S", v["end"], "-s", v["start"], "-t", t, "-T", str(DAY_TEMP)]


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def unit_state() -> tuple[bool, str, int]:
    """(active, description, main pid)"""
    out = _systemctl("show", UNIT, "-p", "ActiveState", "-p", "Description", "-p", "MainPID").stdout
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return props.get("ActiveState") == "active", props.get("Description", ""), int(props.get("MainPID") or 0)


def foreign_wlsunset(_own_pid: int = 0) -> list[int]:
    """wlsunset processes not started by us - only one gamma client can work."""
    return units.foreign_pids(["-x", "wlsunset"], [UNIT])


class NightLightModule:
    sections = ("night_light",)
    tolerated_errors = ()
    depends_on = ("location",)

    def commands(self, section, v, changed, ctx=None) -> list[str]:
        return []

    def apply_extra(self, section: str, v: dict[str, Any], changed: set[str] | None,
                    ctx: Context | None = None) -> list[str]:
        loc = schedule.resolve_location(ctx.values["location"]) if ctx and ctx.values else \
            schedule.Location(0, 0, "default")
        args = wlsunset_args(v, loc)
        desc = _DESC_PREFIX + json.dumps(args)
        active, current_desc, pid = unit_state()
        if args is None:
            if active:
                _systemctl("stop", UNIT)
            return []
        if active and current_desc == desc:
            return []
        others = foreign_wlsunset(pid if active else 0)
        if others:
            return [f"night light: another wlsunset is already running (pid {', '.join(map(str, others))}); "
                    "stop it so swayctl-center can control the night light"]
        if active:
            _systemctl("stop", UNIT)
        env = [f"--setenv={k}={os.environ[k]}" for k in ("WAYLAND_DISPLAY", "XDG_RUNTIME_DIR") if k in os.environ]
        r = subprocess.run(["systemd-run", "--user", "--quiet", "--collect", f"--unit={UNIT}",
                            f"--description={desc}", *env, "wlsunset", *args],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return [f"night light: could not start wlsunset: {r.stderr.strip()}"]
        return []

    def status(self) -> dict[str, Any]:
        active, _desc, pid = unit_state()
        others = foreign_wlsunset(pid if active else 0)
        return {"running": active, "foreign_pids": others}

    def import_current(self, ipc: swayipc.Connection, config: swayconfig.Config,
                       ctx: Context) -> dict[str, dict[str, Any]]:
        return {}

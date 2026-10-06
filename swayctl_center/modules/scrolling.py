"""Smooth scrolling. Under swayctl-fx (feature "smooth-scroll") the
compositor does it: this module sends `input ... smooth_scroll` commands and
tells the service to stand down. Otherwise the work is done by swayctl-center's
smoothscroll service (a root system service: it reads the input devices); this
module writes its settings file, which the service reloads by itself.

While smooth scrolling is on, sway must not scroll the touchpad as well (it
would scroll twice) and must not re-apply direction or speed to the mouse's
smoothed wheel; the input module asks `sway_scroll_owner()` for that.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from . import Context
from .effects import fork_features

# set from get_version on every apply: the compositor smooths scrolling itself
_compositor: dict[str, Any] = {"smooth": False, "features": []}

# our device -> sway input type
SWAY_TYPES = {"touchpad": "touchpad", "mouse": "pointer"}

SERVICE = "swayctl-center-smoothscroll.service"
UNIT_PATH = Path("/etc/systemd/system") / SERVICE
PROGRAM_PATH = Path("/usr/local/lib/swayctl-center/smoothscroll.py")
OLD_SERVICE = "touchpad-inertia.service"   # the script this replaced
OLD_SCRIPTS = (Path("/usr/local/bin/touchpad-inertia.py"),
               Path.home() / ".config/nvim/scripts/touchpad-inertia.py")
CONFIG_NAME = "smoothscroll.json"

# our key -> (json section, json key)
KEYS = {f"{dev}_{k}": (dev, "enabled" if k == "smooth" else k)
        for dev in ("touchpad", "mouse")
        for k in ("smooth", "natural", "speed", "glide", "ramp_ms", "ramp_power", "smoothing", "min_velocity")}
KEYS.update({f"mouse_{k}": ("mouse", k) for k in ("ramp_floor", "burst_reset_ms", "auto_release_ms")})

# the old script's constant -> our key, to adopt its values
OLD_CONSTANTS = {
    "FRICTION": "touchpad_glide", "GAIN": "touchpad_speed", "MIN_VELOCITY": "touchpad_min_velocity",
    "NATURAL_SCROLL": "touchpad_natural", "RAMP_MS": "touchpad_ramp_ms", "RAMP_POWER": "touchpad_ramp_power",
    "SMOOTHING": "touchpad_smoothing", "MOUSE_GAIN": "mouse_speed", "MOUSE_NATURAL_SCROLL": "mouse_natural",
    "MOUSE_FRICTION": "mouse_glide", "MOUSE_MIN_VELOCITY": "mouse_min_velocity", "MOUSE_RAMP_MS": "mouse_ramp_ms",
    "MOUSE_RAMP_POWER": "mouse_ramp_power", "MOUSE_BURST_RESET_MS": "mouse_burst_reset_ms",
    "MOUSE_SMOOTHING": "mouse_smoothing", "MOUSE_AUTO_RELEASE_MS": "mouse_auto_release_ms",
    "MOUSE_RAMP_FLOOR": "mouse_ramp_floor",
}


def _active(unit: str) -> bool:
    r = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True)
    return r.stdout.strip() == "active"


def service_running() -> bool:
    # the script this replaces counts too while it's still installed: it also
    # takes over scrolling, so sway must not scroll as well
    return _active(SERVICE) or _active(OLD_SERVICE)


def detect(ipc) -> dict[str, Any]:
    """Learn whether the compositor smooths scrolling itself. Whoever applies
    first calls it (input comes before scrolling in the schema)."""
    version = ipc.get_version()
    _compositor["features"] = fork_features(version)
    _compositor["smooth"] = "smooth-scroll" in _compositor["features"]
    return version


def config_path(data_dir: Path) -> Path:
    return data_dir / "generated" / CONFIG_NAME


def sway_scroll_owner(values: dict[str, dict[str, Any]], device: str) -> str:
    """"smooth" when our service scrolls this device ("touchpad"/"mouse"),
    "compositor" when swayctl-fx smooths sway's own scrolling, else "sway"."""
    on = values.get("scrolling", {}).get(f"{device}_smooth", False)
    if _compositor["smooth"]:
        return "compositor" if on else "sway"
    return "smooth" if on and service_running() else "sway"


def service_config(v: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cfg: dict[str, dict[str, Any]] = {"touchpad": {}, "mouse": {}}
    for key, (section, name) in KEYS.items():
        cfg[section][name] = v[key]
    if _compositor["smooth"]:
        for section in cfg.values():
            section["enabled"] = False  # never smooth twice
    return cfg


def compositor_commands(v: dict[str, Any]) -> list[str]:
    cmds = []
    for dev, kind in SWAY_TYPES.items():
        on = "enabled" if v[f"{dev}_smooth"] else "disabled"
        cmds += [f"input type:{kind} smooth_scroll {on}",
                 f"input type:{kind} scroll_friction {v[f'{dev}_glide']:g}",
                 f"input type:{kind} scroll_ramp {v[f'{dev}_ramp_ms']:g} {v[f'{dev}_ramp_power']:g}"]
        if "smooth-scroll-tuning" in _compositor["features"]:
            cmds.append(f"input type:{kind} scroll_smoothing {v[f'{dev}_smoothing']:g}")
    return cmds


def adopt_old_script() -> dict[str, Any]:
    """Tuning from the touchpad-inertia script this replaces, if it's around."""
    for path in OLD_SCRIPTS:
        try:
            text = path.read_text()
        except OSError:
            continue
        found: dict[str, Any] = {}
        for const, key in OLD_CONSTANTS.items():
            m = re.search(rf"^{const}\s*=\s*(\S+)", text, re.M)
            if not m:
                continue
            raw = m.group(1)
            if raw in ("True", "False"):
                found[key] = raw == "True"
            else:
                try:
                    found[key] = round(float(raw), 4)
                except ValueError:
                    pass
        return found
    return {}


def install_script(data_dir: Path) -> str:
    """Root shell script: install the service, retire the old one. Run via pkexec."""
    program = Path(__file__).resolve().parent.parent / "smoothscroll.py"
    unit = "\n".join([
        "[Unit]", "Description=Smooth scrolling for swayctl-center (touchpad and mouse)",
        "After=multi-user.target", "",
        "[Service]", f"Environment=SMOOTH_SCROLL_CONFIG={config_path(data_dir)}",
        f"ExecStart=/usr/bin/python3 {PROGRAM_PATH}", "Restart=always", "RestartSec=1", "",
        "[Install]", "WantedBy=multi-user.target", ""])
    return "\n".join([
        "set -e",
        f"install -Dm755 {program} {PROGRAM_PATH}",
        f"cat > {UNIT_PATH} <<'UNIT'\n{unit}UNIT",
        f"systemctl disable --now {OLD_SERVICE} 2>/dev/null || true",
        f"rm -f /etc/systemd/system/{OLD_SERVICE} /usr/local/bin/touchpad-inertia.py",
        "systemctl daemon-reload",
        f"systemctl enable --now {SERVICE}",
    ])


def install(data_dir: Path) -> str | None:
    """Install or update the service (asks for the password once)."""
    r = subprocess.run(["pkexec", "sh", "-c", install_script(data_dir)], capture_output=True, text=True)
    if r.returncode == 126:
        return "cancelled"
    return (r.stderr.strip() or f"failed ({r.returncode})") if r.returncode else None


class ScrollingModule:
    sections = ("scrolling",)
    tolerated_errors = ()
    depends_on: tuple[str, ...] = ()

    def snapshot(self, ipc) -> dict[str, Any]:
        return detect(ipc)

    def commands(self, section, v, changed, ctx=None) -> list[str]:
        return compositor_commands(v) if _compositor["smooth"] else []

    def apply_extra(self, section, v, changed, ctx: Context | None = None) -> list[str]:
        path = config_path(ctx.data_dir)
        text = json.dumps(service_config(v), indent=2) + "\n"
        try:
            if path.read_text() == text:
                return []
        except OSError:
            pass
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text)
        tmp.replace(path)  # atomic: the service never reads half a file
        return []

    def status(self) -> dict[str, Any]:
        return {"installed": UNIT_PATH.exists(), "running": service_running(),
                "old_service": _active(OLD_SERVICE), "compositor": _compositor["smooth"],
                "service_active": _active(SERVICE)}

    def import_current(self, ipc, config, ctx) -> dict[str, dict[str, Any]]:
        found = adopt_old_script()
        return {"scrolling": found} if found else {}

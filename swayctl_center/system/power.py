"""Battery (UPower), power profile (power-profiles-daemon) and screen
brightness (brightnessctl), all read live - nothing is stored."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

UPOWER = "org.freedesktop.UPower"
DISPLAY_DEVICE = "/org/freedesktop/UPower/devices/DisplayDevice"
PROFILES_NAMES = ("org.freedesktop.UPower.PowerProfiles", "net.hadess.PowerProfiles")
PROFILES_PATH = "/org/freedesktop/UPower/PowerProfiles"

_STATES = {1: "charging", 2: "discharging", 3: "empty", 4: "full", 5: "not charging", 6: "discharging"}


class PowerError(RuntimeError):
    pass


@dataclass
class Battery:
    percentage: float
    state: str
    seconds_left: int  # to empty when discharging, to full when charging; 0 = unknown


@dataclass
class Brightness:
    device: str
    percent: int


_bus: Gio.DBusConnection | None = None


def _system_bus() -> Gio.DBusConnection:
    # one long-lived connection for the whole process (see the session bus fd issue)
    global _bus
    if _bus is None:
        _bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    return _bus


def _get(name: str, path: str, iface: str, prop: str):
    reply = _system_bus().call_sync(name, path, "org.freedesktop.DBus.Properties", "Get",
                                    GLib.Variant("(ss)", (iface, prop)), GLib.VariantType("(v)"),
                                    Gio.DBusCallFlags.NONE, 3000, None)
    return reply.unpack()[0]


def battery() -> Battery | None:
    try:
        if not _get(UPOWER, DISPLAY_DEVICE, "org.freedesktop.UPower.Device", "IsPresent"):
            return None
        pct = _get(UPOWER, DISPLAY_DEVICE, "org.freedesktop.UPower.Device", "Percentage")
        state = _STATES.get(_get(UPOWER, DISPLAY_DEVICE, "org.freedesktop.UPower.Device", "State"), "unknown")
        prop = "TimeToFull" if state == "charging" else "TimeToEmpty"
        secs = _get(UPOWER, DISPLAY_DEVICE, "org.freedesktop.UPower.Device", prop)
    except GLib.Error:
        return None
    return Battery(pct, state, int(secs))


def _profiles_name() -> str | None:
    for name in PROFILES_NAMES:
        try:
            _get(name, PROFILES_PATH, PROFILES_NAMES[0], "ActiveProfile")
            return name
        except GLib.Error:
            continue
    return None


def power_profiles() -> tuple[str, list[str]] | None:
    """(active profile, available profiles), or None without power-profiles-daemon."""
    name = _profiles_name()
    if name is None:
        return None
    active = _get(name, PROFILES_PATH, PROFILES_NAMES[0], "ActiveProfile")
    profiles = [p["Profile"] for p in _get(name, PROFILES_PATH, PROFILES_NAMES[0], "Profiles")]
    return active, profiles


def set_power_profile(profile: str) -> None:
    name = _profiles_name()
    if name is None:
        raise PowerError("power-profiles-daemon is not running")
    try:
        _system_bus().call_sync(name, PROFILES_PATH, "org.freedesktop.DBus.Properties", "Set",
                                GLib.Variant("(ssv)", (PROFILES_NAMES[0], "ActiveProfile",
                                                        GLib.Variant("s", profile))),
                                None, Gio.DBusCallFlags.NONE, 5000, None)
    except GLib.Error as e:
        raise PowerError(e.message) from None


def brightness() -> Brightness | None:
    if not shutil.which("brightnessctl"):
        return None
    r = subprocess.run(["brightnessctl", "-m", "--class=backlight"], capture_output=True, text=True)
    line = r.stdout.splitlines()[0] if r.returncode == 0 and r.stdout else ""
    parts = line.split(",")
    if len(parts) < 4:
        return None
    return Brightness(parts[0], int(parts[3].rstrip("%")))


def set_brightness(percent: int) -> None:
    r = subprocess.run(["brightnessctl", "--class=backlight", "set", f"{max(1, min(100, percent))}%"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise PowerError(r.stderr.strip() or "brightnessctl failed")


def format_duration(seconds: int) -> str:
    if seconds <= 0:
        return ""
    h, m = divmod(seconds // 60, 60)
    return f"{h} h {m} min" if h else f"{m} min"

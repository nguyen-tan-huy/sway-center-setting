"""Checks that a machine has what swayctl-center needs, with a fix for each
problem where there is one. Used by `swayctl-center doctor` and the first-run
assistant. Read-only; fixes are separate functions the UI calls on request.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import swayconfig

SWAY_SNIPPET = Path("/etc/sway/config.d/50-swayctl-center.conf")

PROGRAMS = [
    # (program, what it's for, optional)
    ("waybar", "the bar", False),
    ("swaync", "notifications", False),
    ("swayidle", "locking when idle", False),
    ("swaylock", "the lock screen", False),
    ("swaybg", "the wallpaper", False),
    ("wlsunset", "night light", False),
    ("cliphist", "clipboard history", False),
    ("wl-paste", "clipboard history (wl-clipboard)", False),
    ("grim", "screenshots", False),
    ("slurp", "screenshots: picking a region", False),
    ("satty", "screenshots: annotating", False),
    ("brightnessctl", "screen brightness", True),
    ("wl-clip-persist", "keeping copied text after an app closes", True),
    ("walker", "the launcher (fuzzel is used without it)", True),
    ("elephant", "the launcher's search results", True),
    ("fcitx5", "typing Vietnamese, Chinese, Japanese…", True),
]

SERVICES = [
    # (system unit, what it's for, optional)
    ("NetworkManager.service", "Wi-Fi and network", False),
    ("bluetooth.service", "Bluetooth", True),
    ("power-profiles-daemon.service", "power modes", True),
    ("upower.service", "battery status", True),
]


@dataclass
class Check:
    id: str
    label: str
    ok: bool
    detail: str = ""
    optional: bool = False
    fix: str | None = None       # id of a fix the UI can run (see apply_fix)
    fix_hint: str | None = None  # the same fix, for a terminal


def _systemctl(*args: str) -> str:
    r = subprocess.run(["systemctl", *args], capture_output=True, text=True)
    return r.stdout.strip()


def _user_config_includes_snippet() -> bool | None:
    """Whether the sway config sway would load pulls in /etc/sway/config.d.
    None when there's no sway config at all."""
    main = swayconfig.main_config_path()
    if main is None:
        return None
    if main == swayconfig.SYSTEM_CONFIG:
        return True  # the default config includes config.d
    for raw in main.read_text(errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("include") and "/etc/sway/config.d" in line:
            return True
    return False


def run_checks() -> list[Check]:
    checks: list[Check] = []
    in_sway = bool(os.environ.get("SWAYSOCK"))
    checks.append(Check("sway", "Running inside sway", in_sway,
                        "" if in_sway else "open this from a sway session"))

    included = _user_config_includes_snippet()
    main = swayconfig.main_config_path()
    if included is False:
        checks.append(Check("autostart", "Starts automatically with sway", False,
                            f"{main} doesn't include /etc/sway/config.d",
                            fix="add_include",
                            fix_hint=f"echo 'include /etc/sway/config.d/*' >> {main}"))
    else:
        installed = SWAY_SNIPPET.exists()
        checks.append(Check("autostart", "Starts automatically with sway", installed,
                            "" if installed else f"{SWAY_SNIPPET} is missing (reinstall the package)"))

    portal = _systemctl("--user", "is-active", "xdg-desktop-portal.service") == "active"
    checks.append(Check("portal", "Apps follow light/dark (XDG portal)", portal,
                        "" if portal else "xdg-desktop-portal isn't running",
                        fix="start_portal", fix_hint="systemctl --user start xdg-desktop-portal"))

    for prog, purpose, optional in PROGRAMS:
        found = shutil.which(prog) is not None
        checks.append(Check(f"program:{prog}", f"{prog} ({purpose})", found,
                            "" if found else "not installed", optional=optional,
                            fix_hint=None if found else f"sudo pacman -S {prog if prog != 'wl-paste' else 'wl-clipboard'}"))

    for unit, purpose, optional in SERVICES:
        enabled = _systemctl("is-enabled", unit)
        active = _systemctl("is-active", unit) == "active"
        if enabled in ("", "not-found") or "No such file" in enabled:
            checks.append(Check(f"service:{unit}", f"{purpose} ({unit})", False, "not installed",
                                optional=optional))
            continue
        # static/indirect units are started on demand (e.g. upower via D-Bus)
        ok = active or enabled in ("static", "indirect", "alias")
        checks.append(Check(f"service:{unit}", f"{purpose} ({unit})", ok,
                            "" if ok else f"{enabled}, {'running' if active else 'not running'}",
                            optional=optional, fix=f"enable:{unit}",
                            fix_hint=f"sudo systemctl enable --now {unit}"))
    checks += _priority_checks()
    return checks


def _priority_checks() -> list[Check]:
    """What the Performance setting needs from the system (see governor.py)."""
    import resource
    out = []
    soft = resource.getrlimit(resource.RLIMIT_NICE)[0]
    lowest = 20 - soft if soft != resource.RLIM_INFINITY else -20  # the lowest nice the user may set
    out.append(Check("priority:nice", "Favoring the app in use (nice limit)", lowest <= -4,
                     f"may go down to nice {lowest}; needs -4 or lower" if lowest > -4 else f"down to nice {lowest}",
                     optional=True,
                     fix_hint="add yourself to the audio group (limits.d/20-audio.conf) or set "
                              "'<user> - nice -11' in /etc/security/limits.d/"))
    # the processor ceiling needs the cpu controller handed to the user's manager, and the GPU guard a
    # driver that reports utilization
    uid = os.getuid()
    ctl = Path(f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/cgroup.subtree_control")
    try:
        has_cpu = "cpu" in ctl.read_text().split()
    except OSError:
        has_cpu = False
    out.append(Check("priority:cpu-ceiling", "Processor ceiling for background work (cgroup cpu controller)", has_cpu,
                     "the user manager may set it" if has_cpu else "the cpu controller is not delegated to your session",
                     optional=True, fix_hint="systemd must run with cgroup v2 and Delegate=cpu on user@.service"))
    from . import governor
    busy = governor.read_gpu_busy()
    out.append(Check("priority:gpu", "Graphics card load is readable (GPU guard)", busy is not None,
                     f"{busy}% busy now" if busy is not None else "the driver doesn't report utilization", optional=True))
    schedulers = []
    for dev in sorted(Path("/sys/block").glob("*/queue/scheduler")):
        if dev.parent.parent.name.startswith(("loop", "ram", "zram")):
            continue
        try:
            schedulers.append((dev.parent.parent.name, dev.read_text().split("[")[1].split("]")[0]))
        except (OSError, IndexError):
            pass
    bad = [f"{n}: {sch}" for n, sch in schedulers if sch not in ("bfq", "mq-deadline")]
    out.append(Check("priority:io", "Background disk priority is honored (disk scheduler)", not bad,
                     ", ".join(bad) if bad else "bfq or mq-deadline", optional=True,
                     fix_hint="echo bfq | sudo tee /sys/block/<disk>/queue/scheduler "
                              "(make it permanent with a udev rule)"))
    return out


def apply_fix(fix: str) -> str | None:
    """Run a fix; returns an error message or None. May prompt for a password
    (polkit) when it changes system services."""
    if fix == "add_include":
        main = swayconfig.main_config_path()
        if main is None:
            return "no sway config found"
        with main.open("a") as f:
            f.write("\n# added by swayctl-center: start its settings service with sway\n"
                    "include /etc/sway/config.d/*\n")
        return None
    if fix == "start_portal":
        r = subprocess.run(["systemctl", "--user", "start", "xdg-desktop-portal.service"],
                           capture_output=True, text=True)
        return r.stderr.strip() or None if r.returncode else None
    if fix.startswith("enable:"):
        unit = fix.split(":", 1)[1]
        r = subprocess.run(["pkexec", "systemctl", "enable", "--now", unit], capture_output=True, text=True)
        if r.returncode == 126:
            return "cancelled"
        return (r.stderr.strip() or f"failed ({r.returncode})") if r.returncode else None
    return f"unknown fix {fix}"

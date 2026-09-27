"""Long-running programs (waybar, swaync, wlsunset...) run as transient systemd
user units: they're supervised (restarted on crash), log to the journal, and
outlive a daemon restart. A unit's description records the exact command line,
so the daemon can tell whether a running unit is already what it wants and
avoid needless restarts (which flash the bar, the gamma, etc.).
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

PREFIX = os.environ.get("SWAYCTL_CENTER_UNIT_PREFIX", "swayctl-center-")
PASS_ENV = ("WAYLAND_DISPLAY", "SWAYSOCK", "XDG_RUNTIME_DIR", "XDG_CURRENT_DESKTOP",
            "XDG_SESSION_TYPE", "DISPLAY", "I3SOCK")


@dataclass(frozen=True)
class UnitState:
    active: bool
    description: str
    main_pid: int


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def state(unit: str) -> UnitState:
    out = _systemctl("show", unit, "-p", "ActiveState", "-p", "Description", "-p", "MainPID").stdout
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    active = props.get("ActiveState") in ("active", "activating", "reloading")
    return UnitState(active, props.get("Description", ""), int(props.get("MainPID") or 0))


def session_path() -> str | None:
    """PATH of the sway session (from sway's own environment), so programs in
    e.g. ~/.local/bin are found the way `exec` in the sway config finds them.
    None when sway's environ isn't readable (sway often runs with
    cap_sys_nice, which makes /proc/<pid>/environ root-only)."""
    import re
    m = re.search(r"sway-ipc\.\d+\.(\d+)\.sock", os.environ.get("SWAYSOCK", ""))
    if not m:
        return None
    try:
        env = Path(f"/proc/{m.group(1)}/environ").read_bytes().split(b"\0")
    except OSError:
        return None
    for item in env:
        if item.startswith(b"PATH="):
            return item[5:].decode(errors="replace")
    return None


def installed(program: str) -> bool:
    """Whether `program` can be found on the sway session's PATH."""
    import shutil
    return shutil.which(program, path=session_path() or os.environ.get("PATH")) is not None


def start(unit: str, argv: list[str], description: str, restart: bool = True,
          extra_env: dict[str, str] | None = None) -> str | None:
    """Start argv as a transient unit; returns an error message or None."""
    env = [f"--setenv={k}={os.environ[k]}" for k in PASS_ENV if k in os.environ]
    env += [f"--setenv={k}={v}" for k, v in (extra_env or {}).items()]
    path = session_path()
    if path:
        env.append(f"--setenv=PATH={path}")
    props = ["-p", "Restart=on-failure", "-p", "RestartSec=2"] if restart else []
    # Apps opened from these programs (the launcher, a click on the bar) are
    # their children; restarting e.g. the launcher for a new font mustn't
    # take them down with it.
    props += ["-p", "KillMode=process"]
    _systemctl("reset-failed", unit)
    r = subprocess.run(["systemd-run", "--user", "--quiet", "--collect", f"--unit={unit}",
                        f"--description={description}", *props, *env, *argv],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return r.stderr.strip() or f"systemd-run exited with {r.returncode}"
    return None


def stop(unit: str) -> None:
    _systemctl("stop", unit)


def mask_runtime(unit: str) -> None:
    """Stop a unit and keep it from being started (e.g. by D-Bus activation)
    until the next login - nothing persistent is changed."""
    _systemctl("mask", "--runtime", "--now", unit)


def unmask_runtime(unit: str) -> None:
    _systemctl("unmask", "--runtime", unit)


def restart(unit: str) -> None:
    _systemctl("restart", unit)


def signal(unit: str, sig: str) -> None:
    _systemctl("kill", "--kill-whom=main", "-s", sig, unit)


def _is_zombie(pid: int) -> bool:
    try:
        # the state letter follows the parenthesised command name
        stat = Path(f"/proc/{pid}/stat").read_text()
        return stat.rsplit(")", 1)[1].split()[0] == "Z"
    except (OSError, IndexError):
        return True  # gone already


def find_pids(pgrep_args: list[str]) -> list[int]:
    out = subprocess.run(["pgrep", *pgrep_args], capture_output=True, text=True).stdout
    return [pid for pid in map(int, out.split()) if pid != os.getpid() and not _is_zombie(pid)]


def _other_session(pid: int) -> bool:
    """True if the process runs on a different Wayland display than ours."""
    ours = os.environ.get("WAYLAND_DISPLAY")
    if not ours:
        return False
    try:
        env = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except OSError:
        return False
    for item in env:
        if item.startswith(b"WAYLAND_DISPLAY="):
            return item.split(b"=", 1)[1].decode() != ours
    return False


def foreign_pids(pgrep_args: list[str], own_units: list[str]) -> list[int]:
    """Matching processes in this Wayland session that don't belong to our own units."""
    own = set()
    for unit in own_units:
        out = _systemctl("show", unit, "-p", "ControlGroup").stdout.strip()
        cgroup = out.partition("=")[2]
        if cgroup:
            try:
                procs = Path("/sys/fs/cgroup", cgroup.lstrip("/"), "cgroup.procs").read_text()
                own.update(int(p) for p in procs.split())
            except OSError:
                pass
    return [pid for pid in find_pids(pgrep_args) if pid not in own and not _other_session(pid)]

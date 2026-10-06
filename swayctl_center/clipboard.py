"""Clipboard history picker over cliphist, and the launcher opener. Both run
in the caller's process (a keyboard shortcut, the settings window), so they
work whether or not the daemon is up and open on the current session.

Walker is used when its service is running (the Launcher page), otherwise
fuzzel.
"""
from __future__ import annotations

import subprocess

from . import units

_PICK = ("sel=$(cliphist list | {menu}) && [ -n \"$sel\" ] "
         "&& printf \"%s\\n\" \"$sel\" | cliphist {then}")
_FUZZEL = 'fuzzel --dmenu --prompt "{prompt}: "'
_WALKER = 'walker --dmenu --placeholder "{prompt}"'


def bar_running() -> bool:
    return subprocess.run(["pgrep", "-x", "swayctl-bar"], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def walker_running() -> bool:
    return units.installed("walker") and units.state(f"{units.PREFIX}launcher-walker.service").active


def pipeline(what: str) -> str:
    """The shell pipeline for one action; nothing user-provided is interpolated.
    An empty choice (the picker closed with Esc) does nothing, instead of
    replacing the clipboard with nothing."""
    if what == "clear":
        return "cliphist wipe"
    if what == "launcher":
        if walker_running():
            return "walker"
        # swayctl-bar's Spotlight: the bar is running and Walker isn't
        # (swayctl-center leaves Walker out when the bar is the launcher)
        return "swayctl-bar launcher" if bar_running() else "fuzzel"
    if what in ("history", "delete") and not walker_running() and bar_running():
        # swayctl-bar's launcher in clipboard mode: Enter copies, Shift+Delete
        # removes (one view for both)
        return "swayctl-bar launcher :"
    menu = _WALKER if walker_running() else _FUZZEL
    if what == "history":
        return _PICK.format(menu=menu.format(prompt="Clipboard"), then="decode | wl-copy")
    if what == "delete":
        return _PICK.format(menu=menu.format(prompt="Delete from history"), then="delete")
    raise KeyError(what)


ACTIONS = ("history", "delete", "clear")


def run(what: str, wait: bool = True) -> int:
    proc = subprocess.Popen(["sh", "-c", pipeline(what)], start_new_session=True)
    return proc.wait() if wait else 0

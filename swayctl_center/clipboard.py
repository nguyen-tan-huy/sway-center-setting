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


def walker_running() -> bool:
    return units.installed("walker") and units.state(f"{units.PREFIX}launcher-walker.service").active


def pipeline(what: str) -> str:
    """The shell pipeline for one action; nothing user-provided is interpolated.
    An empty choice (the picker closed with Esc) does nothing, instead of
    replacing the clipboard with nothing."""
    if what == "clear":
        return "cliphist wipe"
    if what == "launcher":
        return "walker" if walker_running() else "fuzzel"
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

"""Keep windows where you were looking when a monitor is plugged in.

sway sends every workspace back to the output it first lived on as soon as
that output shows up. Plug in a monitor and the workspace you were working in
(with its apps) jumps onto it, leaving the laptop screen on something else.
Here, after a monitor appears, those workspaces are moved back to the output
they were on a moment before, and each output shows the workspace it showed.
Pure functions; the daemon feeds them sway's `get_workspaces` / `get_outputs`.
"""
from __future__ import annotations

from typing import Any


def _q(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def active_outputs(outputs: list[dict[str, Any]]) -> set[str]:
    return {o["name"] for o in outputs if o.get("active")}


def plan(before_ws: list[dict[str, Any]], before_outs: set[str],
         now_ws: list[dict[str, Any]], now_outs: set[str]) -> list[str]:
    """sway commands that undo the migration onto newly appeared outputs;
    empty when no monitor was added or nothing moved."""
    added = now_outs - before_outs
    if not added:
        return []
    was = {w["name"]: w for w in before_ws}
    moved = [w for w in now_ws
             if w["name"] in was and w["output"] in added
             and was[w["name"]]["output"] in now_outs and was[w["name"]]["output"] != w["output"]]
    if not moved:
        return []
    cmds: list[str] = []
    for w in sorted(moved, key=lambda w: w["name"]):
        cmds.append(f"workspace {_q(w['name'])}")
        cmds.append(f"move workspace to output {_q(was[w['name']]['output'])}")
    # each old output shows what it showed; the focused workspace last
    now_names = {w["name"] for w in now_ws}
    for w in before_ws:
        if w.get("visible") and not w.get("focused") and w["output"] in now_outs and w["name"] in now_names:
            cmds.append(f"workspace {_q(w['name'])}")
    for w in before_ws:
        if w.get("focused") and w["name"] in now_names:
            cmds.append(f"workspace {_q(w['name'])}")
    return cmds


def switch_commands(workspaces: list[dict[str, Any]], num: int) -> list[str]:
    """Show workspace `num` on the monitor you are using, not wherever it
    lives: Mod+2 with the cursor on the laptop brings workspace 2 to the
    laptop instead of jumping to the other monitor."""
    focused = next((w["output"] for w in workspaces if w.get("focused")), None)
    cmds = [f"workspace number {num}"]
    there = next((w for w in workspaces if w.get("num") == num), None)
    if focused and there and there["output"] != focused:
        cmds.append(f"move workspace to output {_q(focused)}")
    return cmds

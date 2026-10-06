"""Displays. Stored per monitor identity ("make model serial"), so a monitor
keeps its mode/scale/position whichever port it is plugged into.

sway remembers `output` commands for monitors that aren't connected yet, so
hotplug mostly takes care of itself; the daemon only adds newly seen monitors
to the store. Commands are sent only when a monitor's live state differs from
the stored one - re-sending an identical mode can still trigger a modeset
(a visible flicker) on every sway reload.
"""
from __future__ import annotations

import re
from typing import Any

from .. import swayconfig, swayipc
from . import Context

_MODE_RE = re.compile(r"^(\d+)x(\d+)(?:@(\d+(?:\.\d+)?)Hz)?$")


def identifier(o: dict[str, Any]) -> str:
    parts = [o.get("make") or "Unknown", o.get("model") or "Unknown", o.get("serial") or "Unknown"]
    if all(p == "Unknown" for p in parts):
        return o["name"]
    return " ".join(parts)


def format_mode(mode: dict[str, Any]) -> str:
    return f"{mode['width']}x{mode['height']}@{mode['refresh'] / 1000:.3f}Hz"


def parse_mode(text: str) -> tuple[int, int, float | None] | None:
    m = _MODE_RE.match(text or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), float(m.group(3)) if m.group(3) else None


def from_live(o: dict[str, Any]) -> dict[str, Any]:
    """Stored-format config describing what a connected output runs with now."""
    cfg: dict[str, Any] = {
        "name": o["name"],
        "enabled": bool(o.get("active")),
        "mode": format_mode(o["current_mode"]) if o.get("current_mode") else "",
        "position": [o["rect"]["x"], o["rect"]["y"]] if o.get("active") else None,
        "scale": float(o.get("scale") or 1.0) if o.get("active") else 1.0,
        "transform": o.get("transform") or "normal",
        "adaptive_sync": o.get("adaptive_sync_status") == "enabled",
    }
    return cfg


def differs(cfg: dict[str, Any], live: dict[str, Any]) -> bool:
    if not cfg["enabled"]:
        return bool(live.get("active"))
    if not live.get("active"):
        return True
    want = parse_mode(cfg["mode"])
    if want and live.get("current_mode"):
        cur = live["current_mode"]
        w, h, rate = want
        if (w, h) != (cur["width"], cur["height"]):
            return True
        if rate is not None and abs(rate - cur["refresh"] / 1000) > 0.01:
            return True
    if cfg["position"] is not None and cfg["position"] != [live["rect"]["x"], live["rect"]["y"]]:
        return True
    if abs(cfg["scale"] - float(live.get("scale") or 1.0)) > 1e-3:
        return True
    if cfg["transform"] != (live.get("transform") or "normal"):
        return True
    return cfg["adaptive_sync"] != (live.get("adaptive_sync_status") == "enabled")


# --- arranging monitors (the Displays page's drag-and-drop map) -------------

Rect = tuple[float, float, float, float]  # x, y, width, height in logical pixels


def logical_size(cfg: dict[str, Any], live: dict[str, Any] | None = None) -> tuple[float, float]:
    """The space a monitor takes in the layout: its mode divided by scale,
    swapped when it's rotated a quarter turn."""
    mode = parse_mode(cfg.get("mode") or "")
    if mode:
        w, h = mode[0], mode[1]
    elif live and live.get("current_mode"):
        w, h = live["current_mode"]["width"], live["current_mode"]["height"]
    else:
        w, h = 1920, 1080
    if cfg.get("transform", "normal").removeprefix("flipped").strip("-") in ("90", "270"):
        w, h = h, w
    scale = cfg.get("scale") or 1.0
    return w / scale, h / scale


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _nearest(v: float, targets: tuple[float, ...], threshold: float) -> float:
    close = [t for t in targets if abs(t - v) <= threshold]
    return min(close, key=lambda t: abs(t - v)) if close else v


def snap(moved: Rect, others: list[Rect], threshold: float = 0.0) -> tuple[float, float]:
    """Where a dropped monitor goes: against the nearest edge of another one
    (sway leaves a gap between monitors as a dead zone for the pointer), with
    its side lined up with that monitor's when within `threshold`."""
    x, y, w, h = moved
    if not others:
        return x, y
    best: tuple[float, float, float] | None = None
    for ox, oy, ow, oh in others:
        for cx, cy in ((ox + ow, _clamp(y, oy - h, oy + oh)), (ox - w, _clamp(y, oy - h, oy + oh)),
                       (_clamp(x, ox - w, ox + ow), oy + oh), (_clamp(x, ox - w, ox + ow), oy - h)):
            # line up with the other monitor's edges or center when close
            if cx in (ox + ow, ox - w):
                cy = _nearest(cy, (oy, oy + oh - h, oy + (oh - h) / 2), threshold)
            else:
                cx = _nearest(cx, (ox, ox + ow - w, ox + (ow - w) / 2), threshold)
            d = (cx - x) ** 2 + (cy - y) ** 2
            if best is None or d < best[0]:
                best = (d, cx, cy)
    return best[1], best[2]


def normalized(positions: dict[str, tuple[float, float]]) -> dict[str, list[int]]:
    """Whole pixels, with the layout's top-left corner at 0,0 like sway reports it."""
    if not positions:
        return {}
    mx = min(p[0] for p in positions.values())
    my = min(p[1] for p in positions.values())
    return {k: [round(px - mx), round(py - my)] for k, (px, py) in positions.items()}


def command(ident: str, cfg: dict[str, Any]) -> str:
    target = '"' + ident.replace('"', '\\"') + '"'
    if not cfg["enabled"]:
        return f"output {target} disable"
    parts = [f"output {target} enable"]
    if cfg["mode"]:
        parts.append(f"mode {cfg['mode']}")
    if cfg["position"] is not None:
        parts.append(f"position {cfg['position'][0]} {cfg['position'][1]}")
    parts.append(f"scale {cfg['scale']:g}")
    parts.append(f"transform {cfg['transform']}")
    parts.append(f"adaptive_sync {'on' if cfg['adaptive_sync'] else 'off'}")
    return " ".join(parts)


class OutputsModule:
    sections = ("outputs",)
    tolerated_errors = ()

    def snapshot(self, ipc: swayipc.Connection) -> list[dict[str, Any]]:
        return ipc.get_outputs()

    def commands(self, section: str, v: dict[str, Any], changed: set[str] | None,
                 ctx: Context | None = None) -> list[str]:
        live = {identifier(o): o for o in (ctx.live if ctx and ctx.live else [])}
        cmds = []
        for ident, cfg in v["config"].items():
            o = live.get(ident)
            if o is None and live:
                # Not connected: skip it. Even an unchanged command for a missing output
                # makes sway emit output events, which the daemon answers by
                # re-applying -> an endless loop (cursor leave/enter every ~0.5s, flickering
                # hovers). The daemon applies it on the output event when it's plugged in.
                continue
            # Live state unknown: sway stores the config for when it shows up.
            if o is None or differs(cfg, o):
                cmds.append(command(ident, cfg))
        return cmds

    def import_current(self, ipc: swayipc.Connection, config: swayconfig.Config,
                       ctx: Context) -> dict[str, dict[str, Any]]:
        return {"outputs": {"config": {identifier(o): from_live(o) for o in ipc.get_outputs()}}}

    def new_outputs(self, stored: dict[str, Any], live: list[dict[str, Any]]) -> dict[str, Any]:
        """Monitors connected now but not in the store yet, in stored format."""
        return {identifier(o): from_live(o) for o in live if identifier(o) not in stored}

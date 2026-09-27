"""Touchpad and mouse, applied per device type (type:touchpad / type:pointer)."""
from __future__ import annotations

import re
from typing import Any

from .. import swayconfig, swayipc
from . import Context


def _onoff(value: bool) -> str:
    return "enabled" if value else "disabled"


# libinput field (sway IPC) -> our key, for importing the running setup
_LIBINPUT_KEYS = {
    "tap": "tap", "dwt": "dwt", "natural_scroll": "natural_scroll", "scroll_method": "scroll_method",
    "accel_profile": "accel_profile", "accel_speed": "pointer_accel", "click_method": "click_method",
    "tap_button_map": "tap_button_map", "tap_drag": "drag", "tap_drag_lock": "drag_lock",
    "middle_emulation": "middle_emulation", "left_handed": "left_handed", "send_events": "events",
}
_KEYBOARD_CONFIG = re.compile(r"^input\s+(?:\*|type:keyboard|\S+)\s+(xkb_layout|xkb_variant|xkb_options|"
                              r"repeat_delay|repeat_rate)\s+(\S+)")


# settings that belong to whoever scrolls the device (see modules/scrolling.py)
_SCROLL_KEYS = {"input.touchpad": ("scroll_method", "natural_scroll", "scroll_factor"),
                "input.pointer": ("natural_scroll", "scroll_factor")}


def scroll_values(section: str, v: dict[str, Any], owner: str) -> dict[str, Any]:
    """What sway should use for the scroll keys of a device."""
    if section == "input.touchpad":
        if owner == "smooth":
            return {"scroll_method": "none"}  # the service scrolls; sway scrolling too = double
        out = {k: v[k] for k in ("scroll_method", "natural_scroll", "scroll_factor") if k in v}
        if out.get("scroll_method") == "none":
            out["scroll_method"] = "two_finger"  # nobody would scroll otherwise
        return out
    if owner == "smooth":
        # the service already applied direction and speed to the wheel it re-emits
        return {"natural_scroll": False, "scroll_factor": 1.0}
    return {k: v[k] for k in ("natural_scroll", "scroll_factor") if k in v}


class InputModule:
    sections = ("input.touchpad", "input.pointer", "input.keyboard")
    tolerated_errors = ()
    depends_on = ("scrolling",)

    def commands(self, section: str, v: dict[str, Any], changed: set[str] | None,
                 ctx: Context | None = None) -> list[str]:
        target = "type:" + section.split(".", 1)[1]
        if section in _SCROLL_KEYS:
            from .scrolling import sway_scroll_owner
            device = "touchpad" if section == "input.touchpad" else "mouse"
            owner = sway_scroll_owner(ctx.values, device) if ctx is not None and ctx.values else "sway"
            scroll = scroll_values(section, v, owner)
            v = {k: x for k, x in v.items() if k not in _SCROLL_KEYS[section]} | scroll
            if changed is not None and changed & set(_SCROLL_KEYS[section]):
                changed = set(changed) | set(scroll)
        cmds = []
        for name, value in v.items():
            if changed is not None and name not in changed:
                continue
            if isinstance(value, bool):
                value = _onoff(value)
            elif value == "":
                if changed is None:
                    continue  # nothing to set on a full re-apply
                value = '""'   # cleared by the user: reset in sway
            cmds.append(f"input {target} {name} {value}")
        return cmds

    def import_current(self, ipc: swayipc.Connection, config: swayconfig.Config,
                       ctx: Context) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        devices = ipc.get_inputs()
        kb: dict[str, Any] = {}
        kbd = next((d for d in devices if d.get("type") == "keyboard" and "repeat_delay" in d), None)
        if kbd:
            kb.update(repeat_delay=kbd["repeat_delay"], repeat_rate=kbd["repeat_rate"])
        # layout codes aren't in IPC (only display names): read them from the config,
        # including `input type:keyboard { ... }` blocks
        for line in config.lines:
            text = line.text
            if line.blocks and line.blocks[-1].startswith("input "):
                text = f"{line.blocks[-1]} {text}"
            m = _KEYBOARD_CONFIG.match(text)
            if m:
                key, val = m.group(1), m.group(2).strip('"')
                kb[key] = int(val) if key.startswith("repeat") else val
        if kb:
            out["input.keyboard"] = kb
        for kind in ("touchpad", "pointer"):
            # Skip virtual devices (e.g. keyd, scroll helpers) that expose only
            # a partial libinput config.
            dev = next(
                (d for d in devices
                 if d.get("type") == kind and "accel_profile" in d.get("libinput", {})),
                None,
            )
            if dev is None:
                continue
            li = dev["libinput"]
            found: dict[str, Any] = {}
            for field, key in _LIBINPUT_KEYS.items():
                if field not in li:
                    continue
                val = li[field]
                if val in ("enabled", "disabled") and key != "events":
                    val = val == "enabled"
                found[key] = val
            out[f"input.{kind}"] = found
        return out

"""Window borders and gaps."""
from __future__ import annotations

import re
from typing import Any

from .. import swayconfig, swayipc
from . import Context


class LayoutModule:
    sections = ("layout",)
    tolerated_errors = ("No matching node.",)

    def commands(self, section: str, v: dict[str, Any], changed: set[str] | None,
                 ctx: Context | None = None) -> list[str]:
        style = v["border_style"]

        def border(n: int) -> str:
            return "none" if style == "none" else f"{style} {n}"

        cmds = [
            f"default_border {border(v['border'])}",
            f"default_floating_border {border(v['floating_border'])}",
            f"gaps inner {v['gaps_inner']}",
            f"gaps outer {v['gaps_outer']}",
            # the two defaults above only affect new workspaces
            f"gaps inner all set {v['gaps_inner']}",
            f"gaps outer all set {v['gaps_outer']}",
            f"smart_gaps {v['smart_gaps']}",
            f"hide_edge_borders {v['hide_edge_borders']}",
            f"focus_follows_mouse {v['focus_follows_mouse']}",
            f"mouse_warping {v['mouse_warping']}",
            f"focus_on_window_activation {v['focus_on_window_activation']}",
            f"workspace_auto_back_and_forth {'yes' if v['workspace_auto_back_and_forth'] else 'no'}",
        ]
        # Restyling existing windows would also override per-window borders set
        # by for_window rules, so only do it when the user changed the value.
        if changed is not None:
            if changed & {"border", "border_style"}:
                cmds.append(f"[tiling] border {border(v['border'])}")
            if changed & {"floating_border", "border_style"}:
                cmds.append(f"[floating] border {border(v['floating_border'])}")
        return cmds

    _PATTERNS = {
        "border": (re.compile(r"^\s*default_border\s+(?:pixel|normal)\s+(\d+)", re.M), int),
        "border_style": (re.compile(r"^\s*default_border\s+(pixel|normal|none)\b", re.M), str),
        "focus_follows_mouse": (re.compile(r"^\s*focus_follows_mouse\s+(yes|no|always)\b", re.M), str),
        "mouse_warping": (re.compile(r"^\s*mouse_warping\s+(output|container|none)\b", re.M), str),
        "focus_on_window_activation": (re.compile(
            r"^\s*focus_on_window_activation\s+(smart|urgent|focus|none)\b", re.M), str),
        "workspace_auto_back_and_forth": (re.compile(
            r"^\s*workspace_auto_back_and_forth\s+(yes|no|true|false)\b", re.M),
            lambda x: x in ("yes", "true")),
        "floating_border": (re.compile(r"^\s*default_floating_border\s+pixel\s+(\d+)", re.M), int),
        "gaps_inner": (re.compile(r"^\s*gaps\s+inner\s+(\d+)\s*$", re.M), int),
        "gaps_outer": (re.compile(r"^\s*gaps\s+outer\s+(\d+)\s*$", re.M), int),
        "smart_gaps": (re.compile(r"^\s*smart_gaps\s+(on|off|inverse_outer)\b", re.M), str),
        "hide_edge_borders": (re.compile(r"^\s*hide_edge_borders\s+(?:--i3\s+)?(\w+)", re.M), str),
    }

    def import_current(self, ipc: swayipc.Connection, config: swayconfig.Config,
                       ctx: Context) -> dict[str, dict[str, Any]]:
        # sway has no IPC query for these defaults, so read them from the
        # loaded config (read-only; the user's config is never modified).
        text = "\n".join(config.top_level())
        found: dict[str, Any] = {}
        for name, (pattern, conv) in self._PATTERNS.items():
            m = pattern.search(text)
            if m:
                found[name] = conv(m.group(1))
        return {"layout": found}

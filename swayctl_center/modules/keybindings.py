"""Keyboard shortcuts, bound at runtime with `bindsym`.

Stored keys may use "$mod", replaced by the modifier setting when applied, so
changing the modifier rebinds everything. Only the default binding mode is
managed; modes like "resize" stay in the user's config.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from .. import schema, swayconfig, swayipc
from . import Context

_BINDSYM_RE = re.compile(r"^bindsym((?:\s+--[\w-]+)*)\s+(\S+)\s+(.+)$")
_BLOCK_ENTRY_RE = re.compile(r"^(\S+)\s+(.+)$")

# The launcher in sway's stock config over the years (after `$menu` is expanded).
# It's often not even installed; ours is always there (Walker, or fuzzel).
STOCK_MENUS = (
    "exec wmenu-run",
    "exec dmenu_path | wmenu | xargs swaymsg exec --",
    "exec dmenu_path | dmenu | xargs swaymsg exec --",
)
LAUNCHER = "exec swayctl-center action launcher.open"
CLIPBOARD_KEYS = "$mod+Shift+v"
CLIPBOARD = "exec swayctl-center action clipboard.history"


def resolve(keys: str, modifier: str) -> str:
    return keys.replace("$mod", modifier)


def _identity(b: dict[str, Any], modifier: str) -> tuple[str, tuple[str, ...]]:
    return resolve(b["keys"], modifier).lower(), tuple(b["flags"])


def _flags(b: dict[str, Any]) -> str:
    return "".join(f" {f}" for f in b["flags"])


def binding_id(b: dict[str, Any]) -> str:
    """Stable short id for a binding (keys + flags), used on the command line."""
    return hashlib.sha1(f"{b['keys']}|{' '.join(b['flags'])}".encode()).hexdigest()[:12]


def needs_runner(command: str) -> bool:
    """sway strips quotes from a `bindsym` sent over IPC (unlike one read from
    the config file), so `exec sh -c '...'` would lose its quoting. Such
    commands are bound as `exec swayctl-center binding <id>`, which looks the
    original up and runs it with the quoting intact."""
    return command.split(None, 1)[0] in ("exec", "exec_always") and any(c in command for c in "'\"\\")


def self_command() -> str:
    """Absolute path of our own CLI. Shortcuts use it instead of relying on
    sway's PATH, which may not include where we're installed (e.g. ~/.local/bin),
    and which we can't even read (sway's /proc environ isn't readable)."""
    import os
    import shutil
    from pathlib import Path
    found = os.environ.get("SWAYCTL_CENTER_BIN") or shutil.which("swayctl-center")
    if found:
        return found
    local = Path.home() / ".local/bin/swayctl-center"
    return str(local) if local.exists() else "swayctl-center"


_SELF_RE = re.compile(r"^(exec(?:_always)?\s+)swayctl-center(?=\s|$)")


def bind(b: dict[str, Any], modifier: str) -> str:
    command = b["command"]
    if needs_runner(command):
        command = f"exec {self_command()} binding {binding_id(b)}"
    else:
        command = _SELF_RE.sub(lambda m: m.group(1) + self_command(), command)
    # --no-warn: overriding a binding from the user's config is intended
    return f"bindsym --no-warn{_flags(b)} {resolve(b['keys'], modifier)} {command}"


def shell_command(command: str) -> str:
    """What `exec ...` hands to the shell."""
    return command.split(None, 1)[1] if " " in command else ""


def unbind(b: dict[str, Any], modifier: str) -> str:
    return f"unbindsym{_flags(b)} {resolve(b['keys'], modifier)}"


class KeybindingsModule:
    sections = ("keybindings",)
    tolerated_errors = ()

    def commands(self, section: str, v: dict[str, Any], changed: set[str] | None,
                 ctx: Context | None = None) -> list[str]:
        mod = v["modifier"]
        head = [f"floating_modifier {mod} normal"]
        if changed is None or ctx is None or ctx.old is None:
            return head + [bind(b, mod) for b in v["bindings"]]
        old_mod = ctx.old["modifier"]
        old = {_identity(b, old_mod): b for b in ctx.old["bindings"]}
        new = {_identity(b, mod): b for b in v["bindings"]}
        cmds = [unbind(b, old_mod) for ident, b in old.items() if ident not in new]
        cmds += [bind(b, mod) for ident, b in new.items()
                 if ident not in old or old[ident]["command"] != b["command"]]
        return head + cmds

    def import_current(self, ipc: swayipc.Connection, config: swayconfig.Config,
                       ctx: Context) -> dict[str, dict[str, Any]]:
        modifier = config.variables.get("$mod", "Mod4")
        bindings = []
        for line in config.lines:
            outer = line.blocks[0] if line.blocks else ""
            if not line.blocks:
                m = _BINDSYM_RE.match(line.text)
                if not m:
                    continue
                flags, keys, command = m.group(1).split(), m.group(2), m.group(3)
            elif len(line.blocks) == 1 and outer.split()[0] == "bindsym":
                # bindsym [--flags] { keys command ... }
                m = _BLOCK_ENTRY_RE.match(line.text)
                if not m:
                    continue
                flags, keys, command = outer.split()[1:], m.group(1), m.group(2)
            else:
                continue  # inside mode "resize" { } etc.
            flags = [f for f in flags if f in schema.BINDING_FLAGS]
            keys = "+".join("$mod" if part == modifier else part for part in keys.split("+"))
            if " ".join(command.split()) in STOCK_MENUS:
                command = LAUNCHER
            bindings.append({"keys": keys, "command": command, "flags": flags})
        # Running on sway's stock config (a fresh install): also give the
        # clipboard history a shortcut, if its usual key is free.
        taken = {resolve(b["keys"], modifier).lower() for b in bindings}
        if (swayconfig.main_config_path() == swayconfig.SYSTEM_CONFIG
                and resolve(CLIPBOARD_KEYS, modifier).lower() not in taken):
            bindings.append({"keys": CLIPBOARD_KEYS, "command": CLIPBOARD, "flags": []})
        found: dict[str, Any] = {"bindings": schema.validate_bindings(bindings)}
        if modifier in schema.lookup("keybindings", "modifier").choices:
            found["modifier"] = modifier
        return {"keybindings": found}

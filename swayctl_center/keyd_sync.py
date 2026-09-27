"""Root side of key remapping: turns swayctl-center's keyd.json (written by the
user) into /etc/keyd/default.conf and reloads keyd. Run by the
swayctl-center-keyd.path unit whenever the file changes. Stdlib only.

keyd runs as root and its config can run commands (`command(...)`), so
nothing from the user's file is copied through as text: only plain key
names that keyd itself lists are accepted.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

TARGET = Path("/etc/keyd/default.conf")
MARKER = "# managed by swayctl-center: change it in Sway Control Center > Keyboard"
# a key turned into a modifier acts as that modifier's layer, as keyd wants
MODIFIER_LAYERS = {"leftcontrol": "control", "rightcontrol": "control", "leftshift": "shift",
                   "rightshift": "shift", "leftalt": "alt", "rightalt": "altgr",
                   "leftmeta": "meta", "rightmeta": "meta"}
# The Copilot key holds Shift+Meta+F23 down for as long as it's held. The
# composite [meta+shift] layer catches F23 and turns on our own "copilot"
# layer; while it's on, [meta+shift+copilot] sends every key with just the
# chosen modifier - keyd drops the Shift and Meta the key came with there.
# (Copilot+Shift+x therefore can't be told apart and sends Super+x.)
COPILOT = {"super": "M", "rightcontrol": "C"}
_NAME = re.compile(r"^[a-z0-9][a-z0-9_]*$")


def known_keys() -> set[str]:
    r = subprocess.run(["keyd", "list-keys"], capture_output=True, text=True)
    return {k for k in r.stdout.split() if _NAME.match(k)}


def render(remaps: list[dict], keys: set[str], copilot: str = "default") -> str:
    lines = [MARKER, "", "[ids]", "*", "", "[main]"]
    seen = set()
    for r in remaps:
        src, dst = r.get("from"), r.get("to")
        if src in keys and dst in keys and src != dst and src not in seen:
            seen.add(src)
            action = f"layer({MODIFIER_LAYERS[dst]})" if dst in MODIFIER_LAYERS else dst
            lines.append(f"{src} = {action}")
    if copilot in COPILOT:
        remapped = {r.get("from"): r.get("to") for r in remaps}
        lines += ["", "[copilot]", "", "[meta+shift]", "f23 = layer(copilot)", "", "[meta+shift+copilot]"]
        for k in sorted(keys - set(MODIFIER_LAYERS) - {"f23"}):
            out = remapped.get(k, k) if remapped.get(k, k) in keys else k
            if out not in MODIFIER_LAYERS:
                lines.append(f"{k} = {COPILOT[copilot]}-{out}")
    return "\n".join(lines) + "\n"


def main(path: str) -> int:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        print(f"keyd_sync: can't read {path}: {e}", file=sys.stderr)
        return 1
    remaps = data.get("remaps") if isinstance(data, dict) else None
    copilot = data.get("copilot") if isinstance(data, dict) else None
    text = render([r for r in remaps or [] if isinstance(r, dict)], known_keys(), copilot)
    try:
        if TARGET.read_text() == text:
            return 0
    except OSError:
        pass
    tmp = TARGET.with_suffix(".tmp")
    tmp.write_text(text)
    os.chmod(tmp, 0o644)
    tmp.replace(TARGET)
    return subprocess.run(["keyd", "reload"]).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))

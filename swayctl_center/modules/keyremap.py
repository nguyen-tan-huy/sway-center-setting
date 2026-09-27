"""Key remapping and swapping with keyd (it works below sway, so it applies
everywhere: the login screen, the TTY, every app).

keyd reads root-owned /etc/keyd; this module only writes generated/keyd.json.
A root path unit installed once (with the password) watches that file and
runs keyd_sync.py, which checks every key name and rewrites
/etc/keyd/default.conf - so changing a remap needs no password.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import Context

KEYD_CONFIG = Path("/etc/keyd/default.conf")
SERVICE = "swayctl-center-keyd.service"
PATH_UNIT = "swayctl-center-keyd.path"
UNIT_DIR = Path("/etc/systemd/system")
PROGRAM_PATH = Path("/usr/local/lib/swayctl-center/keyd_sync.py")
CONFIG_NAME = "keyd.json"
_NAME = re.compile(r"^[a-z0-9_]+$")
_COPILOT_LINES = {"f23=layer(copilot)": "super",  # the [meta+shift+copilot] lines say which
                  "f23=layer(meta)": "super", "f23=layer(control)": "rightcontrol",
                  "f23=leftmeta": "super", "f23=rightcontrol": "rightcontrol"}
_LAYER_KEYS = {"layer(control)": "leftcontrol", "layer(shift)": "leftshift", "layer(alt)": "leftalt",
               "layer(altgr)": "rightalt", "layer(meta)": "leftmeta"}


def config_path(data_dir: Path) -> Path:
    return data_dir / "generated" / CONFIG_NAME


def expand(remaps: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Stored remaps -> one-way pairs for keyd; a swap is two of them."""
    out = []
    for r in remaps:
        out.append({"from": r["from"], "to": r["to"]})
        if r["swap"]:
            out.append({"from": r["to"], "to": r["from"]})
    return out


def parse_keyd(text: str) -> tuple[list[dict[str, Any]], bool, str]:
    """Remaps from a keyd config's [main] section, pairing swaps up, and what
    the Copilot key does.
    Also says whether anything else was there that can't be shown here
    (layers, macros, other devices...)."""
    section, ids, pairs, other, copilot = "", [], {}, False, "default"
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if section == "meta+shift" and line.replace(" ", "") in _COPILOT_LINES:
            copilot = _COPILOT_LINES[line.replace(" ", "")]
            continue
        if section == "copilot":
            continue
        if section == "meta+shift+copilot":  # ours: "a = M-a" for every key
            m = re.match(r"^\S+\s*=\s*([MC])-", line)
            if m:
                copilot = {"M": "super", "C": "rightcontrol"}[m.group(1)]
            continue
        if section == "ids":
            ids.append(line)
            continue
        m = re.match(r"^(\S+)\s*=\s*(\S+)$", line)
        if m and m.group(2) in _LAYER_KEYS:  # layer(control) -> leftcontrol
            m = re.match(r"^(\S+)\s*=\s*(\S+)$", f"{m.group(1)} = {_LAYER_KEYS[m.group(2)]}")
        if section == "main" and m and _NAME.match(m.group(1)) and _NAME.match(m.group(2)):
            pairs.setdefault(m.group(1), m.group(2))
        else:
            other = True
    if ids not in ([], ["*"]):
        other = True
    remaps, done = [], set()
    for src, dst in pairs.items():
        if src in done:
            continue
        swap = pairs.get(dst) == src
        remaps.append({"from": src, "to": dst, "swap": swap})
        done.update({src, dst} if swap else {src})
    return remaps, other, copilot


def installed() -> bool:
    return (UNIT_DIR / PATH_UNIT).exists()


def keyd_installed() -> bool:
    return shutil.which("keyd") is not None


def key_names() -> list[str]:
    """What keyd can remap, for the UI's pickers."""
    try:
        r = subprocess.run(["keyd", "list-keys"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return sorted({k for k in r.stdout.split() if _NAME.match(k)})


def shipped_program() -> Path:
    return Path(__file__).resolve().parent.parent / "keyd_sync.py"


def root_program() -> Path:
    """What the root service runs. From the package (root-owned, so it's safe
    to run as root, and upgrades update it) - or, when running from a source
    checkout the user can write to, a copy made when it was set up."""
    shipped = shipped_program()
    return shipped if str(shipped).startswith("/usr/") else PROGRAM_PATH


def outdated() -> bool:
    """The root service runs an older copy than this version ships."""
    try:
        return installed() and root_program() == PROGRAM_PATH and \
            PROGRAM_PATH.read_bytes() != shipped_program().read_bytes()
    except OSError:
        return True


def install_script(data_dir: Path) -> str:
    """Root shell script: install the sync service and its path unit. Run via pkexec."""
    program = root_program()
    watched = config_path(data_dir)
    service = "\n".join([
        "[Unit]", "Description=Apply swayctl-center key remaps to keyd", "",
        "[Service]", "Type=oneshot", f"ExecStart=/usr/bin/python3 {program} {watched}", ""])
    path = "\n".join([
        "[Unit]", "Description=Watch swayctl-center key remaps", "",
        "[Path]", f"PathChanged={watched}", f"Unit={SERVICE}", "",
        "[Install]", "WantedBy=multi-user.target", ""])
    return "\n".join([
        "set -e",
        f"install -Dm755 {shipped_program()} {PROGRAM_PATH}" if program == PROGRAM_PATH else ":",
        # keep the config this replaces, once
        f"[ -f {KEYD_CONFIG} ] && ! grep -q 'managed by swayctl-center' {KEYD_CONFIG} && "
        f"cp -n {KEYD_CONFIG} {KEYD_CONFIG}.before-swayctl-center || true",
        f"cat > {UNIT_DIR / SERVICE} <<'UNIT'\n{service}UNIT",
        f"cat > {UNIT_DIR / PATH_UNIT} <<'UNIT'\n{path}UNIT",
        "systemctl daemon-reload",
        "systemctl enable --now keyd.service",
        f"systemctl enable --now {PATH_UNIT}",
        f"systemctl start {SERVICE}",
    ])


def _unit_program() -> Path | None:
    """The script the installed service runs (older set-ups always used a copy)."""
    try:
        m = re.search(r"ExecStart=\S+ (\S+)", (UNIT_DIR / SERVICE).read_text())
    except OSError:
        return None
    return Path(m.group(1)) if m else None


def install(data_dir: Path) -> str | None:
    """Install the sync service (asks for the password once)."""
    r = subprocess.run(["pkexec", "sh", "-c", install_script(data_dir)], capture_output=True, text=True)
    if r.returncode == 126:
        return "cancelled"
    return (r.stderr.strip() or f"failed ({r.returncode})") if r.returncode else None


class KeyremapModule:
    sections = ("keyremap",)
    tolerated_errors = ()
    depends_on: tuple[str, ...] = ()

    def commands(self, section, v, changed, ctx=None) -> list[str]:
        return []

    def apply_extra(self, section, v, changed, ctx: Context | None = None) -> list[str]:
        path = config_path(ctx.data_dir)
        text = json.dumps({"remaps": expand(v["remaps"]), "copilot": v["copilot"]}, indent=2) + "\n"
        try:
            if path.read_text() == text:
                return []
        except OSError:
            pass
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text)
        tmp.replace(path)  # atomic: the sync service never reads half a file
        return []

    def status(self) -> dict[str, Any]:
        r = subprocess.run(["systemctl", "is-active", "keyd.service"], capture_output=True, text=True)
        try:
            text = KEYD_CONFIG.read_text()
        except OSError:
            text = ""
        # things in the user's own keyd config that setting this up would replace
        other = "managed by swayctl-center" not in text and parse_keyd(text)[1]
        return {"keyd_installed": keyd_installed(), "installed": installed(),
                "running": r.stdout.strip() == "active", "other_config": other,
                "outdated": outdated() or (installed() and _unit_program() != root_program())}

    def import_current(self, ipc, config, ctx) -> dict[str, dict[str, Any]]:
        try:
            text = KEYD_CONFIG.read_text()
        except OSError:
            return {}
        remaps, _other, copilot = parse_keyd(text)
        known = set(key_names())
        if known:  # keyd ignores lines like "ctrl = alt"; so do we
            remaps = [r for r in remaps if r["from"] in known and r["to"] in known]
        found: dict[str, Any] = {"remaps": remaps} if remaps else {}
        if copilot != "default":
            found["copilot"] = copilot
        return {"keyremap": found} if found else {}

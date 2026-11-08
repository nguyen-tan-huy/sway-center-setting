"""Unlocking with a password, a fingerprint (fprintd) or a face (Howdy).

Where it applies:
  lock    swayctl-lock, which asks the password and the fingerprint at once;
          each has its own PAM service (swayctl-lock-password/-fingerprint)
  sudo, polkit, login (ly)
          the system's PAM files get a marked block with `auth sufficient
          pam_fprintd.so` / `pam_howdy.so` before their first auth line, then
          whatever was there (the password) - never instead of it

Nothing here writes /etc itself: plan() works out every file's new text as
the user and apply_script() is the root shell script that writes them (run
through pkexec by the UI), keeping a one-time backup of each original.
"""
from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

PAM_DIR = Path("/etc/pam.d")
VENDOR_PAM_DIR = Path("/usr/lib/pam.d")      # e.g. polkit-1 ships only here
MODULE_DIR = Path("/usr/lib/security")
METHODS = ("fingerprint", "face")
PAM_MODULE = {"fingerprint": "pam_fprintd.so", "face": "pam_howdy.so"}
# Howdy installs its module in a folder of its own on some systems
FACE_MODULE_DIRS = (MODULE_DIR, MODULE_DIR / "howdy", Path("/lib/security/howdy"))
HOWDY_CONFIG = Path("/etc/howdy/config.ini")
# where the setting applies -> PAM service file
TARGETS = {"sudo": "sudo", "polkit": "polkit-1", "login": "ly"}
LOCK_SERVICES = ("password", "fingerprint", "face")
BEGIN = "# >>> swayctl-center: fingerprint unlock (managed; turn it off in the app to remove)"
END = "# <<< swayctl-center"
_BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.S)
BACKUP_SUFFIX = ".swayctl-backup"


def lock_service(method: str) -> str:
    return f"swayctl-lock-{method}"


def module_ref(method: str, module_dirs=None) -> str:
    """How a PAM line names the module: its file name, or the full path when
    it isn't in the system's security folder."""
    name = PAM_MODULE[method]
    if method != "face":
        return name
    for d in (module_dirs or FACE_MODULE_DIRS):
        if (d / name).exists():
            return name if d == MODULE_DIR else str(d / name)
    return name


def lock_service_text(method: str) -> str:
    auth = {"password": "auth       include    login",
            "fingerprint": f"auth       required   {PAM_MODULE['fingerprint']}",
            "face": f"auth       required   {module_ref('face')}"}[method]
    return ("#%PAM-1.0\n"
            f"# swayctl-lock: unlock with the {method} (written by swayctl-center)\n"
            f"{auth}\n"
            "account    include    login\n")


def strip_block(text: str) -> str:
    return _BLOCK.sub("", text)


def with_block(text: str, methods: list[str]) -> str:
    """text with our block (for these methods, in order) before its first auth line."""
    text = strip_block(text)
    if not methods:
        return text
    block = BEGIN + "\n" + "".join(f"auth       sufficient   {module_ref(m)}\n" for m in methods) + END + "\n"
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        first = line.split()[:1]
        if first and first[0].lstrip("-") == "auth":
            return "".join(lines[:i]) + block + "".join(lines[i:])
    raise ValueError("no auth line to put the block before")


def block_methods(text: str) -> list[str]:
    m = _BLOCK.search(text)
    if not m:
        return []
    found = []
    for method, module in PAM_MODULE.items():
        pos = m.group(0).find(module)
        if pos >= 0:
            found.append((pos, method))
    return [method for _pos, method in sorted(found)]


def wanted(values: dict, target: str) -> list[str]:
    """Methods enabled for a target."""
    return [m for m in METHODS if values.get(f"{m}_{target}")]


def read_service(name: str, pam_dir: Path = PAM_DIR, vendor_dir: Path = VENDOR_PAM_DIR) -> str | None:
    for d in (pam_dir, vendor_dir):
        try:
            return (d / name).read_text()
        except OSError:
            continue
    return None


@dataclass
class Change:
    path: Path
    text: str
    backup: bool   # keep the original once before the first change


def _check_kept(old: str, new: str) -> None:
    """Every original (non-block) line must survive: a guard against ever
    dropping the password line."""
    keep = [line for line in strip_block(old).splitlines() if line.strip()]
    got = [line for line in strip_block(new).splitlines() if line.strip()]
    if keep != got:
        raise ValueError("refusing a change that would alter the existing PAM lines")


def plan(values: dict, pam_dir: Path = PAM_DIR, vendor_dir: Path = VENDOR_PAM_DIR) -> list[Change]:
    """The files that need writing for these settings (empty when all match)."""
    changes: list[Change] = []
    for target, service in TARGETS.items():
        current = read_service(service, pam_dir, vendor_dir)
        if current is None:
            continue  # e.g. ly isn't installed
        new = with_block(current, wanted(values, target))
        if new != current:
            _check_kept(current, new)
            in_etc = (pam_dir / service).exists()
            changes.append(Change(pam_dir / service, new, backup=in_etc))
    for method in LOCK_SERVICES:
        path = pam_dir / lock_service(method)
        text = lock_service_text(method)
        try:
            if path.read_text() == text:
                continue
        except OSError:
            pass
        changes.append(Change(path, text, backup=False))
    return changes


def apply_script(changes: list[Change]) -> str:
    """Root shell script writing the planned files atomically."""
    out = ["set -e"]
    for i, c in enumerate(changes):
        p = shlex.quote(str(c.path))
        tmp = shlex.quote(f"{c.path}.swayctl-new")
        if c.backup:
            out.append(f"[ -e {p}{BACKUP_SUFFIX} ] || cp -p {p} {p}{BACKUP_SUFFIX}")
        tag = f"SWAYCTL_PAM_{i}"
        out.append(f"cat > {tmp} <<'{tag}'\n{c.text}{tag}")
        out.append(f"chmod 644 {tmp} && mv -f {tmp} {p}")
    return "\n".join(out) + "\n"


def restore_script(pam_dir: Path = PAM_DIR) -> str:
    """Put every backed-up original back and remove our lock services."""
    out = ["set -e"]
    for service in TARGETS.values():
        p = shlex.quote(str(pam_dir / service))
        out.append(f"[ ! -e {p}{BACKUP_SUFFIX} ] || mv -f {p}{BACKUP_SUFFIX} {p}")
        # files with no backup (we created them, e.g. polkit-1): just drop our block
        out.append(f"[ ! -e {p} ] || sed -i '/^# >>> swayctl-center: fingerprint/,/^# <<< swayctl-center$/d' {p}")
    for method in LOCK_SERVICES:
        out.append(f"rm -f {shlex.quote(str(pam_dir / lock_service(method)))}")
    return "\n".join(out) + "\n"


# ---- what the machine has ------------------------------------------------------

def fingerprint_readers() -> list[str]:
    """Readers fprintd knows of (empty without fprintd or a reader)."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        r = bus.call_sync("net.reactivated.Fprint", "/net/reactivated/Fprint/Manager",
                          "net.reactivated.Fprint.Manager", "GetDevices", None,
                          GLib.VariantType("(ao)"), Gio.DBusCallFlags.NO_AUTO_START, 2000, None)
        return list(r.unpack()[0])
    except Exception:  # noqa: BLE001 - no bus / no fprintd / no reader all mean "none"
        return []


def face_cameras(sys_dir: Path = Path("/sys/class/video4linux")) -> list[str]:
    """Infrared cameras (/dev/videoN): Howdy only trusts those, a plain webcam
    could be fooled by a photo."""
    found = []
    try:
        nodes = sorted(sys_dir.iterdir(), key=lambda p: (len(p.name), p.name))
    except OSError:
        return []
    for node in nodes:
        try:
            name = (node / "name").read_text().strip().lower()
            index = (node / "index").read_text().strip()
        except OSError:
            continue
        if index == "0" and re.search(r"\bir\b|infrared", name):
            found.append(f"/dev/{node.name}")
    return found


def howdy_installed(module_dirs=None) -> bool:
    return any((d / PAM_MODULE["face"]).exists() for d in (module_dirs or FACE_MODULE_DIRS))


def howdy_device(config: Path = HOWDY_CONFIG) -> str:
    """The camera Howdy is set to use ('' when unset or unreadable)."""
    try:
        for line in config.read_text().splitlines():
            m = re.match(r"\s*device_path\s*=\s*(\S+)", line)
            if m:
                return m.group(1)
    except OSError:
        pass
    return ""


def face_setup_script(camera: str, config: Path = HOWDY_CONFIG) -> str:
    """Root script: point Howdy at the infrared camera."""
    c, cfg = shlex.quote(camera), shlex.quote(str(config))
    return ("set -e\n"
            f"[ -f {cfg} ] || {{ echo 'Howdy has no config yet: {config}'; exit 1; }}\n"
            f"sed -i \"s|^device_path.*|device_path = $(printf %s {c})|\" {cfg}\n")


def status(values: dict, pam_dir: Path = PAM_DIR, vendor_dir: Path = VENDOR_PAM_DIR,
           module_dir: Path = MODULE_DIR, readers: list[str] | None = None) -> dict:
    applied = {}
    for target, service in TARGETS.items():
        text = read_service(service, pam_dir, vendor_dir)
        applied[target] = None if text is None else block_methods(text)
    try:
        pending = bool(plan(values, pam_dir, vendor_dir))
    except ValueError:
        pending = True
    return {
        "fingerprint": {"hardware": fingerprint_readers() if readers is None else readers,
                        "installed": (module_dir / PAM_MODULE["fingerprint"]).exists()},
        "face": {"installed": howdy_installed(), "cameras": face_cameras(), "device": howdy_device()},
        "applied": applied,
        "pending": pending,
        "user": os.environ.get("USER", ""),
    }

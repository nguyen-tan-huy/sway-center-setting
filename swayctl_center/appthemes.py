"""Apps that follow light/dark beyond the color-scheme preference.

- GTK 3 (and browsers / Electron that read the GTK theme): gtk-theme becomes
  adw-gtk3 / adw-gtk3-dark (adw-gtk-theme) when installed, else Adwaita /
  Adwaita-dark, plus gtk-application-prefer-dark-theme in gtk-3.0/settings.ini.
- Qt: QT_QPA_PLATFORMTHEME=xdgdesktopportal for apps started by systemd or
  D-Bus (the launcher's): Qt 6 then follows the portal's color scheme live.
- Terminals: foot (colors-dark / colors-light + SIGUSR1/2 to switch running
  ones), kitty (dark/light-theme.auto.conf: kitty switches by itself) and
  alacritty (an imported colors file it reloads).

Files we own carry MARK; a user's own config is only ever given one include
line, and only when it doesn't exist yet or already has ours.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

MARK = "# managed by swayctl-center (light/dark); edits are overwritten"

# 16-color terminal palettes in the same spirit as the two themes
PALETTES = {
    "dark": {"bg": "#1c1c1e", "fg": "#f5f5f7", "cursor": "#0a84ff", "sel_bg": "#3a3a3c", "ansi": [
        "#3a3a3c", "#ff453a", "#32d74b", "#ffd60a", "#0a84ff", "#bf5af2", "#64d2ff", "#e5e5ea",
        "#636366", "#ff6961", "#4ae06a", "#ffe14d", "#409cff", "#da8fff", "#8de3ff", "#ffffff"]},
    "light": {"bg": "#f5f5f7", "fg": "#1d1d1f", "cursor": "#0a84ff", "sel_bg": "#c7dcff", "ansi": [
        "#1d1d1f", "#d70015", "#248a3d", "#a05a00", "#0040dd", "#8944ab", "#0071a4", "#8e8e93",
        "#636366", "#ff3b30", "#34c759", "#b25000", "#007aff", "#af52de", "#32ade6", "#3a3a3c"]},
}

GTK3_FAMILIES = ({"light": "adw-gtk3", "dark": "adw-gtk3-dark"}, {"light": "Adwaita", "dark": "Adwaita-dark"})


def _themes_dirs(home: Path) -> list[Path]:
    return [Path("/usr/share/themes"), home / ".themes", home / ".local/share/themes"]


def gtk3_theme(variant: str, current: str, home: Path) -> str | None:
    """The gtk-theme to set, or None to leave the user's own theme alone."""
    known = {n for fam in GTK3_FAMILIES for n in fam.values()} | {""}
    if current not in known:
        return None
    adw = any((d / "adw-gtk3").is_dir() for d in _themes_dirs(home))
    fam = GTK3_FAMILIES[0] if adw else GTK3_FAMILIES[1]
    return fam[variant]


def _write(path: Path, text: str) -> bool:
    try:
        if path.read_text() == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return True


def gtk3_settings_ini(variant: str, home: Path) -> None:
    """gtk-application-prefer-dark-theme in gtk-3.0/settings.ini (read at app start)."""
    path = home / ".config/gtk-3.0/settings.ini"
    want = f"gtk-application-prefer-dark-theme={'true' if variant == 'dark' else 'false'}"
    try:
        lines = path.read_text().splitlines()
    except OSError:
        lines = ["[Settings]"]
    out, done = [], False
    for line in lines:
        if line.strip().startswith("gtk-application-prefer-dark-theme"):
            if not done:
                out.append(want)
                done = True
            continue
        out.append(line)
    if not done:
        i = next((n for n, l in enumerate(out) if l.strip() == "[Settings]"), None)
        if i is None:
            out = ["[Settings]", want] + out
        else:
            out.insert(i + 1, want)
    _write(path, "\n".join(out) + "\n")


# --- terminals --------------------------------------------------------------

def foot_colors(variant: str) -> str:
    def section(name: str, p: dict) -> list[str]:
        out = [f"[{name}]", f"background={p['bg'][1:]}", f"foreground={p['fg'][1:]}",
               f"cursor={p['bg'][1:]} {p['cursor'][1:]}", f"selection-background={p['sel_bg'][1:]}",
               f"selection-foreground={p['fg'][1:]}"]
        out += [f"regular{i}={c[1:]}" for i, c in enumerate(p["ansi"][:8])]
        out += [f"bright{i}={c[1:]}" for i, c in enumerate(p["ansi"][8:])]
        return out + [""]
    return "\n".join([MARK, "[main]", f"initial-color-theme={variant}", ""]
                     + section("colors-dark", PALETTES["dark"]) + section("colors-light", PALETTES["light"]))


def kitty_colors(variant: str) -> str:
    p = PALETTES[variant]
    lines = [MARK, f"background {p['bg']}", f"foreground {p['fg']}", f"cursor {p['cursor']}",
             f"selection_background {p['sel_bg']}", f"selection_foreground {p['fg']}"]
    lines += [f"color{i} {c}" for i, c in enumerate(p["ansi"])]
    return "\n".join(lines) + "\n"


def alacritty_colors(variant: str) -> str:
    p = PALETTES[variant]
    names = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]
    out = [MARK, "[colors.primary]", f'background = "{p["bg"]}"', f'foreground = "{p["fg"]}"', "",
           "[colors.cursor]", f'cursor = "{p["cursor"]}"', f'text = "{p["bg"]}"', "",
           "[colors.selection]", f'background = "{p["sel_bg"]}"', f'text = "{p["fg"]}"', "", "[colors.normal]"]
    out += [f'{n} = "{c}"' for n, c in zip(names, p["ansi"][:8])]
    out += ["", "[colors.bright]"] + [f'{n} = "{c}"' for n, c in zip(names, p["ansi"][8:])]
    return "\n".join(out) + "\n"


def _include_once(path: Path, line: str, create: str) -> str | None:
    """Make sure `path` (a user's own config) includes our file: create it with
    `create` when missing; when it exists without the line, prepend the line
    if the file format allows (foot); returns an error to show otherwise."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        _write(path, create)
        return None
    except OSError as e:
        return f"{path}: {e}"
    if line in text:
        return None
    return f"add this line to {path} so it follows light/dark: {line}"


def sync_terminals(variant: str, home: Path, signal=True) -> list[str]:
    errors: list[str] = []
    cfg = home / ".config"
    if shutil.which("foot"):
        _write(cfg / "foot/swayctl-colors.ini", foot_colors(variant))
        inc = f"include={cfg / 'foot/swayctl-colors.ini'}"
        foot_ini = cfg / "foot/foot.ini"
        try:
            text = foot_ini.read_text()
            if inc not in text:
                # foot reads includes in place: first, so the user's own colors still win
                _write(foot_ini, f"{inc}\n{text}")
        except FileNotFoundError:
            _write(foot_ini, f"{MARK}\n{inc}\n")
        except OSError as e:
            errors.append(f"{foot_ini}: {e}")
        if signal:
            # running foot (and foot --server) windows switch right away
            subprocess.run(["pkill", "-USR1" if variant == "dark" else "-USR2", "-x", "foot"], capture_output=True)
    if shutil.which("kitty"):
        # kitty (0.38+) picks these by the system's color scheme, live
        _write(cfg / "kitty/dark-theme.auto.conf", kitty_colors("dark"))
        _write(cfg / "kitty/light-theme.auto.conf", kitty_colors("light"))
        _write(cfg / "kitty/no-preference-theme.auto.conf", kitty_colors(variant))
    if shutil.which("alacritty"):
        colors = cfg / "alacritty/swayctl-colors.toml"
        _write(colors, alacritty_colors(variant))  # alacritty reloads imports by itself
        imp = f'import = ["{colors}"]'
        err = _include_once(cfg / "alacritty/alacritty.toml", imp, f"{MARK}\n[general]\n{imp}\n")
        if err:
            errors.append(err)
    return errors


# --- Qt -----------------------------------------------------------------------

def qt_environment() -> list[str]:
    """Qt apps started by systemd / D-Bus (the launcher's) follow the portal's
    color scheme. Left alone when the user chose a platform theme (qt6ct...)."""
    if os.environ.get("QT_QPA_PLATFORMTHEME"):
        return []
    errors = []
    for argv in (["systemctl", "--user", "set-environment", "QT_QPA_PLATFORMTHEME=xdgdesktopportal"],
                 ["dbus-update-activation-environment", "QT_QPA_PLATFORMTHEME=xdgdesktopportal"]):
        try:
            r = subprocess.run(argv, capture_output=True, text=True)
            if r.returncode:
                errors.append(f"{argv[0]}: {r.stderr.strip()}")
        except OSError as e:
            errors.append(f"{argv[0]}: {e}")
    return errors

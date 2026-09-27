"""Shell components: the bar, notifications, idle/lock, clipboard history and
the input method. Each can be "managed": swayctl-center then runs it as a
systemd user unit with config files it generates (themed with the active
theme and font) under <app folder>/generated/<component>/. The user's own
config files for these programs are never touched.

A component is never started while the same program is already running from
somewhere else (typically an `exec` in the user's sway config) - two bars or
two notification daemons would fight. First start adopts that situation by
marking such components unmanaged.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shlex
from pathlib import Path
from typing import Any

from .. import jsonc, owned, swayconfig, swayipc, theming, themes, units
from . import Context


def _font(ctx: Context) -> tuple[str, int]:
    f = (ctx.values or {}).get("font") or {"family": "sans-serif", "size": 10}
    return f["family"], f["size"]


def _font_weight(ctx: Context) -> int:
    """The interface font's weight as a CSS number."""
    from .font import css_weight
    return css_weight(((ctx.values or {}).get("font") or {}).get("weight", "regular"))


def _file_hash(path: Path) -> str:
    """Change marker for a user file we pass to a program by path."""
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest() + "\n"
    except OSError:
        return "missing\n"


def _render_template(path: str, theme, ctx: Context) -> str:
    text = theming.expand(path).read_text()  # OSError -> reported by apply_extra
    return theming.render(text, theming.placeholders(theme, (ctx.values or {}).get("font")))


def _rgb_triplet(hex_color: str) -> str:
    return ", ".join(str(int(hex_color[i:i + 2], 16)) for i in (1, 3, 5))


def read_base(path: str) -> Any:
    """The user's own config file (JSON with comments), or None."""
    if not path:
        return None
    return jsonc.loads(theming.expand(path).read_text())


def apply_map(cfg: dict, v: dict[str, Any], mapping: dict[str, str]) -> None:
    for key, cfg_key in mapping.items():
        cfg[cfg_key] = v[key]


def values_from(cfg: dict, mapping: dict[str, str]) -> dict[str, Any]:
    return {key: cfg[cfg_key] for key, cfg_key in mapping.items() if cfg_key in cfg}


class Component:
    name = ""
    depends_on: tuple[str, ...] = ("theme", "font")
    tolerated_errors = ()
    # pgrep arguments that find this program when someone else started it
    detect: list[list[str]] = []

    @property
    def sections(self) -> tuple[str, ...]:
        return (self.name,)

    def programs(self, v: dict[str, Any], ctx: Context) -> dict[str, list[str]]:
        """{unit suffix: argv}; "" for a single program."""
        raise NotImplementedError

    def program_env(self, suffix: str, v: dict[str, Any], ctx: Context) -> dict[str, str]:
        """Extra environment for one program's unit."""
        return {}

    def detect_for(self, suffix: str) -> list[list[str]]:
        """pgrep arguments finding someone else's copy of one program."""
        return self.detect

    def files(self, v: dict[str, Any], ctx: Context) -> dict[str, str]:
        """{file name: content} written to generated/<name>/"""
        return {}

    def reload(self, unit: str) -> None:
        """Pick up changed files without a restart where the program supports it."""
        units.stop(unit)  # the next apply_extra step starts it again

    def unit_name(self, suffix: str) -> str:
        return f"{units.PREFIX}{self.name}{'-' + suffix if suffix else ''}.service"

    def gen_dir(self, ctx: Context) -> Path:
        return ctx.data_dir / "generated" / self.name

    def commands(self, section, v, changed, ctx=None) -> list[str]:
        return []

    def _write_files(self, v, ctx) -> bool:
        changed = False
        d = self.gen_dir(ctx)
        for name, content in self.files(v, ctx).items():
            path = d / name
            try:
                if path.read_text() == content:
                    continue
            except OSError:
                pass
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            changed = True
        return changed

    def all_units(self, v, ctx) -> list[str]:
        return [self.unit_name(s) for s in self.programs(v, ctx)]

    def apply_extra(self, section: str, v: dict[str, Any], changed: set[str] | None,
                    ctx: Context | None = None) -> list[str]:
        wanted = {self.unit_name(s): argv for s, argv in self.programs(v, ctx).items()}
        if not v["managed"]:
            self.stop_all(v, ctx)
            return []
        try:
            files_changed = self._write_files(v, ctx)
        except OSError as e:
            return [f"{self.name}: {e}"]
        errors = []
        suffix_of = {self.unit_name(s): s for s in self.programs(v, ctx)}
        for unit, argv in wanted.items():
            if not units.installed(argv[0]):
                # an optional helper that isn't installed mustn't take the rest down
                errors.append(f"{argv[0]} is not installed")
                continue
            desc = f"swayctl-center {self.name}: {shlex.join(argv)}"
            st = units.state(unit)
            if st.active and st.description == desc:
                if files_changed:
                    self.reload(unit)
                    if units.state(unit).active:
                        continue
                else:
                    continue
            elif st.active:
                units.stop(unit)
            suffix = unit[len(self.unit_name("")) - len(".service"):-len(".service")].lstrip("-")
            others = self.foreign(v, ctx, suffix)
            if others:
                errors.append(f"{self.name}: {argv[0]} is already running outside swayctl-center "
                              f"(pid {', '.join(map(str, others))}); remove it from your sway config "
                              "or turn off \"Managed by swayctl-center\"")
                return errors
            err = units.start(unit, argv, desc, extra_env=self.program_env(suffix_of[unit], v, ctx))
            if err:
                errors.append(f"{self.name}: could not start {argv[0]}: {err}")
        return errors

    def foreign(self, v, ctx, suffix: str | None = None) -> list[int]:
        own = self.all_units(v, ctx)
        patterns = self.detect if suffix is None else self.detect_for(suffix)
        pids: list[int] = []
        for args in patterns:
            pids += units.foreign_pids(args, own)
        return sorted(set(pids))

    def stop_all(self, v, ctx) -> None:
        for unit in self.all_units(v, ctx):
            if units.state(unit).active:
                units.stop(unit)

    def status(self, v, ctx) -> dict[str, Any]:
        progs = self.programs(v, ctx)
        missing = sorted({argv[0] for argv in progs.values() if not units.installed(argv[0])})
        running = [units.state(self.unit_name(s)).active for s, argv in progs.items()
                   if argv[0] not in missing]
        return {"managed": v["managed"], "running": bool(running) and all(running),
                "foreign_pids": self.foreign(v, ctx), "missing": missing}

    def is_running_elsewhere(self, suffix: str | None = None) -> bool:
        patterns = self.detect if suffix is None else self.detect_for(suffix)
        return any(units.foreign_pids(args, []) for args in patterns)

    def import_current(self, ipc: swayipc.Connection, config: swayconfig.Config,
                       ctx: Context) -> dict[str, dict[str, Any]]:
        # Already started by the user's setup: leave it to them.
        if self.is_running_elsewhere():
            return {self.name: {"managed": False}}
        return {}


# --- bar -------------------------------------------------------------------

# Icons are Nerd Font (Material Design) glyphs from ttf-nerd-fonts-symbols;
# the bar's CSS falls back to "Symbols Nerd Font" for them.
_VOLUME = ["\U000f057f", "\U000f0580", "\U000f057e"]
_WIFI = ["\U000f091f", "\U000f0922", "\U000f0925", "\U000f0928"]
# empty, 10%, 20% ... 90%, full; charging the same, with a bolt
_BATTERY = ["\U000f008e", "\U000f007a", "\U000f007b", "\U000f007c", "\U000f007d", "\U000f007e",
            "\U000f007f", "\U000f0080", "\U000f0081", "\U000f0082", "\U000f0079"]
_BATTERY_CHARGING = ["\U000f089f", "\U000f089c", "\U000f0086", "\U000f0087", "\U000f0088", "\U000f089d",
                     "\U000f0089", "\U000f089e", "\U000f008a", "\U000f008b", "\U000f0085"]
_BELL, _BELL_DOT, _BELL_OFF = "\U000f009a", "\U000f009c", "\U000f009b"

WAYBAR_MODULE_CONFIG: dict[str, dict[str, Any]] = {
    "sway/workspaces": {"disable-scroll": True},
    "sway/window": {"max-length": 60},
    "clock": {"format": "{:%H:%M}", "format-alt": "{:%a %d %b  %H:%M}",
              "tooltip-format": "<tt>{calendar}</tt>"},
    "tray": {"spacing": 8},
    "pulseaudio": {"format": "{icon}", "format-muted": "\U000f075f", "format-icons": {"default": _VOLUME},
                   "tooltip-format": "{volume}% · {desc}",
                   "on-click": "pavucontrol", "scroll-step": 5},
    "network": {"format-wifi": "{icon}", "format-icons": _WIFI, "format-ethernet": "\U000f0200",
                "format-disconnected": "\U000f092e", "tooltip-format": "{ifname} {ipaddr}",
                "tooltip-format-wifi": "{essid} {signalStrength}%\n{ipaddr}"},
    "bluetooth": {"format": "\U000f00af", "format-disabled": "", "format-off": "\U000f00b2",
                  "format-connected": "\U000f00b1", "tooltip-format-connected": "{device_enumerate}",
                  "tooltip-format-enumerate-connected": "{device_alias}"},
    # just the icon; the percentage and time left are in the tooltip
    "battery": {"format": "{icon}", "format-icons": {"default": _BATTERY, "charging": _BATTERY_CHARGING,
                                                     "plugged": _BATTERY_CHARGING},
                "tooltip-format": "{capacity}% · {timeTo}",
                "states": {"warning": 25, "critical": 10}},
    "backlight": {"format": "{icon}", "tooltip-format": "{percent}%", "format-icons": ["\U000f00de", "\U000f00df", "\U000f00e0"]},
    "cpu": {"format": "\U000f035b {usage}%"},
    "memory": {"format": "\U000f061a {}%"},
    "temperature": {"format": "\U000f050f {temperatureC}°C"},
    "idle_inhibitor": {"format": "{icon}", "format-icons": {"activated": "\U000f0176", "deactivated": "\U000f0faa"},
                       "tooltip-format-activated": "Staying awake", "tooltip-format-deactivated": "Locks when idle"},
    "power-profiles-daemon": {"format": "{icon}", "format-icons": {
        "performance": "\U000f04c5", "balanced": "\U000f0f85", "power-saver": "\U000f0f86", "default": "\U000f0f85"}},
    "keyboard-state": {"capslock": True, "format": "{icon}",
                       "format-icons": {"locked": "\U000f0a9b", "unlocked": ""}},
    "custom/notifications": {"exec": "swaync-client -swb", "return-type": "json", "format": "{icon}",
                             "format-icons": {"notification": _BELL_DOT, "none": _BELL,
                                              "dnd-notification": _BELL_OFF, "dnd-none": _BELL_OFF,
                                              "inhibited-notification": _BELL_DOT, "inhibited-none": _BELL,
                                              "dnd-inhibited-notification": _BELL_OFF, "dnd-inhibited-none": _BELL_OFF},
                             "on-click": "swaync-client -t -sw", "on-click-right": "swaync-client -d -sw",
                             "escape": True},
}


BAR_MAP = {
    "position": "position", "layer": "layer", "height": "height", "spacing": "spacing",
    "margin_top": "margin-top", "margin_right": "margin-right", "margin_bottom": "margin-bottom",
    "margin_left": "margin-left", "exclusive": "exclusive", "modules_left": "modules-left",
    "modules_center": "modules-center", "modules_right": "modules-right",
}


class BarModule(Component):
    name = "bar"
    detect = [["-x", "waybar"]]

    def __init__(self):
        self._hidden: dict[str, str] = {}  # sway bar id -> its mode before we hid it

    def snapshot(self, ipc) -> dict[str, str]:
        """sway's own bars (`bar { }` in the config, e.g. the stock swaybar): {id: mode}."""
        return {bar_id: ipc.get_bar_config(bar_id).get("mode", "dock")
                for bar_id in ipc.get_bar_config() or []}

    def commands(self, section, v, changed, ctx=None) -> list[str]:
        """While waybar is managed, sway's own bars are made invisible so there
        aren't two bars (the stock config starts swaybar); they come back when
        the bar isn't managed any more. `sway reload` shows them again, and the
        re-apply after it hides them again."""
        bars = (ctx.live if ctx else None) or {}
        if v["managed"]:
            cmds = []
            for bar_id, mode in bars.items():
                if mode != "invisible":
                    self._hidden[bar_id] = mode
                    cmds.append(f"bar {bar_id} mode invisible")
            return cmds
        cmds = [f"bar {bar_id} mode {mode}" for bar_id, mode in self._hidden.items()
                if bars.get(bar_id) == "invisible"]
        self._hidden.clear()
        return cmds

    def programs(self, v, ctx):
        d = self.gen_dir(ctx)
        return {"": ["waybar", "-c", str(d / "config.json"), "-s", str(d / "style.css")]}

    def config(self, v, ctx) -> dict[str, Any]:
        base = read_base(v["config_file"])
        if isinstance(base, list):  # several bars: settings apply to the first
            base = base[0] if base else {}
        cfg = copy.deepcopy(base) if isinstance(base, dict) else {}
        if v["config_file"] and "include" in cfg:
            # relative includes were relative to the user's file, not ours
            here = theming.expand(v["config_file"]).parent
            inc = cfg["include"] if isinstance(cfg["include"], list) else [cfg["include"]]
            cfg["include"] = [str((here / Path(i).expanduser()).resolve()) for i in inc]
        # modules the base config already uses keep waybar's own defaults;
        # only ones added here get our built-in settings
        known = {m for k in ("modules-left", "modules-center", "modules-right") for m in cfg.get(k, [])}
        apply_map(cfg, v, BAR_MAP)
        if not v["height"]:
            cfg.pop("height")  # 0 = let waybar size it
        for m in v["modules_left"] + v["modules_center"] + v["modules_right"]:
            if m not in cfg and m not in known:
                cfg[m] = copy.deepcopy(WAYBAR_MODULE_CONFIG.get(m, {}))
        clock = cfg.setdefault("clock", copy.deepcopy(WAYBAR_MODULE_CONFIG["clock"]))
        clock["format"], clock["format-alt"] = v["clock_format"], v["clock_format_alt"]
        return cfg

    def values_from_config(self, cfg: Any) -> dict[str, Any]:
        if isinstance(cfg, list):
            cfg = cfg[0] if cfg else {}
        if not isinstance(cfg, dict):
            return {}
        found = values_from(cfg, BAR_MAP)
        if "height" not in cfg:
            found["height"] = 0
        for key in ("modules_left", "modules_center", "modules_right"):
            found.setdefault(key, [])
        clock = cfg.get("clock") or {}
        if "format" in clock:
            found["clock_format"] = clock["format"]
        if "format-alt" in clock:
            found["clock_format_alt"] = clock["format-alt"]
        return found

    def before_set(self, section, name, value, ctx):
        # the user's own files become the app's: copied in, scripts and all
        if name == "config_file":
            return owned.adopt(value, ctx.data_dir, "bar", "base.jsonc", with_references=True)
        if name == "style_template":
            return owned.adopt(value, ctx.data_dir, "bar", "style.css.template")
        return value

    def related_values(self, section, name, value, ctx) -> dict[str, Any]:
        """Choosing a base config adopts its layout, so nothing jumps around."""
        if name == "config_file" and value:
            return self.values_from_config(read_base(value))
        return {}

    def import_current(self, ipc, config, ctx):
        found = super().import_current(ipc, config, ctx).get(self.name, {})
        base = (ctx.values or {}).get(self.name, {}).get("config_file")
        if base:
            try:
                found.update(self.values_from_config(read_base(base)))
            except (OSError, ValueError):
                pass
        return {self.name: found} if found else {}

    def theme(self, v, ctx):
        """The bar can have its own theme, e.g. dark on a light desktop."""
        if v["theme"]:
            t = themes.load_all(ctx.data_dir).get(v["theme"])
            if t is not None:
                return t
        return ctx.theme

    def files(self, v, ctx):
        t = self.theme(v, ctx)
        style = _render_template(v["style_template"], t, ctx) if v["style_template"] else self.css(ctx, t)
        return {"config.json": json.dumps(self.config(v, ctx), indent=2, ensure_ascii=False) + "\n",
                "style.css": style}

    def css(self, ctx: Context, t=None) -> str:
        t = t or ctx.theme
        family, size = _font(ctx)
        px = round(size * 4 / 3)
        return f"""/* generated by swayctl-center; edits are overwritten */
* {{ font-family: "{family}", "Symbols Nerd Font", sans-serif; font-weight: {_font_weight(ctx)}; font-size: {px}px; min-height: 0; border: none; border-radius: 0; }}
window#waybar {{ background: {t.bg}; color: {t.fg}; }}
tooltip {{ background: {t.bg}; color: {t.fg}; border: 1px solid {t.muted}; }}
#workspaces button {{ padding: 0 8px; color: {t.muted}; background: transparent; box-shadow: none; }}
#workspaces button:hover {{ color: {t.fg}; background: alpha({t.muted}, 0.25); }}
#workspaces button.focused {{ color: {t.bg}; background: {t.accent}; }}
#workspaces button.urgent {{ color: {t.bg}; background: {t.fg}; }}
#mode {{ color: {t.bg}; background: {t.accent}; padding: 0 8px; }}
.modules-right > widget > *, .modules-center > widget > *, .modules-left > widget > label {{ padding: 0 8px; }}
#battery.warning {{ color: {t.accent}; }}
#battery.critical:not(.charging) {{ color: {t.bg}; background: {t.accent}; }}
#idle_inhibitor.activated, #custom-notifications.notification {{ color: {t.accent}; }}
"""

    def reload(self, unit):
        # Not SIGUSR2: waybar 0.15 aborts (core dump) while reloading on it.
        units.restart(unit)


# --- notifications ---------------------------------------------------------

NOTIFICATIONS_MAP = {
    "position_x": "positionX", "position_y": "positionY", "layer": "layer",
    "width": "notification-window-width", "control_center_width": "control-center-width",
    "control_center_height": "control-center-height", "fit_to_screen": "fit-to-screen",
    "timeout": "timeout", "timeout_low": "timeout-low", "timeout_critical": "timeout-critical",
    "grouping": "notification-grouping", "relative_timestamps": "relative-timestamps",
    "image_visibility": "image-visibility", "hide_on_clear": "hide-on-clear",
    "hide_on_action": "hide-on-action", "keyboard_shortcuts": "keyboard-shortcuts",
}


class NotificationsModule(Component):
    name = "notifications"
    detect = [["-x", "swaync"], ["-x", "mako"], ["-x", "dunst"]]
    # The swaync package's own unit is D-Bus activated and restarts on
    # failure: left alone it respawns the moment ours isn't up yet.
    distro_unit = "swaync.service"

    def apply_extra(self, section, v, changed, ctx=None):
        if v["managed"]:
            units.mask_runtime(self.distro_unit)
        else:
            units.unmask_runtime(self.distro_unit)
        return super().apply_extra(section, v, changed, ctx)

    def programs(self, v, ctx):
        d = self.gen_dir(ctx)
        return {"": ["swaync", "-c", str(d / "config.json"), "-s", str(d / "style.css")]}

    def session_start(self, section, v):
        if not (v["managed"] and v["dnd_on_start"]):
            return []
        # swaync may still be starting; retry briefly
        return ["exec sh -c 'for i in $(seq 20); do swaync-client --dnd-on >/dev/null 2>&1 && exit; sleep 0.5; done'"]

    def config(self, v, ctx) -> dict[str, Any]:
        base = read_base(v["config_file"])
        cfg = copy.deepcopy(base) if isinstance(base, dict) else {
            "widgets": ["title", "dnd", "notifications"],
            "widget-config": {
                "title": {"text": "Notifications", "clear-all-button": True, "button-text": "Clear"},
                "dnd": {"text": "Do not disturb"},
            },
        }
        apply_map(cfg, v, NOTIFICATIONS_MAP)
        return cfg

    def values_from_config(self, cfg: Any) -> dict[str, Any]:
        return values_from(cfg, NOTIFICATIONS_MAP) if isinstance(cfg, dict) else {}

    def before_set(self, section, name, value, ctx):
        if name == "config_file":
            return owned.adopt(value, ctx.data_dir, "notifications", "base.json", with_references=True)
        if name == "style_template":
            return owned.adopt(value, ctx.data_dir, "notifications", "style.css.template")
        return value

    def related_values(self, section, name, value, ctx) -> dict[str, Any]:
        if name == "config_file" and value:
            return self.values_from_config(read_base(value))
        return {}

    def import_current(self, ipc, config, ctx):
        found = super().import_current(ipc, config, ctx).get(self.name, {})
        base = (ctx.values or {}).get(self.name, {}).get("config_file")
        if base:
            try:
                found.update(self.values_from_config(read_base(base)))
            except (OSError, ValueError):
                pass
        return {self.name: found} if found else {}

    def files(self, v, ctx):
        style = _render_template(v["style_template"], ctx.theme, ctx) if v["style_template"] else self.css(ctx)
        return {"config.json": json.dumps(self.config(v, ctx), indent=2, ensure_ascii=False) + "\n",
                "style.css": style}

    def css(self, ctx: Context) -> str:
        t = ctx.theme
        family, _size = _font(ctx)
        default_css = Path("/etc/xdg/swaync/style.css")
        imp = f'@import url("file://{default_css}");\n' if default_css.exists() else ""
        return f"""/* generated by swayctl-center; edits are overwritten */
{imp}:root {{
  --cc-bg: alpha({t.bg}, 0.92);
  --noti-bg: {_rgb_triplet(t.bg)};
  --noti-bg-alpha: 0.95;
  --noti-bg-darker: {t.bg};
  --noti-bg-hover: alpha({t.muted}, 0.35);
  --noti-bg-focus: alpha({t.muted}, 0.25);
  --noti-close-bg: alpha({t.muted}, 0.5);
  --noti-close-bg-hover: {t.muted};
  --noti-border-color: alpha({t.muted}, 0.6);
  --text-color: {t.fg};
  --text-color-disabled: {t.muted};
  --bg-selected: {t.accent};
}}
* {{ font-family: "{family}", sans-serif; font-weight: {_font_weight(ctx)}; }}
"""

    def reload(self, unit):
        # swaync can reload both without restarting (and losing notifications)
        import subprocess
        subprocess.run(["swaync-client", "--reload-config"], capture_output=True)
        subprocess.run(["swaync-client", "--reload-css"], capture_output=True)


# --- idle and lock ---------------------------------------------------------

def lock_command(ctx: Context) -> list[str]:
    t = ctx.theme
    idle = (ctx.values or {}).get("idle") or {}
    bare = {k: getattr(t, k).lstrip("#") for k in ("bg", "fg", "accent", "muted")}
    argv = ["swaylock", "-f", "-c", bare["bg"], "--inside-color", bare["bg"],
            "--ring-color", bare["fg"], "--line-color", bare["fg"], "--text-color", bare["fg"],
            "--key-hl-color", bare["accent"], "--separator-color", bare["fg"]]
    image = ((ctx.values or {}).get("background") or {}).get("image")
    if idle.get("lock_background") == "wallpaper" and image:
        argv += ["-i", str(ctx.data_dir / image), "-s", "fill"]
    if idle.get("show_failed_attempts"):
        argv.append("-F")
    if idle.get("ignore_empty_password"):
        argv.append("-e")
    return argv


class IdleModule(Component):
    name = "idle"
    depends_on = ("theme", "background")
    detect = [["-x", "swayidle"]]

    def programs(self, v, ctx):
        lock = shlex.join(lock_command(ctx))
        argv = ["swayidle", "-w"]
        if v["lock_after"]:
            argv += ["timeout", str(v["lock_after"]), lock]
        if v["screen_off_after"]:
            argv += ["timeout", str(v["screen_off_after"]), 'swaymsg "output * power off"',
                     "resume", 'swaymsg "output * power on"']
        if v["suspend_after"]:
            argv += ["timeout", str(v["suspend_after"]), "systemctl suspend"]
        if v["lock_before_sleep"]:
            argv += ["before-sleep", lock]
        return {"": argv}

    _TIMEOUT_RE = re.compile(r"timeout\s+(\d+)\s+('[^']*'|\"(?:[^\"\\\\]|\\\\.)*\"|\S+)")

    def import_current(self, ipc, config, ctx):
        found: dict[str, Any] = {}
        running = self.is_running_elsewhere()
        if running:
            found["managed"] = False
        # timeouts from the user's `exec swayidle ...` line, whether or not it runs now
        for line in config.top_level():
            if not re.match(r"^exec(_always)?\s+(\S*/)?swayidle\b", line):
                continue
            for secs, cmd in self._TIMEOUT_RE.findall(line):
                if "lock" in cmd and "lock_after" not in found:
                    found["lock_after"] = int(secs)
                elif ("power off" in cmd or "dpms off" in cmd) and "screen_off_after" not in found:
                    found["screen_off_after"] = int(secs)
            found["lock_before_sleep"] = "before-sleep" in line
        return {self.name: found} if found else {}


# --- clipboard -------------------------------------------------------------

class ClipboardModule(Component):
    name = "clipboard"
    depends_on = ()
    detect = [["-f", r"^(\S*/)?wl-paste .*--watch cliphist"]]

    def programs(self, v, ctx):
        store = ["cliphist", "-max-items", str(v["max_items"]), "store"]
        progs = {"text": ["wl-paste", "--type", "text", "--watch", *store]}
        if v["images"]:
            progs["image"] = ["wl-paste", "--type", "image", "--watch", *store]
        if v["persist"]:
            progs["persist"] = ["wl-clip-persist", "--clipboard", "regular"]
        return progs

    def detect_for(self, suffix):
        return [["-x", "wl-clip-persist"]] if suffix == "persist" else self.detect

    def all_units(self, v, ctx):
        # all of them, so turning an option off also stops its program
        return [self.unit_name(s) for s in ("text", "image", "persist")]

    def apply_extra(self, section, v, changed, ctx=None):
        for option, suffix in (("images", "image"), ("persist", "persist")):
            if not v[option] and units.state(self.unit_name(suffix)).active:
                units.stop(self.unit_name(suffix))
        return super().apply_extra(section, v, changed, ctx)


    def import_current(self, ipc, config, ctx):
        found = super().import_current(ipc, config, ctx).get(self.name, {})
        if self.is_running_elsewhere("persist"):
            found["persist"] = False
        conf = Path.home() / ".config/cliphist/config"
        try:
            m = re.search(r"^max-items\s+(\d+)", conf.read_text(), re.M)
            if m:
                found["max_items"] = int(m.group(1))
        except OSError:
            pass
        return {self.name: found} if found else {}


# --- input method ----------------------------------------------------------

class InputMethodModule(Component):
    name = "input_method"
    depends_on = ()
    detect = [["-x", "fcitx5"]]

    def programs(self, v, ctx):
        return {"": ["fcitx5"]}


# --- polkit agent ----------------------------------------------------------

POLKIT_GNOME = "/usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1"


class PolkitAgentModule(Component):
    """The password prompt behind pkexec (turning on system services, setting
    up smooth scrolling...). Desktops start one; plain sway doesn't."""
    name = "polkit_agent"
    depends_on = ()
    detect = [["-f", r"polkit.*agent|policykit-agent|lxpolkit|xfce-polkit|soteria"]]

    def programs(self, v, ctx):
        return {"": [POLKIT_GNOME]}

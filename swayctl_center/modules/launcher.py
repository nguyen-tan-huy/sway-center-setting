"""App launcher: Walker (GTK4 UI) on top of elephant (the data service with
one plugin per kind of result). Both run as units with configuration the app
generates under generated/launcher/, so nothing is written to ~/.config/walker
or ~/.config/elephant:

  elephant --config generated/launcher/elephant   (reads <provider>.toml, menus/)
  walker --gapplication-service with XDG_CONFIG_HOME=generated/launcher
                                                   (reads walker/config.toml, walker/themes/)

With elephant's config folder moved, it no longer looks in /etc/xdg/elephant,
where the AUR packages install the provider plugins, so those are symlinked
into our folder. When Walker isn't installed, the `launcher.open` action falls
back to fuzzel.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import units
from . import Context
from .components import Component, _font, _font_weight

THEME_NAME = "swayctl-center"
PLUGIN_DIRS = (Path("/etc/xdg/elephant/providers"), Path("/usr/lib/elephant"),
               Path("/usr/lib64/elephant"), Path("/usr/local/lib/elephant"))

# setting -> (elephant provider, AUR package, walker prefix or None)
PROVIDERS = {
    "apps": ("desktopapplications", "elephant-desktopapplications-bin", None),
    "settings": ("menus", "elephant-menus-bin", None),
    "calc": ("calc", "elephant-calc-bin", "="),
    "files": ("files", "elephant-files-bin", "/"),
    "websearch": ("websearch", "elephant-websearch-bin", "@"),
    "symbols": ("symbols", "elephant-symbols-bin", "."),
    "windows": ("windows", "elephant-windows-bin", "$"),
    "runner": ("runner", "elephant-runner-bin", ">"),
}
ALWAYS = ("providerlist", "elephant-providerlist-bin", ";")  # ";" lists what's available

ENGINES = {
    "google": ("Google", "https://www.google.com/search?q=%TERM%"),
    "duckduckgo": ("DuckDuckGo", "https://duckduckgo.com/?q=%TERM%"),
    "bing": ("Bing", "https://www.bing.com/search?q=%TERM%"),
    "brave": ("Brave Search", "https://search.brave.com/search?q=%TERM%"),
    "startpage": ("Startpage", "https://www.startpage.com/do/search?query=%TERM%"),
    "youtube": ("YouTube", "https://www.youtube.com/results?search_query=%TERM%"),
}

# What the Settings menu offers inside the launcher: (text, keywords, icon, cli args)
SETTINGS_ENTRIES = [
    ("Wi-Fi and network", "wifi network internet vpn", "network-wireless", "ui --page system:network"),
    ("Bluetooth", "bluetooth headphones pair", "bluetooth", "ui --page system:bluetooth"),
    ("Sound", "sound volume audio speaker microphone", "audio-volume-high", "ui --page system:sound"),
    ("Power and battery", "power battery brightness", "battery", "ui --page system:power"),
    ("Clipboard settings", "clipboard history copy paste", "edit-paste", "ui --page clipboard"),
    ("Displays", "display monitor screen resolution scale", "video-display", "ui --page outputs"),
    ("Appearance", "theme dark light color", "preferences-desktop-theme", "ui --page appearance"),
    ("Night light", "night light blue filter warm", "weather-clear-night", "ui --page night_light"),
    ("Wallpaper", "wallpaper background", "preferences-desktop-wallpaper", "ui --page background"),
    ("Keyboard shortcuts", "shortcuts keys bindings", "preferences-desktop-keyboard-shortcuts",
     "ui --page keybindings"),
    ("Keyboard", "keyboard layout typing repeat", "input-keyboard", "ui --page input.keyboard"),
    ("Touchpad", "touchpad tap scroll", "input-touchpad", "ui --page input.touchpad"),
    ("Bar", "bar waybar panel", "preferences-system", "ui --page bar"),
    ("Sway Control Center", "settings preferences control", "preferences-system", "ui"),
    ("Switch light / dark", "dark light mode theme toggle", "weather-clear-night", "action theme.toggle"),
    ("Night light on / off", "night light toggle", "weather-clear-night", "action night_light.toggle"),
    ("Lock screen", "lock", "system-lock-screen", "action lock"),
    ("Clipboard history", "clipboard history paste", "edit-paste", "action clipboard.history"),
    ("Notification center", "notifications", "preferences-system-notifications", "action notifications.panel"),
    ("Do not disturb", "notifications dnd quiet", "notifications-disabled", "action notifications.dnd"),
]


def installed_plugins() -> set[str]:
    names = set()
    for d in PLUGIN_DIRS:
        if d.is_dir():
            names.update(p.stem for p in d.rglob("*.so"))
    return names


def _toml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)  # a JSON string is a valid TOML basic string


def _toml_list(items: list[str]) -> str:
    return "[" + ", ".join(_toml_str(i) for i in items) + "]"


class LauncherModule(Component):
    name = "launcher"
    detect = [["-x", "walker"], ["-x", "elephant"]]

    def root(self, ctx: Context) -> Path:
        return self.gen_dir(ctx)

    def programs(self, v, ctx):
        root = self.root(ctx)
        return {"elephant": ["elephant", "--config", str(root / "elephant")],
                "walker": ["walker", "--gapplication-service"]}

    def program_env(self, suffix, v, ctx):
        # walker has no --config flag; it reads $XDG_CONFIG_HOME/walker
        return {"XDG_CONFIG_HOME": str(self.root(ctx))} if suffix == "walker" else {}

    def detect_for(self, suffix):
        return [["-x", suffix]]

    def enabled(self, v) -> list[str]:
        return [k for k in PROVIDERS if v[k]]

    def missing_packages(self, v) -> list[str]:
        have = installed_plugins()
        pkgs = [PROVIDERS[k][1] for k in self.enabled(v) if PROVIDERS[k][0] not in have]
        if ALWAYS[0] not in have:
            pkgs.append(ALWAYS[1])
        if not units.installed("elephant"):
            pkgs.insert(0, "elephant-bin")
        return pkgs

    # --- generated files ------------------------------------------------

    def walker_config(self, v) -> str:
        enabled = self.enabled(v)
        default = []
        for key in ("apps", "settings", "calc", "websearch"):
            if key in enabled:
                default.append("menus:swayctl-center" if key == "settings" else PROVIDERS[key][0])
        if "files" in enabled and v["files_in_results"]:
            default.append("files")
        prefixes = [(PROVIDERS[k][2], PROVIDERS[k][0]) for k in enabled if PROVIDERS[k][2]]
        prefixes.append((ALWAYS[2], ALWAYS[0]))
        hints = [f"{p} {k}" for p, k in (("/", "files"), ("=", "math"), ("@", "web"))
                 if (k == "files" and v["files"]) or (k == "math" and v["calc"]) or (k == "web" and v["websearch"])]
        lines = [
            "# generated by swayctl-center; edits are overwritten",
            f"theme = {_toml_str(THEME_NAME)}",
            "force_keyboard_focus = true",
            "close_when_open = true",
            "",
            "[placeholders]",
            f'"default" = {{ input = {_toml_str("Search" + (" · " + ", ".join(hints) if hints else ""))}, '
            f'list = "No results" }}',
            "",
            "[providers]",
            f"default = {_toml_list(default)}",
            f"empty = {_toml_list(['desktopapplications'] if v['apps'] else [])}",
            "max_results = 50",
        ]
        for prefix, provider in prefixes:
            lines += ["", "[[providers.prefixes]]", f"prefix = {_toml_str(prefix)}",
                      f"provider = {_toml_str(provider)}"]
        return "\n".join(lines) + "\n"

    def theme_css(self, ctx: Context) -> str:
        t = ctx.theme
        family, size = _font(ctx)
        return f"""/* generated by swayctl-center from the current theme; edits are overwritten */
@define-color window_bg_color {t.bg};
@define-color accent_bg_color {t.accent};
@define-color theme_fg_color {t.fg};
@define-color error_bg_color #c34043;
@define-color error_fg_color {t.fg};

* {{ all: unset; font-family: "{family}", sans-serif; font-weight: {_font_weight(ctx)}; font-size: {size}pt; }}
popover {{ background: @window_bg_color; border: 1px solid alpha(@theme_fg_color, 0.15);
  border-radius: 12px; padding: 8px; }}
.normal-icons {{ -gtk-icon-size: 16px; }}
.large-icons {{ -gtk-icon-size: 32px; }}
scrollbar {{ opacity: 0; }}
.box-wrapper {{ background: @window_bg_color; color: @theme_fg_color; padding: 16px; border-radius: 16px;
  border: 1px solid alpha(@accent_bg_color, 0.6); box-shadow: 0 14px 36px rgba(0, 0, 0, 0.35); }}
.search-container {{ border-radius: 10px; }}
.input {{ background: alpha(@theme_fg_color, 0.07); color: @theme_fg_color; caret-color: @accent_bg_color;
  padding: 10px 12px; border-radius: 10px; font-size: {size + 2}pt; }}
.input placeholder {{ color: alpha(@theme_fg_color, 0.45); }}
.input selection {{ background: alpha(@accent_bg_color, 0.4); }}
.content-container {{ margin-top: 10px; }}
.placeholder, .elephant-hint {{ color: alpha(@theme_fg_color, 0.55); padding: 12px; }}
.list {{ color: @theme_fg_color; }}
.item-box {{ padding: 8px 10px; border-radius: 10px; }}
child:selected .item-box, row:selected .item-box {{ background: alpha(@accent_bg_color, 0.28); }}
.item-image {{ margin-right: 10px; -gtk-icon-size: 26px; }}
.item-image-text {{ margin-right: 10px; font-size: 20px; }}
.item-text {{ font-weight: 600; }}
.item-subtext {{ font-size: {max(size - 2, 6)}pt; color: alpha(@theme_fg_color, 0.6); }}
.item-quick-activation {{ color: alpha(@theme_fg_color, 0.55); background: alpha(@theme_fg_color, 0.08);
  border-radius: 6px; padding: 2px 6px; margin-left: 8px; }}
.calc .item-text {{ font-size: {size + 6}pt; }}
.preview {{ border: 1px solid alpha(@theme_fg_color, 0.12); border-radius: 10px; padding: 10px;
  margin-left: 10px; color: @theme_fg_color; }}
.keybinds {{ padding-top: 10px; margin-top: 10px; border-top: 1px solid alpha(@theme_fg_color, 0.1);
  font-size: {max(size - 2, 6)}pt; color: alpha(@theme_fg_color, 0.55); }}
.keybind-button {{ padding: 2px 6px; border-radius: 6px; }}
.keybind-button:hover {{ background: alpha(@theme_fg_color, 0.08); }}
.keybind-bind {{ font-weight: 700; margin-right: 4px; }}
.error {{ background: @error_bg_color; color: @error_fg_color; padding: 10px; border-radius: 10px; }}
"""

    def settings_menu(self) -> str:
        from .keybindings import self_command
        me = self_command()
        lines = ["# generated by swayctl-center; edits are overwritten",
                 'name = "swayctl-center"', 'name_pretty = "Settings"', 'icon = "preferences-system"']
        for text, keywords, icon, args in SETTINGS_ENTRIES:
            lines += ["", "[[entries]]", f"text = {_toml_str(text)}",
                      f"keywords = {_toml_list(keywords.split())}", f"icon = {_toml_str(icon)}",
                      f"actions = {{ \"open\" = {_toml_str(f'{me} {args}')} }}"]
        return "\n".join(lines) + "\n"

    def files(self, v, ctx):
        name, url = ENGINES[v["search_engine"]]
        return {
            "walker/config.toml": self.walker_config(v),
            f"walker/themes/{THEME_NAME}/style.css": self.theme_css(ctx),
            "elephant/files.toml": "\n".join([
                "# generated by swayctl-center; edits are overwritten",
                f"search_dirs = {_toml_list([str(Path(d).expanduser()) for d in v['file_folders']])}",
                f"ignored_dirs = {_toml_list([str(Path(d).expanduser()) for d in v['file_excluded']])}",
                f"watch = {'true' if v['file_watch'] else 'false'}", ""]),
            "elephant/websearch.toml": "\n".join([
                "# generated by swayctl-center; edits are overwritten",
                "[[entries]]", "default = true", f"name = {_toml_str(name)}", f"url = {_toml_str(url)}", ""]),
            "elephant/desktopapplications.toml": "\n".join([
                "# generated by swayctl-center; edits are overwritten",
                f"show_actions = {'true' if v['app_actions'] else 'false'}",
                # each app in its own scope, not in elephant's unit (restarted on changes)
                'launch_prefix = "systemd-run --user --scope --collect --quiet"', ""]),
            "elephant/menus/swayctl-center.toml": self.settings_menu(),
        }

    def link_plugins(self, ctx: Context) -> bool:
        """Symlink installed provider plugins where elephant --config looks."""
        dest = self.root(ctx) / "elephant" / "providers"
        dest.mkdir(parents=True, exist_ok=True)
        changed = False
        wanted = {}
        for d in PLUGIN_DIRS[:1]:  # /usr/lib/elephant etc. are still searched by elephant itself
            if d.is_dir():
                wanted.update({p.name: p for p in d.rglob("*.so")})
        for link in dest.iterdir():
            if link.is_symlink() and link.name not in wanted:
                link.unlink()
                changed = True
        for name, target in wanted.items():
            link = dest / name
            if not (link.is_symlink() and link.resolve() == target.resolve()):
                if link.exists() or link.is_symlink():
                    link.unlink()
                link.symlink_to(target)
                changed = True
        return changed

    def apply_extra(self, section, v, changed, ctx=None):
        if v["managed"]:
            try:
                if self.link_plugins(ctx):
                    # new plugins only load when elephant starts
                    for suffix in ("elephant", "walker"):
                        if units.state(self.unit_name(suffix)).active:
                            units.restart(self.unit_name(suffix))
            except OSError as e:
                return [f"launcher: {e}"]
        return super().apply_extra(section, v, changed, ctx)

    def reload(self, unit):
        # walker has no config reload; elephant reads its config at start
        units.restart(unit)

    def status(self, v, ctx):
        s = super().status(v, ctx)
        s["missing_packages"] = self.missing_packages(v) if v["managed"] else []
        s["walker_installed"] = units.installed("walker")
        return s

    def import_current(self, ipc, config, ctx):
        return super().import_current(ipc, config, ctx)

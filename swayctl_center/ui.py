"""Settings window. A thin client of the daemon: every control calls Set over
D-Bus, and every page refreshes from the daemon's Changed signal, so the window
stays correct when settings change from the CLI, a file edit, or another window.

Simple sections are built straight from the schema; outputs, keyboard shortcuts
and startup applications get their own pages.
"""
from __future__ import annotations

import copy
import math
import os
from datetime import datetime
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from . import swayipc  # noqa: E402
from .i18n import _  # noqa: E402
from .client import CallError, Client, DaemonUnavailable  # noqa: E402
from .store import config_dir as store_config_dir  # noqa: E402
from .daemon import BUS_NAME, INTERFACE, OBJECT_PATH  # noqa: E402
from .modules.outputs import format_mode  # noqa: E402

APP_ID = "io.github.huyhappy.SwayctlCenter.Settings"

# How enum values read in dropdowns; anything missing is prettified.
CHOICE_LABELS: dict[str, dict[str, str]] = {
    "appearance.schedule": {"sun": "Sunrise and sunset", "custom": "At set times"},
    "auth.lock_screen": {"swaylock": "swaylock (password only)",
                         "swayctl-lock": "swayctl-lock (password and fingerprint at once)"},
    "bar.program": {"waybar": "Waybar", "swayctl-bar": "swayctl-bar (with Quick Settings)"},
    "appearance.style": {"classic": "Classic (flat bar, square corners)",
                         "modern": "Modern (floating bar, rounded)"},
    "keyremap.copilot": {"default": "Copilot (unchanged)", "super": "Super (Windows key)",
                         "rightcontrol": "Right Ctrl"},
    "night_light.mode": {"off": "Off", "always": "Always on", "sun": "Sunset to sunrise",
                         "custom": "At set times"},
    "location.source": {"timezone": "From the timezone", "manual": "Set by hand"},
    "layout.border_style": {"pixel": "Thin line", "normal": "With title bar", "none": "None"},
    "layout.smart_gaps": {"on": "Hide when only one window", "off": "Always show",
                          "inverse_outer": "Outer gaps only when alone"},
    "layout.focus_follows_mouse": {"yes": "Yes", "no": "No", "always": "Always (even over the same window)"},
    "layout.mouse_warping": {"output": "When moving between displays", "container": "Always",
                             "none": "Never"},
    "layout.focus_on_window_activation": {"smart": "Focus if visible, else mark urgent",
                                          "urgent": "Mark urgent", "focus": "Focus it", "none": "Ignore"},
    "input.touchpad.tap_button_map": {"lrm": "2 fingers right, 3 fingers middle",
                                      "lmr": "2 fingers middle, 3 fingers right"},
    "input.touchpad.click_method": {"button_areas": "Bottom corners", "clickfinger": "Number of fingers",
                                    "none": "Off"},
    "input.touchpad.events": {"enabled": "On", "disabled": "Off",
                              "disabled_on_external_mouse": "Off while a mouse is plugged in"},
    "keybindings.modifier": {"Mod4": "Super (Windows key)", "Mod1": "Alt", "Control": "Ctrl"},
    "idle.lock_background": {"color": "Theme color", "wallpaper": "Wallpaper"},
    "notifications.image_visibility": {"when-available": "When available"},
    "launcher.search_engine": {"google": "Google", "duckduckgo": "DuckDuckGo", "bing": "Bing",
                               "brave": "Brave Search", "startpage": "Startpage", "youtube": "YouTube"},
}


def choice_label(path: str, value: str) -> str:
    label = CHOICE_LABELS.get(path, {}).get(value)
    if label:
        return _(label)
    text = value.replace("_", " ").replace("-", " ")
    return _(text[:1].upper() + text[1:])


# Sections of a page, in order; keys not listed go at the end.
GROUPS: dict[str, list[tuple[str, list[str]]]] = {
    "layout": [("", ["border_style", "border", "gaps_inner", "gaps_outer", "focus_follows_mouse"]),
               ("Advanced", ["floating_border", "hide_edge_borders", "smart_gaps", "mouse_warping",
                             "focus_on_window_activation", "workspace_auto_back_and_forth"])],
    "input.keyboard": [("Layout", ["xkb_layout", "xkb_variant", "xkb_options"]),
                       ("Typing", ["repeat_delay", "repeat_rate"])],
    "bar": [("", ["position", "height", "theme"]),
            ("Modules", ["modules_left", "modules_center", "modules_right"]),
            ("", ["clock_format"])],
    "effects": [("", ["corner_radius", "dim_inactive", "glass"]),
                ("Liquid glass", ["glass_refraction", "glass_thickness", "glass_edge",
                                  "glass_blur", "glass_opacity",
                                  "glass_highlight", "glass_chroma"])],
    "notifications": [("", ["dnd_on_start", "position_x", "position_y", "timeout"]),
                      ("Advanced", ["output", "width", "max_visible", "timeout_low", "timeout_critical"])],
    "launcher": [("Show in results", ["apps", "settings", "calc", "files", "websearch"]),
                 ("", ["search_engine"]),
                 ("~Where to look for files", ["file_folders", "file_excluded", "file_watch", "files_in_results"]),
                 ("Advanced", ["symbols", "windows", "runner", "app_actions"])],
    "idle": [("", ["lock_after", "screen_off_after", "suspend_after", "lock_before_sleep"]),
             ("Advanced", ["lock_background", "show_failed_attempts", "ignore_empty_password"])],
}

# number settings shown as a slider between two words
SLIDERS = {
    "scrolling.touchpad_speed": ("Slow", "Fast"), "scrolling.mouse_speed": ("Slow", "Fast"),
    "scrolling.touchpad_glide": ("Short", "Long"), "scrolling.mouse_glide": ("Short", "Long"),
    "input.touchpad.pointer_accel": ("Slow", "Fast"), "input.pointer.pointer_accel": ("Slow", "Fast"),
    "input.touchpad.scroll_factor": ("Slow", "Fast"), "input.pointer.scroll_factor": ("Slow", "Fast"),
    "effects.glass_refraction": ("Flat", "Bend"), "effects.glass_blur": ("Clear", "Frosted"),
    "effects.glass_opacity": ("Clear", "Opaque"), "effects.glass_highlight": ("Matte", "Shiny"),
    "effects.glass_edge": ("Thin", "Thick"), "effects.glass_chroma": ("None", "Rainbow"),
    "effects.glass_thickness": ("Thin", "Thick"),
}


def slider_out(key_type: str, raw: float) -> int | float:
    """What a slider sends to the daemon: Gtk.Scale is always float, so int
    settings (glass_opacity, glass_refraction...) must be whole numbers."""
    return int(round(raw)) if key_type == "int" else round(raw, 3)

# seconds, picked from a list
DURATION_KEYS = {"idle.lock_after", "idle.screen_off_after", "idle.suspend_after"}
DURATIONS = [0, 60, 120, 180, 300, 600, 900, 1200, 1800, 2700, 3600, 7200]


def _duration_label(secs: int) -> str:
    if secs == 0:
        return "Never"
    if secs % 3600 == 0:
        h = secs // 3600
        return f"{h} hour" + ("s" if h > 1 else "")
    if secs % 60 == 0:
        m = secs // 60
        return f"{m} minute" + ("s" if m > 1 else "")
    return f"{secs} seconds"


FONT_KEYS = {"font.family", "font.monospace_family"}

# "str" keys holding a monitor name, picked from the connected ones; the label is for "".
OUTPUT_PICKERS = {"notifications.output": "Focused monitor"}


def _output_names() -> list[str]:
    try:
        return [o["name"] for o in swayipc.Connection().get_outputs()]
    except (swayipc.IPCError, OSError):
        return []


PLACEHOLDERS = {
    "background.color": "Theme color",
    "bar.theme": "Same as the desktop",
}

# Sidebar: groups of pages. "system:*" pages talk to system services directly
# and work without the daemon; "app:system" is the System page.
NAV = [
    ("Connections", [("system:network", "Wi-Fi & Network", "network-wireless-symbolic"),
                     ("system:bluetooth", "Bluetooth", "bluetooth-symbolic")]),
    ("Devices", [("displays", "Displays", "video-display-symbolic"),
                 ("system:sound", "Sound", "audio-volume-high-symbolic"),
                 ("keyboard", "Keyboard", "input-keyboard-symbolic"),
                 ("pointing", "Mouse & Touchpad", "input-mouse-symbolic"),
                 ("power", "Power & Lock", "battery-good-symbolic")]),
    ("Personalize", [("appearance", "Appearance", "preferences-desktop-appearance-symbolic"),
                     ("desktop", "Desktop", "view-grid-symbolic"),
                     ("notifications", "Notifications", "preferences-system-notifications-symbolic"),
                     ("search", "Search", "system-search-symbolic")]),
    ("System", [("app:system", "System", "preferences-system-symbolic")]),
]

# What each combined page shows, top to bottom: (section, sub-heading). An empty
# heading means the part needs none (the page title says it).
PAGES = {
    "displays": [("outputs", ""), ("night_light", "Night Light")],
    "keyboard": [("input.keyboard", ""), ("keyremap", "Swap & remap keys"), ("input_method", "Typing other languages"),
                 ("keybindings", "Shortcuts")],
    "power": [("system:power", ""), ("idle", "Lock & Idle"), ("auth", "Fingerprint")],
    "appearance": [("appearance", ""), ("background", "Wallpaper"), ("font", "Fonts"),
                   ("theming", "Other apps"), ("location", "Location")],
    "desktop": [("layout", "Windows"), ("effects", "Effects"), ("bar", "Bar")],
    "notifications": [("notifications", "")],
    "search": [("launcher", "Launcher"), ("clipboard", "Clipboard")],
}

# old page ids (--page, the launcher's Settings menu) and sections -> page
SECTION_PAGE = {sec: page for page, parts in PAGES.items() for sec, _t in parts}
SECTION_PAGE.update({"input.touchpad": "pointing", "input.pointer": "pointing", "scrolling": "pointing",
                     "autostart": "app:system", "system:power": "power"})

# extra words people search for, besides every setting's label on the page
PAGE_KEYWORDS = {
    "system:network": "wifi internet vpn ethernet", "system:bluetooth": "headphones pair",
    "system:sound": "volume audio speaker microphone", "power": "battery brightness sleep suspend idle lock",
    "displays": "monitor screen resolution scale night light", "keyboard": "layout shortcuts keys fcitx typing keyd swap remap capslock",
    "pointing": "touchpad mouse scroll trackpad", "appearance": "theme dark light wallpaper font color",
    "desktop": "windows gaps borders bar waybar", "notifications": "swaync do not disturb",
    "search": "launcher walker clipboard history", "app:system": "backup startup components checks",
}


def _system_page(name: str) -> Gtk.Widget:
    if name == "network":
        from .pages.network import NetworkPage
        return NetworkPage()
    if name == "bluetooth":
        from .pages.bluetooth import BluetoothPage
        return BluetoothPage()
    if name == "sound":
        from .pages.sound import SoundPage
        return SoundPage()
    from .pages.power import PowerPage
    return PowerPage()

SPIN_DEBOUNCE_MS = 400

CSS = """
.title-2 { font-size: 1.5em; font-weight: 800; }
.caption { font-size: 0.85em; }
.monospace { font-family: monospace; }
.error { background: alpha(@error_color, 0.15); }
.error label { color: @error_color; }
.status { margin-bottom: 4px; }
.heading { font-weight: 700; margin-top: 6px; }
.title-3 { font-size: 1.2em; font-weight: 700; }
.nav-group { font-size: 0.8em; font-weight: 700; opacity: 0.6; }
.chip { border: 1px solid alpha(currentColor, 0.25); border-radius: 6px; }
"""


def _frame(child: Gtk.Widget) -> Gtk.Frame:
    frame = Gtk.Frame()
    frame.set_child(child)
    return frame


def _list_box() -> Gtk.ListBox:
    box = Gtk.ListBox()
    box.set_selection_mode(Gtk.SelectionMode.NONE)
    box.add_css_class("rich-list")
    return box


def _row(title: str, control: Gtk.Widget, subtitle: str | None = None) -> Gtk.Box:
    row = Gtk.Box(spacing=12)
    labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
    label = Gtk.Label(label=title, xalign=0)
    labels.append(label)
    if subtitle:
        sub = Gtk.Label(label=subtitle, xalign=0, wrap=True, max_width_chars=70)
        sub.add_css_class("dim-label")
        sub.add_css_class("caption")
        labels.append(sub)
    row.append(labels)
    control.set_valign(Gtk.Align.CENTER)
    row.append(control)
    return row


def _heading(text: str) -> Gtk.Label:
    label = Gtk.Label(label=_(text), xalign=0)
    label.add_css_class("title-2")
    return label


class Page(Gtk.Box):
    def __init__(self, win: "SettingsWindow", section: str, title: str | None, compact: bool = False):
        margin = 0 if compact else 18
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                         margin_top=margin, margin_bottom=margin, margin_start=margin, margin_end=margin)
        self.win, self.section = win, section
        if title:
            self.append(_heading(title))
        self.updating = False

    def update(self, values: dict[str, Any]) -> None:
        raise NotImplementedError

    def update_status(self, status: dict[str, Any]) -> None:
        pass


_PANE_NAMES = {"frame", "headerbar", "entry", "spinbutton", "dropdown", "searchentry", "toast", "switch"}
_CHIP_CLASSES = ("title-1", "title-2", "title-3", "title-4", "heading", "status", "dim-label")


def _is_glass_pane(w: Gtk.Widget) -> bool:
    """A pane of glass in the settings window (as app_glass_css draws them):
    tagged light/dark as a whole, its contents follow."""
    name = w.get_css_name()
    if name in _PANE_NAMES:
        return True
    parent = w.get_parent()
    if name == "row" and w.has_css_class("nav-header"):
        return False  # the sidebar's group names: only their label is a chip
    if name == "row" and parent is not None and parent.get_css_name() == "list":
        # sidebar entries and rows of unframed lists are pills; framed ones are the frame's
        return not parent.has_css_class("boxed-list") and not _inside(parent, "frame")
    if name == "button":
        return not w.has_css_class("flat") and not _inside(w, "frame", "row", "headerbar")
    if name == "label":
        if _inside(w, "frame", "row", "button", "headerbar", "list", "entry", "spinbutton"):
            return False
        return any(w.has_css_class(c) for c in _CHIP_CLASSES) or (parent is not None and parent.get_css_name() == "box")
    if name == "expander-widget":
        return True
    return False


def _inside(w: Gtk.Widget, *names: str) -> bool:
    p = w.get_parent()
    while p is not None:
        if p.get_css_name() in names:
            return True
        p = p.get_parent()
    return False


def _status_label() -> Gtk.Label:
    label = Gtk.Label(xalign=0, wrap=True)
    label.add_css_class("status")
    return label


def _fmt_time(iso: str | None) -> str:
    if not iso:
        return ""
    dt = datetime.fromisoformat(iso)
    today = datetime.now().astimezone().date()
    day = "" if dt.date() == today else (" tomorrow" if (dt.date() - today).days == 1 else f" {dt:%a %d %b}")
    return f"{dt:%H:%M}{day}"


# --- schema-driven rows ----------------------------------------------------

class SettingRow(Gtk.ListBoxRow):
    """One scalar setting: label, a control matching its type, and a reset button."""

    def __init__(self, page: Page, key: dict[str, Any]):
        super().__init__(activatable=False)
        self.page, self.key = page, key
        self.path = f"{key['section']}.{key['name']}"
        self.current: Any = None
        self._spin_timer = 0
        self.control = self._build_control()
        self.reset_btn = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Reset to default")
        self.reset_btn.add_css_class("flat")
        self.reset_btn.connect("clicked", lambda _b: page.win.reset(self.path))
        box = Gtk.Box(spacing=6)
        box.append(self.control)
        box.append(self.reset_btn)
        self.set_child(_row(key["label"], box, key.get("help")))

    def _build_control(self) -> Gtk.Widget:
        t = self.key["type"]
        if t == "bool":
            w = Gtk.Switch()
            w.connect("notify::active", lambda s, _p: self._changed(s.get_active()))
        elif t in ("int", "float"):
            lo = self.key.get("min", -1e6)
            hi = self.key.get("max", 1e6)
            step = (100 if hi - lo > 1000 else 1) if t == "int" else 0.05
            w = Gtk.SpinButton.new_with_range(lo, hi, step)
            w.set_digits(0 if t == "int" else 2)
            w.connect("value-changed", self._spin_changed)
        elif t == "enum":
            w = Gtk.DropDown.new_from_strings([choice_label(self.path, c) for c in self.key["choices"]])
            w.connect("notify::selected", lambda d, _p: self._changed(self.key["choices"][d.get_selected()]))
        elif self.path in OUTPUT_PICKERS:
            # "" first (the focused monitor), then the connected ones by connector name
            self._outputs = [""] + _output_names()
            w = Gtk.DropDown.new_from_strings([OUTPUT_PICKERS[self.path]] + self._outputs[1:])
            w.connect("notify::selected", lambda d, _p: self._changed(self._outputs[d.get_selected()]))
        else:  # str
            w = Gtk.Entry(width_chars=24, placeholder_text=_(PLACEHOLDERS.get(self.path, "")))
            w.connect("activate", lambda e: self._changed(e.get_text()))
            focus = Gtk.EventControllerFocus()
            focus.connect("leave", lambda _c: self._changed(w.get_text()))
            w.add_controller(focus)
        return w

    def _spin_changed(self, spin: Gtk.SpinButton) -> None:
        if self.page.updating:
            return
        if self._spin_timer:
            GLib.source_remove(self._spin_timer)

        def fire():
            self._spin_timer = 0
            value = spin.get_value()
            self._changed(int(value) if self.key["type"] == "int" else round(value, 2))
            return GLib.SOURCE_REMOVE
        self._spin_timer = GLib.timeout_add(SPIN_DEBOUNCE_MS, fire)

    def _changed(self, value: Any) -> None:
        if self.page.updating or value == self.current:
            return
        self.page.win.set(self.path, value)

    def set_value(self, value: Any) -> None:
        self.current = value
        w, t = self.control, self.key["type"]
        if t == "bool":
            w.set_active(bool(value))
        elif t in ("int", "float"):
            w.set_value(value)
        elif t == "enum":
            w.set_selected(self.key["choices"].index(value))
        elif self.path in OUTPUT_PICKERS:
            if value not in self._outputs:  # saved monitor isn't plugged in right now
                self._outputs.append(value)
                w.get_model().append(value)
            w.set_selected(self._outputs.index(value))
        elif w.get_text() != value:
            w.set_text(value)
        is_default = value == self.key["default"]
        self.reset_btn.set_opacity(0 if is_default else 1)
        self.reset_btn.set_sensitive(not is_default)


class TextListRow(Gtk.ListBoxRow):
    """A list of plain strings edited as comma-separated text."""

    def __init__(self, page: Page, key: dict[str, Any]):
        super().__init__(activatable=False)
        self.page, self.key = page, key
        self.path = f"{key['section']}.{key['name']}"
        self.current: list[str] = []
        self.entry = Gtk.Entry(hexpand=True)
        if key.get("choices_hint"):
            self.entry.set_tooltip_text("Available: " + ", ".join(key["choices_hint"]))
        self.entry.connect("activate", lambda _e: self._changed())
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda _c: self._changed())
        self.entry.add_controller(focus)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.append(Gtk.Label(label=key["label"], xalign=0))
        box.append(self.entry)
        self.set_child(box)

    def _changed(self) -> None:
        items = [x.strip() for x in self.entry.get_text().split(",") if x.strip()]
        if not self.page.updating and items != self.current:
            self.page.win.set(self.path, items)

    def set_value(self, value: list[str]) -> None:
        self.current = list(value)
        text = ", ".join(value)
        if self.entry.get_text() != text:
            self.entry.set_text(text)


def _reset_button(page: Page, path: str) -> Gtk.Button:
    b = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Reset to default")
    b.add_css_class("flat")
    b.connect("clicked", lambda _b: page.win.reset(path))
    return b


def _show_reset(button: Gtk.Button, is_default: bool) -> None:
    button.set_opacity(0 if is_default else 1)
    button.set_sensitive(not is_default)


class DurationRow(Gtk.ListBoxRow):
    """A time in seconds, chosen from a list (Never, 1 minute, ...)."""

    def __init__(self, page: Page, key: dict[str, Any]):
        super().__init__(activatable=False)
        self.page, self.key = page, key
        self.path = f"{key['section']}.{key['name']}"
        self.current: int | None = None
        self.choices = [d for d in DURATIONS if d <= key.get("max", 86400)]
        self.model = Gtk.StringList()
        self.dropdown = Gtk.DropDown(model=self.model, valign=Gtk.Align.CENTER)
        self.dropdown.connect("notify::selected", self._changed)
        self.set_child(_row(key["label"].split(" (")[0], self.dropdown, key.get("help")))

    def _changed(self, dd, _p) -> None:
        i = dd.get_selected()
        if not self.page.updating and i < len(self.choices) and self.choices[i] != self.current:
            self.page.win.set(self.path, self.choices[i])

    def set_value(self, value: int) -> None:
        self.current = value
        choices = sorted(set(DURATIONS) | {value}) if value not in DURATIONS else list(self.choices)
        if choices != self.choices or self.model.get_n_items() == 0:
            self.choices = choices
            self.model.splice(0, self.model.get_n_items(), [_duration_label(c) for c in choices])
        self.dropdown.set_selected(self.choices.index(value))


class SliderRow(Gtk.ListBoxRow):
    """A number as a slider with words at both ends (e.g. Slow ... Fast)."""

    def __init__(self, page: Page, key: dict[str, Any], low: str, high: str):
        super().__init__(activatable=False)
        self.page, self.key = page, key
        self.path = f"{key['section']}.{key['name']}"
        self.current: float | None = None
        self._timer = 0
        lo, hi = key.get("min", 0.0), key.get("max", 1.0)
        step = 1.0 if key["type"] == "int" else (hi - lo) / 100
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.set_size_request(220, -1)
        self.scale.add_mark(key["default"], Gtk.PositionType.BOTTOM, None)  # where "default" is
        self.scale.connect("value-changed", self._moved)
        self.reset_btn = _reset_button(page, self.path)
        box = Gtk.Box(spacing=8)
        for w in (Gtk.Label(label=low), self.scale, Gtk.Label(label=high), self.reset_btn):
            if isinstance(w, Gtk.Label):
                w.add_css_class("dim-label")
                w.add_css_class("caption")
            box.append(w)
        self.set_child(_row(key["label"], box, key.get("help")))

    def _moved(self, scale) -> None:
        if self.page.updating:
            return
        if self._timer:
            GLib.source_remove(self._timer)

        def fire():
            self._timer = 0
            value = slider_out(self.key["type"], scale.get_value())
            if value != self.current:
                self.page.win.set(self.path, value)
            return GLib.SOURCE_REMOVE
        self._timer = GLib.timeout_add(250, fire)

    def set_value(self, value: float) -> None:
        self.current = value
        self.scale.set_value(value)
        _show_reset(self.reset_btn, abs(value - self.key["default"]) < 1e-6)


class FontRow(Gtk.ListBoxRow):
    """A font family, picked from the installed fonts."""

    def __init__(self, page: Page, key: dict[str, Any]):
        super().__init__(activatable=False)
        self.page, self.key = page, key
        self.path = f"{key['section']}.{key['name']}"
        self.current = ""
        self.button = Gtk.FontDialogButton(dialog=Gtk.FontDialog(title=key["label"]),
                                           level=Gtk.FontLevel.FAMILY, use_font=True)
        self.button.connect("notify::font-desc", self._changed)
        self.reset_btn = _reset_button(page, self.path)
        box = Gtk.Box(spacing=6)
        box.append(self.button)
        box.append(self.reset_btn)
        self.set_child(_row(key["label"], box, key.get("help")))

    def _changed(self, button, _p) -> None:
        desc = button.get_font_desc()
        family = desc.get_family() if desc else None
        if not self.page.updating and family and family != self.current:
            self.page.win.set(self.path, family)

    def set_value(self, value: str) -> None:
        self.current = value
        desc = Pango.FontDescription()
        desc.set_family(value)  # not from_string: "Inter SemiBold" is a family name here
        self.button.set_font_desc(desc)
        _show_reset(self.reset_btn, value == self.key["default"])


# what each swayctl-bar module is, in the module pickers
MODULE_LABELS = {
    "workspaces": "Workspaces", "mode": "Sway mode (resize…)", "window": "Window title",
    "clock": "Clock", "tray": "Tray (app icons)", "status": "Quick Settings (Wi-Fi, sound, battery…)",
}


class ModulesRow(Gtk.ListBoxRow):
    """An ordered list of bar modules: move, remove, add from swayctl-bar's modules."""

    def __init__(self, page: Page, key: dict[str, Any]):
        super().__init__(activatable=False)
        self.page, self.key = page, key
        self.path = f"{key['section']}.{key['name']}"
        self.current: list[str] = []
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        head = Gtk.Box(spacing=6)
        title = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        title.append(Gtk.Label(label=key["label"], xalign=0))
        if key.get("help"):
            sub = Gtk.Label(label=key["help"], xalign=0, wrap=True)
            sub.add_css_class("dim-label")
            sub.add_css_class("caption")
            title.append(sub)
        head.append(title)
        self.pick = Gtk.DropDown.new_from_strings([_("Add a module…")])
        self.pick.connect("notify::selected", self._picked)
        head.append(self.pick)
        self.reset_btn = _reset_button(page, self.path)
        head.append(self.reset_btn)
        outer.append(head)
        self.chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=6, row_spacing=6,
                                 max_children_per_line=20)
        outer.append(self.chips)
        self.catalog: list[str] = []
        self.set_child(outer)

    def _refresh_catalog(self) -> None:
        """Only modules not on this side yet."""
        self.catalog = [m for m in self.key.get("choices_hint", []) if m not in self.current]
        self.pick.set_model(Gtk.StringList.new([_("Add a module…")] + [_(MODULE_LABELS.get(m, m))
                                                                        for m in self.catalog]))
        self.pick.set_selected(0)
        self.pick.set_sensitive(bool(self.catalog))

    def _save(self, items: list[str]) -> None:
        if not self.page.updating and items != self.current:
            self.page.win.set(self.path, items)

    def _picked(self, dd, _p) -> None:
        i = dd.get_selected()
        if 0 < i <= len(self.catalog) and not self.page.updating:
            self._add(self.catalog[i - 1])

    def _add(self, name: str) -> None:
        if name and name not in self.current:
            self._save(self.current + [name])

    def _move(self, i: int, delta: int) -> None:
        j = i + delta
        if 0 <= j < len(self.current):
            items = list(self.current)
            items[i], items[j] = items[j], items[i]
            self._save(items)

    def set_value(self, value: list[str]) -> None:
        self.current = list(value)
        self.chips.remove_all()
        for i, name in enumerate(value):
            chip = Gtk.Box(spacing=0)
            chip.add_css_class("chip")
            for icon, tip, cb in (("go-previous-symbolic", _("Move left"), lambda _b, i=i: self._move(i, -1)),):
                b = Gtk.Button(icon_name=icon, tooltip_text=tip)
                b.add_css_class("flat")
                b.set_sensitive(i > 0)
                b.connect("clicked", cb)
                chip.append(b)
            chip.append(Gtk.Label(label=_(MODULE_LABELS.get(name, name)), margin_start=4, margin_end=4))
            nxt = Gtk.Button(icon_name="go-next-symbolic", tooltip_text=_("Move right"))
            nxt.add_css_class("flat")
            nxt.set_sensitive(i < len(value) - 1)
            nxt.connect("clicked", lambda _b, i=i: self._move(i, 1))
            chip.append(nxt)
            rm = Gtk.Button(icon_name="window-close-symbolic", tooltip_text=_("Remove"))
            rm.add_css_class("flat")
            rm.connect("clicked", lambda _b, n=name: self._save([x for x in self.current if x != n]))
            chip.append(rm)
            self.chips.append(chip)
        if not value:
            empty = Gtk.Label(label=_("(empty)"))
            empty.add_css_class("dim-label")
            self.chips.append(empty)
        self._refresh_catalog()
        _show_reset(self.reset_btn, value == self.key["default"])


class FolderListRow(Gtk.ListBoxRow):
    """A list of folders, added with a folder chooser."""

    def __init__(self, page: Page, key: dict[str, Any]):
        super().__init__(activatable=False)
        self.page, self.key = page, key
        self.path = f"{key['section']}.{key['name']}"
        self.current: list[str] = []
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        head = Gtk.Box(spacing=6)
        head.append(Gtk.Label(label=key["label"], xalign=0, hexpand=True))
        add = Gtk.Button(label="Add folder…")
        add.connect("clicked", self._choose)
        head.append(add)
        self.reset_btn = _reset_button(page, self.path)
        head.append(self.reset_btn)
        outer.append(head)
        self.items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        outer.append(self.items)
        self.set_child(outer)

    def _choose(self, _b) -> None:
        dialog = Gtk.FileDialog(title=self.key["label"], initial_folder=Gio.File.new_for_path(str(Path.home())))

        def done(d, result):
            try:
                f = d.select_folder_finish(result)
            except GLib.Error:
                return
            path, home = f.get_path(), str(Path.home())
            path = "~" + path[len(home):] if path == home or path.startswith(home + "/") else path
            if path not in self.current:
                self.page.win.set(self.path, self.current + [path])
        dialog.select_folder(self.page.win, None, done)

    def set_value(self, value: list[str]) -> None:
        self.current = list(value)
        child = self.items.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.items.remove(child)
            child = nxt
        for folder in value:
            row = Gtk.Box(spacing=6)
            shown = "Home folder" if folder == "~" else folder
            row.append(Gtk.Label(label=shown, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE))
            rm = Gtk.Button(icon_name="window-close-symbolic", tooltip_text="Remove")
            rm.add_css_class("flat")
            rm.connect("clicked", lambda _b, f=folder: self.page.win.set(
                self.path, [x for x in self.current if x != f]))
            row.append(rm)
            self.items.append(row)
        if not value:
            none = Gtk.Label(label="None", xalign=0)
            none.add_css_class("dim-label")
            self.items.append(none)
        _show_reset(self.reset_btn, value == self.key["default"])


class SchemaPage(Page):
    # {key name: predicate(section values)} - rows hidden when not relevant
    visible_when: dict[str, Callable[[dict[str, Any]], bool]] = {}

    def __init__(self, win, section, title, keys: list[dict[str, Any]],
                 groups: list[tuple[str, list[str]]] | None = None, compact: bool = False):
        super().__init__(win, section, title, compact)
        self.status = _status_label()
        self.status.set_visible(False)
        self.append(self.status)
        self.rows: dict[str, SettingRow] = {}
        shown = {k["name"]: k for k in keys
                 if not k.get("hidden") and k["type"] != "map"
                 and not (k["type"] == "list" and k.get("item_type") not in ("str", "folder"))}
        if groups is None:
            groups = [(t, [n for n in names if n in shown]) for t, names in GROUPS.get(section, [])]
            grouped = {n for _t, names in groups for n in names}
            rest = [n for n in shown if n not in grouped]
            if rest:
                groups.append(("", rest) if not groups else ("Other", rest))
        else:  # exactly these keys (a piece of a combined page)
            groups = [(t, [n for n in names if n in shown]) for t, names in groups]
        self.groups: list[tuple[Gtk.Widget, list[str]]] = []
        for title_, names in groups:
            if not names:
                continue
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            lb = _list_box()
            for name in names:
                key = shown[name]
                row = self.make_row(key)
                self.rows[name] = row
                lb.append(row)
            if title_ == "Advanced" or title_.startswith("~"):
                # rarely needed: out of the way until asked for
                exp = Gtk.Expander(label=_(title_.lstrip("~")), child=_frame(lb))
                exp.add_css_class("heading")
                box.append(exp)
            else:
                if title_:
                    h = Gtk.Label(label=_(title_), xalign=0)
                    h.add_css_class("heading")
                    box.append(h)
                box.append(_frame(lb))
            self.append(box)
            self.groups.append((box, names))

    def make_row(self, key: dict[str, Any]) -> Gtk.ListBoxRow:
        path = f"{key['section']}.{key['name']}"
        if key["type"] == "list":
            if key.get("item_type") == "folder":
                return FolderListRow(self, key)
            return ModulesRow(self, key) if key.get("choices_hint") else TextListRow(self, key)
        if path in FONT_KEYS:
            return FontRow(self, key)
        if path in SLIDERS:
            return SliderRow(self, key, *SLIDERS[path])
        if path in DURATION_KEYS:
            return DurationRow(self, key)
        return SettingRow(self, key)

    def update(self, values: dict[str, Any]) -> None:
        self.updating = True
        try:
            for name, row in self.rows.items():
                row.set_value(values[name])
                if name in self.visible_when:
                    row.set_visible(self.visible_when[name](values))
            for box, names in self.groups:  # hide a group when all its rows are hidden
                box.set_visible(any(self.rows[n].get_visible() for n in names))
        finally:
            self.updating = False


# --- appearance, night light, location ---------------------------------------

class ThemeRow(Gtk.ListBoxRow):
    """A theme name picked from the themes the daemon knows (built-in + user)."""

    def __init__(self, page: Page, key: dict[str, Any], empty_label: str | None = None):
        super().__init__(activatable=False)
        self.page, self.key = page, key
        self.path = f"{key['section']}.{key['name']}"
        self.empty_label = empty_label  # offer "" (e.g. "Same as the desktop") first
        self.names: list[str] = []
        self.current: str | None = None
        self.model = Gtk.StringList()
        self.dropdown = Gtk.DropDown(model=self.model)
        self.dropdown.connect("notify::selected", self._changed)
        self.set_child(_row(key["label"], self.dropdown, key.get("help")))

    def set_names(self, names: list[str]) -> None:
        if self.empty_label is not None:
            names = [""] + names
        if names == self.names:
            return
        self.page.updating = True
        try:
            self.names = names
            self.model.splice(0, self.model.get_n_items(), [n or self.empty_label for n in names])
            self.set_value(self.current)
        finally:
            self.page.updating = False

    def _changed(self, dd, _p) -> None:
        i = dd.get_selected()
        if self.page.updating or i >= len(self.names) or self.names[i] == self.current:
            return
        self.page.win.set(self.path, self.names[i])

    def set_value(self, value: str | None) -> None:
        self.current = value
        if value in self.names:
            self.dropdown.set_selected(self.names.index(value))


class AppearancePage(SchemaPage):
    visible_when = {
        "schedule": lambda v: v["mode"] == "auto",
        "light_at": lambda v: v["mode"] == "auto" and v["schedule"] == "custom",
        "dark_at": lambda v: v["mode"] == "auto" and v["schedule"] == "custom",
        "light_theme": lambda v: v["mode"] != "dark",
        "dark_theme": lambda v: v["mode"] != "light",
    }

    def __init__(self, win, section, title, keys):
        super().__init__(win, section, title, keys)
        toggle = Gtk.Button(label=_("Switch light/dark now"), halign=Gtk.Align.START)
        toggle.connect("clicked", lambda _b: win.action("theme.toggle"))
        modern = Gtk.Button(label=_("Use the modern look"), halign=Gtk.Align.START,
                            tooltip_text="Liquid glass, floating rounded bar, gaps between windows")
        modern.connect("clicked", lambda _b: win.action("preset.modern"))
        buttons = Gtk.Box(spacing=8)
        buttons.append(toggle)
        buttons.append(modern)
        self.insert_child_after(buttons, self.status)
        self.swatches = Gtk.Box(spacing=0, halign=Gtk.Align.START)
        self.insert_child_after(self.swatches, self.get_first_child())

    def make_row(self, key):
        return ThemeRow(self, key) if key["name"] in ("light_theme", "dark_theme") else SettingRow(self, key)

    def update_status(self, status):
        a = status["appearance"]
        t = a["theme"]
        names = [x["name"] for x in a["themes"]]
        for name in ("light_theme", "dark_theme"):
            if name in self.rows:  # hidden: only "light" and "dark" are left
                self.rows[name].set_names(names)
        when = {"fixed": "always", "override": "switched by hand until", "schedule": "until"}[a["source"]]
        name = t["name"].capitalize() if t["name"] == a["variant"] else f"{t['name']} ({a['variant']})"
        text = f"Now using {name}, {when}"
        if a["source"] != "fixed" and a["next_change"]:
            text += f" {_fmt_time(a['next_change'])}"
        if a["missing_theme"]:
            text += f". Theme “{a['missing_theme']}” was not found."
        self.status.set_label(text)
        self.status.set_visible(True)
        child = self.swatches.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.swatches.remove(child)
            child = nxt
        for role in ("bg", "fg", "accent", "muted"):
            sw = Gtk.Label(label="  ", tooltip_text=f"{role} {t[role]}")
            sw.add_css_class(f"swatch-{role}")
            self.swatches.append(sw)
        self.win.set_swatch_colors(t, status)


class NightLightPage(SchemaPage):
    visible_when = {
        "start": lambda v: v["mode"] == "custom",
        "end": lambda v: v["mode"] == "custom",
        "temperature": lambda v: v["mode"] != "off",
    }

    def update_status(self, status):
        n = status["night_light"]
        if n["foreign_pids"]:
            text = ("Another wlsunset is already running (pid "
                    f"{', '.join(map(str, n['foreign_pids']))}), probably started by your sway config. "
                    "Stop it to control the night light from here.")
        else:
            text = "Active" if n["running"] else "Off"
        err = status["errors"].get("night_light")
        if err and not n["foreign_pids"]:
            text += " — " + err[0]
        self.status.set_label(text)
        self.status.set_visible(True)


class EffectsPage(SchemaPage):
    visible_when = {
        "glass_refraction": lambda v: v["glass"],
        "glass_thickness": lambda v: v["glass"],
        "glass_opacity": lambda v: v["glass"],
        "glass_blur": lambda v: v["glass"],
        "glass_highlight": lambda v: v["glass"],
        "glass_edge": lambda v: v["glass"],
        "glass_chroma": lambda v: v["glass"],
    }

    def update_status(self, status):
        c = status.get("compositor") or {}
        if c.get("swayfx"):
            text = "Running on SwayFX — changes apply right away."
        else:
            text = ("These need the SwayFX compositor: log out and pick “Sway (swayctl-fx)”. "
                    "Settings are kept and apply there; plain sway ignores them.")
        self.status.set_label(text)
        self.status.set_visible(True)


class AuthPage(SchemaPage):
    """Fingerprint (fprintd) unlock: whether there's a reader, installing and
    enrolling (in a terminal, they ask questions), and writing PAM on request
    (pkexec) - never on its own."""

    def __init__(self, win, section, title, keys):
        super().__init__(win, section, title, keys)
        self.state: dict[str, Any] = {}
        self.visible_when = {}
        for name in self.rows:
            if name.startswith("fingerprint_"):
                self.visible_when[name] = lambda v: bool(self.state.get("fingerprint", {}).get("hardware"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                      margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        self.info = Gtk.Label(xalign=0, wrap=True)
        buttons = Gtk.Box(spacing=8)
        self.btn = {}
        for key, label in (("install", _("Install…")), ("fingerprint", _("Add a fingerprint…")),
                           ("apply", _("Apply")), ("restore", _("Undo all changes"))):
            b = Gtk.Button(label=label)
            b.connect("clicked", getattr(self, f"_{key}"))
            self.btn[key] = b
            buttons.append(b)
        self.btn["apply"].add_css_class("suggested-action")
        self.note = Gtk.Label(xalign=0, wrap=True, label=_(
            "Your password always keeps working: the fingerprint is only tried before it."))
        self.note.add_css_class("dim-label")
        for w in (self.info, buttons, self.note):
            box.append(w)
        self.insert_child_after(_frame(box), self.status)

    def update_status(self, status):
        st = status.get("auth") or {}
        self.state = st
        finger = st.get("fingerprint", {})
        lines = [_("Fingerprint: ") + (_("reader found") if finger.get("hardware") else _("no reader found"))
                 + ("" if finger.get("installed") else _(" (fprintd not installed)"))]
        if st.get("pending"):
            lines.append(_("Changes not applied yet: press Apply (asks for your password)."))
        self.info.set_label("\n".join(lines))
        self.btn["install"].set_visible(not finger.get("installed"))
        self.btn["fingerprint"].set_visible(bool(finger.get("hardware") and finger.get("installed")))
        self.btn["apply"].set_sensitive(bool(st.get("pending")))
        try:
            self.update(self.win.client.get_all()[self.section])
        except (DaemonUnavailable, CallError):
            pass

    def _run(self, script: str) -> None:
        cmd = _terminal_command(script + '; echo; printf "Press Enter to close. "; read _')
        if cmd is None:
            self.win.show_error("Couldn't find a terminal to run this in.")
            return
        subprocess.Popen(cmd, start_new_session=True)

    def _install(self, _b) -> None:
        self._run("sudo pacman -S --needed fprintd")

    def _fingerprint(self, _b) -> None:
        self._run("fprintd-enroll")

    def _pkexec(self, script: str, what: str) -> None:
        from .pages.async_util import run_async

        def go():
            r = subprocess.run(["pkexec", "sh", "-c", script], capture_output=True, text=True)
            return None if r.returncode == 0 else ("cancelled" if r.returncode == 126 else r.stderr.strip())

        def done(err):
            if err:
                self.win.show_error(f"{what}: {err}")
            else:
                self.win.notify(what)
            self.win.refresh_everything()
            return GLib.SOURCE_REMOVE
        run_async(go, done)

    def _apply(self, _b) -> None:
        from . import auth
        try:
            changes = auth.plan(self.win.client.get_all()["auth"])
        except (ValueError, DaemonUnavailable, CallError) as e:
            self.win.show_error(str(e))
            return
        if changes:
            self._pkexec(auth.apply_script(changes), _("Unlock settings applied"))

    def _restore(self, _b) -> None:
        from . import auth
        self._pkexec(auth.restore_script(), _("Unlock changes undone"))


class LocationPage(SchemaPage):
    visible_when = {
        "latitude": lambda v: v["source"] == "manual",
        "longitude": lambda v: v["source"] == "manual",
    }

    def update_status(self, status):
        loc = status["location"]
        where = f"{loc['latitude']:.2f}, {loc['longitude']:.2f}"
        if loc["source"] == "timezone":
            text = f"From your timezone ({loc['timezone']}): {where}. Used for sunrise and sunset."
        elif loc["source"] == "manual":
            text = f"Using {where} for sunrise and sunset."
        else:
            text = f"Couldn't tell your location from the timezone; using {where}. Set it by hand below."
        self.status.set_label(text)
        self.status.set_visible(True)


class ComponentPage(SchemaPage):
    """A shell component: "managed" switch, its options, and whether it runs."""
    program = ""

    def __init__(self, win, section, title, keys, **kw):
        # whether the app runs it is chosen in System > Components
        super().__init__(win, section, title, [k for k in keys if k["name"] != "managed"], **kw)
        self.visible_when = {k["name"]: (lambda v: v["managed"]) for k in keys if k["name"] != "managed"}

    def update_status(self, status):
        c = status.get("components", {}).get(self.section)
        if c is None:
            return
        err = status["errors"].get(self.section)
        text = ""
        if c["foreign_pids"] and c["managed"]:
            text = (f"Can't start {self.program}: your own setup already runs it. Remove it from your sway "
                    "config, or leave it to your setup in System \u203a Components.")
        elif not c["managed"]:
            text = (f"{self.program} is run by your own setup, so these settings don't apply. "
                    "Let ChoCaiDat run it in System \u203a Components.")
        elif c["running"]:
            text = ""
        elif self.program in c.get("missing", []):
            text = f"{self.program} is not installed. Install it with: sudo pacman -S {self.program}"
        else:
            text = f"{self.program} is not running." + (f" {err[0]}" if err else "")
        others = [m for m in c.get("missing", []) if m != self.program]
        if c["managed"] and others:
            text = (text + "\n" if text else "") + (f"{', '.join(others)} is not installed, so the option that needs it does nothing. "
                     f"Install it with: sudo pacman -S {' '.join(others)}")
        self.status.set_label(text)
        self.status.set_visible(bool(text))


class BarPage(ComponentPage):
    program = "swayctl-bar"

    def make_row(self, key):
        if key["name"] == "theme":
            return ThemeRow(self, key, empty_label=_("Same as the desktop"))
        return super().make_row(key)

    def update_status(self, status):
        super().update_status(status)
        if "theme" in self.rows:
            self.rows["theme"].set_names([t["name"] for t in status["appearance"]["themes"]])


class NotificationsPage(ComponentPage):
    """Shown by swayctl-bar itself: pop-ups at a corner, the list and
    do-not-disturb in Quick Settings."""
    program = "swayctl-bar"



class IdlePage(ComponentPage):
    program = "swayidle"

    def __init__(self, win, section, title, keys):
        super().__init__(win, section, title, keys)
        lock = Gtk.Button(label="Lock now", halign=Gtk.Align.START)
        lock.connect("clicked", lambda _b: win.action("lock"))
        self.append(lock)


class ClipboardPage(ComponentPage):
    program = "cliphist"

    def __init__(self, win, section, title, keys):
        super().__init__(win, section, title, keys)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        h = Gtk.Label(label="History", xalign=0)
        h.add_css_class("heading")
        box.append(h)
        self.shortcut = Gtk.Label(xalign=0, wrap=True)
        self.shortcut.add_css_class("dim-label")
        box.append(self.shortcut)
        buttons = Gtk.Box(spacing=8)
        show = Gtk.Button(label="Open history")
        show.connect("clicked", lambda _b: self._run("history"))
        remove = Gtk.Button(label="Remove an entry…")
        remove.connect("clicked", lambda _b: self._run("delete"))
        clear = Gtk.Button(label="Clear history…")
        clear.add_css_class("destructive-action")
        clear.connect("clicked", self._clear)
        for b in (show, remove, clear):
            buttons.append(b)
        box.append(buttons)
        self.append(box)

    def _run(self, what: str) -> None:
        from .clipboard import run
        run(what, wait=False)  # walker when running, fuzzel otherwise

    def _clear(self, _b) -> None:
        dialog = Gtk.AlertDialog(message="Clear the whole clipboard history?",
                                 detail="Everything you copied so far is removed. This can't be undone.",
                                 buttons=["Cancel", "Clear"], cancel_button=0, default_button=0)

        def answered(d, res):
            try:
                if d.choose_finish(res) == 1:
                    self._run("clear")
            except GLib.Error:
                pass
        dialog.choose(self.win, None, answered)

    def update_status(self, status):
        super().update_status(status)
        try:
            values = self.win.client.get("keybindings.bindings")
            mod = self.win.client.get("keybindings.modifier")
        except (DaemonUnavailable, CallError):
            return
        keys = [b["keys"] for b in values if "clipboard.history" in b["command"]]
        if keys:
            names = {"Mod4": "Super", "Mod1": "Alt", "Control": "Ctrl"}
            pretty = keys[0].replace("$mod", names.get(mod, mod))
            self.shortcut.set_label(f"Open the history with {pretty}. Change it on the Shortcuts page.")
        else:
            self.shortcut.set_label("No shortcut opens the history yet; add one on the Shortcuts page "
                                    "with the command: exec swayctl-center action clipboard.history")


def _terminal_command(script: str) -> list[str] | None:
    """Run `script` in a terminal window the user can type a password into."""
    import shutil
    for term, args in (("kitty", ["-e"]), ("foot", []), ("alacritty", ["-e"]), ("wezterm", ["start", "--"]),
                       ("gnome-terminal", ["--"]), ("konsole", ["-e"]), ("xterm", ["-e"])):
        if shutil.which(term):
            return [term, *args, "sh", "-c", script]
    return None


class LauncherPage(ComponentPage):
    program = "walker"
    visible_when_files = ("files_in_results", "file_folders", "file_excluded", "file_watch")

    def __init__(self, win, section, title, keys):
        super().__init__(win, section, title, keys)
        for name in self.visible_when_files:
            self.visible_when[name] = lambda v: v["managed"] and v["files"]
        # shown while Walker or some of its parts aren't installed
        self.install = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                               margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        self.install_text = Gtk.Label(xalign=0, wrap=True)
        self.install_pkgs = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.install_pkgs.add_css_class("monospace")
        self.install_pkgs.add_css_class("caption")
        buttons = Gtk.Box(spacing=8)
        self.install_btn = Gtk.Button(label="Install…")
        self.install_btn.add_css_class("suggested-action")
        self.install_btn.connect("clicked", self._install)
        again = Gtk.Button(label="Check again")
        again.connect("clicked", self._check_again)
        buttons.append(self.install_btn)
        buttons.append(again)
        for w in (self.install_text, self.install_pkgs, buttons):
            self.install.append(w)
        self.install_frame = _frame(self.install)
        self.install_frame.set_visible(False)
        self.insert_child_after(self.install_frame, self.status)
        self.shortcut = Gtk.Label(xalign=0, wrap=True)
        self.shortcut.add_css_class("dim-label")
        self.insert_child_after(self.shortcut, self.install_frame)
        self.missing: list[str] = []
        self.walker_missing = False

    def _install_script(self) -> str | None:
        import shutil
        helper = shutil.which("paru") or shutil.which("yay")
        aur = [p for p in self.missing if p.startswith("elephant")]
        steps = ['echo "Installing the Walker launcher for ChoCaiDat"', "echo"]
        if self.walker_missing:
            steps.append("sudo pacman -S --needed walker")
        if aur:
            if not helper:
                return None
            steps.append(f"{Path(helper).name} -S --needed {' '.join(aur)}")
        steps += ["echo", 'printf "Done. Press Enter to close. "', "read _"]
        return " && ".join(steps[:-3]) + "; " + "; ".join(steps[-3:])

    def _install(self, _b) -> None:
        script = self._install_script()
        cmd = _terminal_command(script) if script else None
        if cmd is None:
            self.win.show_error("Couldn't find a terminal or an AUR helper (paru, yay) to install with. "
                                "Install the packages listed on this page, then press Check again.")
            return
        subprocess.Popen(cmd, start_new_session=True)

    def _check_again(self, _b) -> None:
        try:
            self.win.client.apply_all()  # starts elephant/walker if they're there now
        except (DaemonUnavailable, CallError) as e:
            self.win.show_error(str(e))
        self.win.refresh_everything()

    def update_status(self, status):
        super().update_status(status)
        c = status.get("components", {}).get(self.section)
        if c is None:
            return
        self.walker_missing = not c.get("walker_installed", False)
        self.missing = c.get("missing_packages", [])
        need = (["walker"] if self.walker_missing else []) + self.missing
        if c["managed"] and need:
            if self.walker_missing:
                text = ("Walker isn't installed yet. It's a fast launcher that finds apps, files and settings, "
                        "does math and searches the web. Until it's installed, the launcher shortcut opens fuzzel.")
            else:
                text = "Some parts of the launcher aren't installed, so those results won't show up yet."
            self.install_text.set_label(text)
            self.install_pkgs.set_label("Packages: " + " ".join(need))
            self.install_frame.set_visible(True)
            self.status.set_visible(False)
        else:
            self.install_frame.set_visible(False)
        try:
            bindings = self.win.client.get("keybindings.bindings")
            mod = self.win.client.get("keybindings.modifier")
        except (DaemonUnavailable, CallError):
            return
        keys = [b["keys"] for b in bindings if "launcher.open" in b["command"]]
        names = {"Mod4": "Super", "Mod1": "Alt", "Control": "Ctrl"}
        self.shortcut.set_label(
            f"Open the launcher with {keys[0].replace('$mod', names.get(mod, mod))}. Change it on the Shortcuts page."
            if keys else "No shortcut opens the launcher yet; add one on the Shortcuts page with the command: "
                         "exec swayctl-center action launcher.open")


def _scroll_owned(win, device: str, status: dict[str, Any]) -> bool | None:
    """True when smooth scrolling runs for this device (so sway's own scroll
    settings don't apply); None if that can't be told right now."""
    try:
        smooth = win.client.get(f"scrolling.{device}_smooth")
    except (DaemonUnavailable, CallError):
        return None
    sc = status.get("scrolling", {})
    # the service, or swayctl-fx (direction/speed set from the Smooth scrolling rows)
    return bool(smooth and (sc.get("running") or sc.get("compositor")))


class DeviceScrollPiece(SchemaPage):
    """sway's scroll settings for a device, shown only while smooth scrolling is off."""
    device = ""

    def update_status(self, status):
        owned = _scroll_owned(self.win, self.device, status)
        if owned is not None:
            self.set_visible(not owned)


class SmoothScrollPiece(SchemaPage):
    """Smooth scrolling for one device: the switch always, the rest while it's on."""
    device = ""
    setup_card = False

    def __init__(self, win, section, title, keys, groups, compact=True):
        super().__init__(win, section, title, keys, groups, compact)
        self.running = False
        self.compositor = False
        self.visible_when = {}  # our own dict, not the class-level one every page shares
        # only swayctl-fx smooths scrolling now: without it there's nothing to set here
        for name in self.rows:
            self.visible_when[name] = (
                (lambda v: self.compositor) if name.endswith("_smooth")
                else (lambda v: v[f"{self.device}_smooth"] and self.compositor))
        if self.setup_card:
            self.setup = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                                 margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
            self.setup_text = Gtk.Label(xalign=0, wrap=True)
            self.setup_btn = Gtk.Button(label="Set up smooth scrolling…", halign=Gtk.Align.START)
            self.setup_btn.add_css_class("suggested-action")
            self.setup_btn.connect("clicked", self._set_up)
            self.setup.append(self.setup_text)
            self.setup.append(self.setup_btn)
            self.setup_frame = _frame(self.setup)
            self.setup_frame.set_visible(False)
            self.insert_child_after(self.setup_frame, self.status)

    def _set_up(self, _b) -> None:
        # the only setup left: turning the old smooth scrolling service off
        self._retire_service()

    def _retire_service(self) -> None:
        """Under swayctl-fx the system service isn't needed; while it runs it
        still grabs the mouse and re-sends its wheel through a virtual device."""
        from .modules import scrolling
        from .pages.async_util import run_async
        self.setup_btn.set_sensitive(False)

        def go():
            r = subprocess.run(["pkexec", "systemctl", "disable", "--now", scrolling.SERVICE],
                               capture_output=True, text=True)
            return None if r.returncode == 0 else ("cancelled" if r.returncode == 126 else r.stderr.strip())

        def done(err):
            self.setup_btn.set_sensitive(True)
            if err:
                self.win.show_error(f"Couldn't turn the service off: {err}")
            self.win.refresh_everything()
            return GLib.SOURCE_REMOVE
        run_async(go, done)

    def update_status(self, status):
        sc = status.get("scrolling", {})
        compositor = bool(sc.get("compositor"))
        running = bool(sc.get("running")) or compositor
        if (running, compositor) != (self.running, self.compositor):
            self.running, self.compositor = running, compositor
            try:
                self.update(self.win.client.get_all()[self.section])
            except (DaemonUnavailable, CallError):
                pass
        if not self.setup_card:
            return
        self.retire_old = bool(sc.get("service_active"))
        self.setup_btn.set_label(_("Turn off the old service…"))
        self.setup_btn.set_visible(self.retire_old)
        if self.retire_old:
            text = _("swayctl-fx smooths scrolling itself. The old smooth scrolling service is still running and "
                     "holds the mouse (its wheel can stop working): turn it off. Asks for your password.")
        elif not compositor:
            text = _("Smooth scrolling needs the Sway (swayctl-fx) session: log out and pick it on the login screen.")
        else:
            text = ""  # smooth scrolling is swayctl-fx's job now; nothing to set up
        self.setup_text.set_label(text)
        self.setup_frame.set_visible(bool(text))


class PointingPage(Gtk.Box):
    """Touchpad and mouse, each with exactly one pointer speed and one scroll speed."""

    def __init__(self, win, keys_by_section):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                         margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        self.append(_heading("Mouse & Touchpad"))
        tp, ptr, sc = (keys_by_section[k] for k in ("input.touchpad", "input.pointer", "scrolling"))

        def piece(cls, section, keys, groups, device=""):
            p = cls(win, section, None, keys, groups, compact=True)
            if device:
                p.device = device
            return p

        class TouchpadSmooth(SmoothScrollPiece):
            device, setup_card = "touchpad", True

        class MouseSmooth(SmoothScrollPiece):
            device = "mouse"

        self.pieces = [
            piece(SchemaPage, "input.touchpad", tp,
                  [("Touchpad", ["events", "tap", "drag", "dwt", "pointer_accel"])]),
            piece(DeviceScrollPiece, "input.touchpad", tp,
                  [("", ["natural_scroll", "scroll_factor", "scroll_method"])], "touchpad"),
            TouchpadSmooth(win, "scrolling", None, sc,
                           [("", ["touchpad_smooth", "touchpad_natural", "touchpad_speed", "touchpad_glide"]),
                            ("~Fine-tune scrolling", ["touchpad_ramp_ms", "touchpad_smoothing"])]),
            piece(SchemaPage, "input.touchpad", tp,
                  [("~More touchpad options", ["tap_button_map", "click_method", "drag_lock", "middle_emulation",
                                               "left_handed", "accel_profile"])]),
            piece(SchemaPage, "input.pointer", ptr, [("Mouse", ["pointer_accel", "accel_profile", "left_handed"])]),
            piece(DeviceScrollPiece, "input.pointer", ptr, [("", ["natural_scroll", "scroll_factor"])], "mouse"),
            MouseSmooth(win, "scrolling", None, sc,
                        [("", ["mouse_smooth", "mouse_natural", "mouse_speed", "mouse_glide"]),
                         ("~Fine-tune scrolling", ["mouse_smoothing"])]),
            piece(SchemaPage, "input.pointer", ptr, [("~More mouse options", ["middle_emulation"])]),
        ]
        for p in self.pieces:
            self.append(p)


def _as_part(widget: Gtk.Widget, heading: str) -> Gtk.Widget:
    """Restyle a page to sit inside a combined page: no outer margins, and its
    big title becomes a sub-heading (or goes away when `heading` is empty)."""
    for side in ("top", "bottom", "start", "end"):
        getattr(widget, f"set_margin_{side}")(0)
    first = widget.get_first_child()
    if isinstance(first, Gtk.Label) and first.has_css_class("title-2"):
        if heading:
            first.set_label(_(heading))
            first.remove_css_class("title-2")
            first.add_css_class("title-3")
        else:
            first.set_visible(False)
    return widget


class CompositePage(Gtk.Box):
    """A sidebar page made of several parts (each normally a page of its own)."""

    def __init__(self, title: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=28,
                         margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        self.append(_heading(title))

    def add_part(self, widget: Gtk.Widget, heading: str) -> None:
        self.append(_as_part(widget, heading))


COMPONENT_NAMES = {
    "bar": ("Bar", "swayctl-bar"), "notifications": ("Notifications", "swayctl-bar"),
    "idle": ("Lock & idle", "swayidle and swayctl-lock"), "clipboard": ("Clipboard history", "cliphist"),
    "input_method": ("Typing other languages", "fcitx5"), "launcher": ("Launcher", "Walker"),
    "polkit_agent": ("Password prompt", "polkit-gnome, for tasks that need your password"),
}


class ComponentToggle(Gtk.ListBoxRow):
    """One line in System > Components: does the app run this, and is it running."""

    def __init__(self, win, section: str):
        super().__init__(activatable=False)
        self.win, self.section = win, section
        self.updating = False
        name, program = COMPONENT_NAMES[section]
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch.connect("notify::active", self._toggled)
        self.row = _row(name, self.switch, program)
        self.sub = self.row.get_first_child().get_last_child()  # the subtitle label
        self.set_child(self.row)

    def _toggled(self, sw, _p) -> None:
        if not self.updating:
            self.win.set(f"{self.section}.managed", sw.get_active())

    def update(self, values: dict[str, Any]) -> None:
        self.updating = True
        try:
            self.switch.set_active(values["managed"])
        finally:
            self.updating = False

    def update_status(self, status: dict[str, Any]) -> None:
        c = status.get("components", {}).get(self.section)
        if c is None:
            return
        name, program = COMPONENT_NAMES[self.section]
        if not c["managed"]:
            state = "your own setup runs it" if c["foreign_pids"] else "off"
        elif c["foreign_pids"]:
            state = "can't start: your own setup already runs it"
        elif c["running"]:
            state = "running"
        elif c.get("missing"):
            state = "not installed"
        else:
            state = "not running"
        self.sub.set_label(f"{program} \u00b7 {state}")


class InputMethodPage(ComponentPage):
    program = "fcitx5"


# --- wallpaper -------------------------------------------------------------

class ImageRow(Gtk.ListBoxRow):
    def __init__(self, page: Page, key: dict[str, Any]):
        super().__init__(activatable=False)
        self.page, self.path = page, f"{key['section']}.{key['name']}"
        self.current = ""
        self.file_label = Gtk.Label(xalign=1, ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=28)
        choose = Gtk.Button(label="Choose…")
        choose.connect("clicked", self._choose)
        self.clear = Gtk.Button(icon_name="edit-clear-symbolic", tooltip_text="Use a plain color")
        self.clear.add_css_class("flat")
        self.clear.connect("clicked", lambda _b: page.win.set(self.path, ""))
        box = Gtk.Box(spacing=6)
        for w in (self.file_label, choose, self.clear):
            box.append(w)
        self.set_child(_row(key["label"], box, key.get("help")))

    def _choose(self, _button) -> None:
        dialog = Gtk.FileDialog(title="Choose a wallpaper")
        images = Gtk.FileFilter(name="Images")
        images.add_mime_type("image/*")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(images)
        dialog.set_filters(filters)
        pictures = Path.home() / "Pictures"
        if pictures.is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(str(pictures)))

        def done(d, result):
            try:
                f = d.open_finish(result)
            except GLib.Error:
                return  # cancelled
            if f is not None and f.get_path():
                self.page.win.set(self.path, f.get_path())
        dialog.open(self.page.win, None, done)

    def set_value(self, value: str) -> None:
        self.current = value
        self.file_label.set_label(Path(value).name.split("-", 1)[-1] if value else "None (plain color)")
        self.clear.set_visible(bool(value))


class BackgroundPage(SchemaPage):
    def make_row(self, key):
        return ImageRow(self, key) if key["name"] == "image" else SettingRow(self, key)


# --- displays --------------------------------------------------------------

class MonitorMap(Gtk.DrawingArea):
    """The monitors as boxes, laid out like sway does; drag one to move it.
    It sticks to the nearest edge of another monitor when dropped."""
    PAD = 16

    def __init__(self, on_moved: Callable[[dict[str, list[int]]], None]):
        super().__init__(content_height=220, hexpand=True)
        self.on_moved = on_moved
        self.rects: dict[str, list[float]] = {}  # ident -> [x, y, w, h] logical px
        self.names: dict[str, str] = {}
        self.dragging: str | None = None
        self.start = (0.0, 0.0)
        self.view = (1.0, 0.0, 0.0)  # scale, offset x, offset y (kept still during a drag)
        self.set_draw_func(self._draw)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._begin)
        drag.connect("drag-update", self._update)
        drag.connect("drag-end", self._end)
        self.add_controller(drag)

    def set_monitors(self, monitors: dict[str, tuple[str, list[float]]]) -> None:
        self.rects = {k: list(r) for k, (_n, r) in monitors.items()}
        self.names = {k: n for k, (n, _r) in monitors.items()}
        self.dragging = None
        self.queue_draw()

    def _fit(self) -> tuple[float, float, float]:
        if self.dragging:
            return self.view
        rs = list(self.rects.values())
        x0, y0 = min(r[0] for r in rs), min(r[1] for r in rs)
        x1, y1 = max(r[0] + r[2] for r in rs), max(r[1] + r[3] for r in rs)
        w, h = self.get_width() - 2 * self.PAD, self.get_height() - 2 * self.PAD
        # room around the layout, so a monitor can be dragged to any side
        k = min(w / ((x1 - x0) * 1.6 or 1), h / ((y1 - y0) * 1.6 or 1))
        return k, self.PAD + (w - (x1 - x0) * k) / 2 - x0 * k, self.PAD + (h - (y1 - y0) * k) / 2 - y0 * k

    def _draw(self, _area, cr, _w, _h) -> None:
        if not self.rects:
            return
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import PangoCairo
        self.view = k, ox, oy = self._fit()
        fg = self.get_color()
        for ident, (x, y, w, h) in self.rects.items():
            rx, ry, rw, rh = ox + x * k + 2, oy + y * k + 2, w * k - 4, h * k - 4
            active = ident == self.dragging
            # a rounded tile of the accent, with the glass's bright rim
            r = min(12.0, rw / 4, rh / 4)
            cr.new_sub_path()
            cr.arc(rx + rw - r, ry + r, r, -math.pi / 2, 0)
            cr.arc(rx + rw - r, ry + rh - r, r, 0, math.pi / 2)
            cr.arc(rx + r, ry + rh - r, r, math.pi / 2, math.pi)
            cr.arc(rx + r, ry + r, r, math.pi, 3 * math.pi / 2)
            cr.close_path()
            cr.set_source_rgba(0.21, 0.52, 0.89, 0.6 if active else 0.35)
            cr.fill_preserve()
            cr.set_source_rgba(1, 1, 1, 0.55)
            cr.set_line_width(1.5)
            cr.stroke()
            layout = self.create_pango_layout(self.names.get(ident, ident))  # the app's font
            layout.set_width(int(max(rw - 8, 1) * Pango.SCALE))
            layout.set_alignment(Pango.Alignment.CENTER)
            layout.set_ellipsize(Pango.EllipsizeMode.END)
            _tw, th = layout.get_pixel_size()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 1)
            cr.move_to(rx + 4, ry + (rh - th) / 2)
            PangoCairo.show_layout(cr, layout)

    def _hit(self, px: float, py: float) -> str | None:
        k, ox, oy = self.view
        for ident, (x, y, w, h) in reversed(list(self.rects.items())):
            if ox + x * k <= px <= ox + (x + w) * k and oy + y * k <= py <= oy + (y + h) * k:
                return ident
        return None

    def _begin(self, gesture, px, py) -> None:
        self.view = self._fit()
        self.dragging = self._hit(px, py)
        if self.dragging is None:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        self.start = tuple(self.rects[self.dragging][:2])

    def _update(self, _g, dx, dy) -> None:
        if self.dragging:
            k = self.view[0]
            self.rects[self.dragging][:2] = [self.start[0] + dx / k, self.start[1] + dy / k]
            self.queue_draw()

    def _end(self, _g, _dx, _dy) -> None:
        from .modules.outputs import normalized, snap
        ident, self.dragging = self.dragging, None
        if ident is None:
            return
        r = self.rects[ident]
        others = [tuple(o) for i, o in self.rects.items() if i != ident]
        r[0], r[1] = snap(tuple(r), others, threshold=min(r[2], r[3]) / 8)
        positions = normalized({i: (o[0], o[1]) for i, o in self.rects.items()})
        for i, (x, y) in positions.items():
            self.rects[i][:2] = [x, y]
        self.queue_draw()
        self.on_moved(positions)


class OutputsPage(Page):
    TRANSFORMS = ["normal", "90", "180", "270", "flipped", "flipped-90", "flipped-180", "flipped-270"]

    def __init__(self, win, section, title):
        super().__init__(win, section, title)
        self.map = MonitorMap(self._moved)
        self.map_frame = _frame(self.map)
        self.append(self.map_frame)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.append(self.body)
        self.config: dict[str, Any] = {}

    def _moved(self, positions: dict[str, list[int]]) -> None:
        new = copy.deepcopy(self.config)
        for ident, pos in positions.items():
            new[ident]["position"] = pos
        if new != self.config:
            self.win.set("outputs.config", new)

    def _live(self) -> dict[str, dict[str, Any]]:
        from .modules.outputs import identifier
        try:
            return {identifier(o): o for o in swayipc.Connection().get_outputs()}
        except (swayipc.IPCError, OSError):
            return {}

    def _set(self, ident: str, field: str, value: Any) -> None:
        if self.updating or self.config[ident].get(field) == value:
            return
        new = copy.deepcopy(self.config)
        new[ident][field] = value
        self.win.set("outputs.config", new)

    def update(self, values: dict[str, Any]) -> None:
        self.updating = True
        try:
            self.config = values["config"]
            child = self.body.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                self.body.remove(child)
                child = nxt
            live = self._live()
            self._update_map(live)
            for ident, cfg in self.config.items():
                self.body.append(self._output_box(ident, cfg, live.get(ident)))
        finally:
            self.updating = False

    def _update_map(self, live: dict[str, dict[str, Any]]) -> None:
        from .modules.outputs import logical_size
        monitors = {}
        for ident, cfg in self.config.items():
            o = live.get(ident)
            if not o or not cfg["enabled"]:
                continue
            pos = cfg["position"] or [o["rect"]["x"], o["rect"]["y"]]
            monitors[ident] = (o["name"], [pos[0], pos[1], *logical_size(cfg, o)])
        self.map.set_monitors(monitors)
        self.map_frame.set_visible(bool(monitors))

    def _output_box(self, ident: str, cfg: dict[str, Any], live: dict[str, Any] | None) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        title = Gtk.Label(xalign=0)
        state = f"{cfg.get('name', '')} · connected" if live else "not connected"
        title.set_markup(f"<b>{GLib.markup_escape_text(ident)}</b>  <small>{GLib.markup_escape_text(state)}</small>")
        box.append(title)
        lb = _list_box()

        sw = Gtk.Switch(active=cfg["enabled"])
        sw.connect("notify::active", lambda s, _p: self._set(ident, "enabled", s.get_active()))
        lb.append(_row("Enabled", sw))

        modes = [format_mode(m) for m in (live or {}).get("modes", [])]
        modes = list(dict.fromkeys(modes))
        if modes:
            if cfg["mode"] and cfg["mode"] not in modes:
                modes.insert(0, cfg["mode"])
            dd = Gtk.DropDown.new_from_strings(modes)
            dd.set_selected(modes.index(cfg["mode"]) if cfg["mode"] in modes else 0)
            dd.connect("notify::selected", lambda d, _p: self._set(ident, "mode", modes[d.get_selected()]))
            lb.append(_row("Resolution", dd))

        scale = Gtk.SpinButton.new_with_range(0.25, 10, 0.25)
        scale.set_digits(2)
        scale.set_value(cfg["scale"])
        scale.connect("value-changed", lambda s: self._set(ident, "scale", round(s.get_value(), 2)))
        lb.append(_row("Scale", scale))

        tr = Gtk.DropDown.new_from_strings(self.TRANSFORMS)
        tr.set_selected(self.TRANSFORMS.index(cfg["transform"]))
        tr.connect("notify::selected", lambda d, _p: self._set(ident, "transform", self.TRANSFORMS[d.get_selected()]))
        lb.append(_row("Rotation", tr))

        vrr = Gtk.Switch(active=cfg["adaptive_sync"])
        vrr.connect("notify::active", lambda s, _p: self._set(ident, "adaptive_sync", s.get_active()))
        lb.append(_row("Adaptive sync", vrr))

        box.append(_frame(lb))
        return box


# --- lists: shortcuts, startup apps -----------------------------------------

class ListPage(SchemaPage):
    """A schema page (for any scalar keys) plus an editable list setting."""
    list_key = ""

    def __init__(self, win, section, title, keys):
        super().__init__(win, section, title, keys)
        self.items: list[dict[str, Any]] = []
        self.add_row = self.build_add_row()
        self.append(self.add_row)
        self.search = Gtk.SearchEntry(placeholder_text="Filter")
        self.search.connect("search-changed", lambda _s: self.items_box.invalidate_filter())
        self.append(self.search)
        self.items_box = _list_box()
        self.items_box.set_filter_func(self._filter)
        self.append(_frame(self.items_box))

    def _filter(self, row: Gtk.ListBoxRow) -> bool:
        text = self.search.get_text().lower()
        return not text or text in getattr(row, "search_text", "")

    def save(self, items: list[dict[str, Any]]) -> None:
        self.win.set(f"{self.section}.{self.list_key}", items)

    def update(self, values: dict[str, Any]) -> None:
        super().update(values)
        self.items = values[self.list_key]
        self.items_box.remove_all()
        for i, item in enumerate(self.items):
            row = Gtk.ListBoxRow(activatable=False)
            row.set_child(self.item_widget(i, item))
            row.search_text = " ".join(str(v) for v in item.values()).lower()
            self.items_box.append(row)

    def remove(self, index: int) -> None:
        self.save([it for i, it in enumerate(self.items) if i != index])

    def _delete_button(self, index: int) -> Gtk.Button:
        b = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Remove")
        b.add_css_class("flat")
        b.connect("clicked", lambda _b: self.remove(index))
        return b

    def build_add_row(self) -> Gtk.Widget:
        raise NotImplementedError

    def item_widget(self, index: int, item: dict[str, Any]) -> Gtk.Widget:
        raise NotImplementedError


class KeybindingsPage(ListPage):
    list_key = "bindings"

    def build_add_row(self):
        box = Gtk.Box(spacing=6)
        self.keys_entry = Gtk.Entry(placeholder_text="$mod+Shift+x", width_chars=18)
        self.cmd_entry = Gtk.Entry(placeholder_text="exec foot", hexpand=True)
        add = Gtk.Button(label="Add")
        add.add_css_class("suggested-action")
        add.connect("clicked", self._add)
        self.cmd_entry.connect("activate", self._add)
        for w in (self.keys_entry, self.cmd_entry, add):
            box.append(w)
        hint = Gtk.Label(label="Adding a shortcut that already exists replaces its command.", xalign=0)
        hint.add_css_class("dim-label")
        hint.add_css_class("caption")
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        outer.append(box)
        outer.append(hint)
        return outer

    def _add(self, _w) -> None:
        keys, cmd = self.keys_entry.get_text().strip(), self.cmd_entry.get_text().strip()
        if not keys or not cmd:
            return
        # the daemon keeps the last entry for identical keys+flags
        if self.win.set(f"{self.section}.bindings", self.items + [{"keys": keys, "command": cmd, "flags": []}]):
            self.keys_entry.set_text("")
            self.cmd_entry.set_text("")

    def _edit(self, item: dict[str, Any]) -> None:
        self.keys_entry.set_text(item["keys"])
        self.cmd_entry.set_text(item["command"])
        self.cmd_entry.grab_focus()

    def item_widget(self, index, item):
        box = Gtk.Box(spacing=12)
        keys = Gtk.Label(label=item["keys"], xalign=0, width_chars=26, max_width_chars=26,
                         ellipsize=Pango.EllipsizeMode.END)
        keys.add_css_class("monospace")
        cmd = Gtk.Label(label=item["command"], xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                        tooltip_text=item["command"])
        box.append(keys)
        box.append(cmd)
        if item["flags"]:
            flags = Gtk.Label(label=" ".join(item["flags"]))
            flags.add_css_class("dim-label")
            flags.add_css_class("caption")
            box.append(flags)
        edit = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="Edit")
        edit.add_css_class("flat")
        edit.connect("clicked", lambda _b: self._edit(item))
        box.append(edit)
        box.append(self._delete_button(index))
        return box


# What each themed config is, by where it's written (the user never sees paths)
THEMED_APP_NAMES = [
    ("fuzzel/fuzzel.ini", "Fuzzel", "app launcher"),
    ("kitty/theme.conf", "Kitty", "terminal; open windows update too"),
    ("btop/themes/", "btop", "system monitor"),
    ("gtk-3.0/gtk.css", "GTK 3 apps", "older GTK apps"),
    ("sway/theme/current.conf", "Sway window colors", "colors your sway config uses"),
    ("sway/theme/state", "Neovim", "picks its colorscheme from this"),
]


def themed_app_name(output: str) -> tuple[str, str]:
    for suffix, name, what in THEMED_APP_NAMES:
        if suffix in output:
            return name, what
    parent = Path(output).parent.name.lstrip(".")
    return parent[:1].upper() + parent[1:], ""


class ThemedAppsPage(Page):
    """Other apps that follow the theme and font, each switchable on/off."""

    def __init__(self, win, section, title, keys):
        super().__init__(win, section, title)
        intro = Gtk.Label(xalign=0, wrap=True, label=(
            "These apps change color (and font, where they can) together with the desktop."))
        intro.add_css_class("dim-label")
        self.append(intro)
        self.items: list[dict[str, Any]] = []
        self.list = _list_box()
        self.frame = _frame(self.list)
        self.append(self.frame)
        self.empty = Gtk.Label(label="No other apps are themed yet.", xalign=0)
        self.empty.add_css_class("dim-label")
        self.append(self.empty)

    def _toggle(self, index: int, on: bool) -> None:
        if self.updating or self.items[index].get("enabled", True) == on:
            return
        items = copy.deepcopy(self.items)
        items[index]["enabled"] = on
        self.win.set(f"{self.section}.templates", items)

    def update(self, values):
        self.updating = True
        try:
            self.items = values["templates"]
            self.list.remove_all()
            for i, item in enumerate(self.items):
                name, what = themed_app_name(item["output"])
                sw = Gtk.Switch(active=item.get("enabled", True))
                sw.connect("notify::active", lambda s, _p, i=i: self._toggle(i, s.get_active()))
                self.list.append(Gtk.ListBoxRow(activatable=False, child=_row(name, sw, what or None)))
            self.frame.set_visible(bool(self.items))
            self.empty.set_visible(not self.items)
        finally:
            self.updating = False


# keys people usually swap, first in the pickers; then everything else keyd knows
COMMON_KEYS = ["capslock", "esc", "leftcontrol", "leftalt", "leftmeta", "leftshift", "rightcontrol",
               "rightalt", "rightmeta", "rightshift", "tab", "backspace", "enter", "space", "compose",
               "insert", "delete", "home", "end", "pageup", "pagedown", "print", "sysrq", "scrolllock"]


class KeyRemapPage(ListPage):
    """Swap or remap keys with keyd (below sway: works everywhere, even the TTY)."""
    list_key = "remaps"

    def __init__(self, win, section, title, keys):
        from .modules.keyremap import key_names
        known = key_names()
        self.key_list = [k for k in COMMON_KEYS if k in known or not known] + \
                        [k for k in known if k not in COMMON_KEYS]
        super().__init__(win, section, title, keys)
        self.setup = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                             margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        self.setup_text = Gtk.Label(xalign=0, wrap=True)
        self.setup_btn = Gtk.Button(label="Set up key remapping…", halign=Gtk.Align.START)
        self.setup_btn.add_css_class("suggested-action")
        self.setup_btn.connect("clicked", self._set_up)
        self.setup.append(self.setup_text)
        self.setup.append(self.setup_btn)
        self.setup_frame = _frame(self.setup)
        self.setup_frame.set_visible(False)
        self.insert_child_after(self.setup_frame, self.get_first_child())  # below the heading

    def _picker(self) -> Gtk.DropDown:
        dd = Gtk.DropDown.new_from_strings(self.key_list)
        dd.set_enable_search(True)
        dd.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        return dd

    def build_add_row(self):
        box = Gtk.Box(spacing=6)
        self.from_dd, self.to_dd = self._picker(), self._picker()
        if "esc" in self.key_list:
            self.to_dd.set_selected(self.key_list.index("esc"))
        self.swap_check = Gtk.CheckButton(label="Swap both ways", active=True)
        add = Gtk.Button(label="Add")
        add.add_css_class("suggested-action")
        add.connect("clicked", self._add)
        box.append(self.from_dd)
        box.append(Gtk.Label(label="→"))
        box.append(self.to_dd)
        box.append(self.swap_check)
        spacer = Gtk.Box(hexpand=True)
        box.append(spacer)
        box.append(add)
        # on a pane, or the check box's label floats over the wallpaper with glass on
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(8)
        return _frame(box)

    def _add(self, _w) -> None:
        src = self.key_list[self.from_dd.get_selected()]
        dst = self.key_list[self.to_dd.get_selected()]
        if src == dst:
            self.win.show_error("Pick two different keys.")
            return
        self.win.set(f"{self.section}.remaps",
                     self.items + [{"from": src, "to": dst, "swap": self.swap_check.get_active()}])

    def _toggle_swap(self, index: int, swap: bool) -> None:
        if self.updating or self.items[index]["swap"] == swap:
            return
        items = copy.deepcopy(self.items)
        items[index]["swap"] = swap
        self.save(items)

    def item_widget(self, index, item):
        box = Gtk.Box(spacing=12)
        arrow = "⇄" if item["swap"] else "→"
        label = Gtk.Label(label=f"{item['from']}  {arrow}  {item['to']}", xalign=0, hexpand=True)
        label.add_css_class("monospace")
        swap = Gtk.CheckButton(label="Swap", active=item["swap"])
        swap.connect("toggled", lambda c: self._toggle_swap(index, c.get_active()))
        box.append(label)
        box.append(swap)
        box.append(self._delete_button(index))
        return box

    def update(self, values):
        self.updating = True
        try:
            super().update(values)
        finally:
            self.updating = False
        self.search.set_visible(len(self.items) > 8)

    def update_status(self, status):
        k = status.get("keyremap", {})
        if not k:
            return
        if not k.get("keyd_installed"):
            text, button = ("Key remapping uses keyd, which isn't installed. Install it with: "
                            "sudo pacman -S keyd"), False
        elif not k.get("installed"):
            text = ("Set up once to let this page change keyd's config (you'll be asked for your password). "
                    "Your current remaps are already listed below.")
            if k.get("other_config"):
                text += (" Your /etc/keyd/default.conf also has things this page doesn't show (layers, macros…); "
                         "it's kept as default.conf.before-swayctl-center.")
            button = True
        elif not k.get("running"):
            text, button = "keyd isn't running, so remaps don't apply right now.", True
        elif k.get("outdated"):
            text, button = ("Key remapping was set up by an older version; update it to use the new options "
                            "(you'll be asked for your password)."), True
        else:
            self.setup_frame.set_visible(False)
            return
        self.setup_text.set_text(text)
        self.setup_btn.set_visible(button)
        self.setup_frame.set_visible(True)

    def _set_up(self, _b) -> None:
        from .modules import keyremap
        from .pages.async_util import run_async
        from .store import config_dir
        self.setup_btn.set_sensitive(False)
        self.setup_btn.set_label("Waiting for your password…")

        def done(err):
            self.setup_btn.set_sensitive(True)
            self.setup_btn.set_label("Set up key remapping…")
            if isinstance(err, Exception) or err:
                self.win.show_error(f"Key remapping wasn't set up: {err}")
            self.win.refresh_everything()
            return GLib.SOURCE_REMOVE
        run_async(lambda: keyremap.install(config_dir()), done)


class AutostartPage(ListPage):
    list_key = "commands"

    def build_add_row(self):
        box = Gtk.Box(spacing=6)
        self.entry = Gtk.Entry(placeholder_text="Command to run at login, e.g. fcitx5 -d", hexpand=True)
        add = Gtk.Button(label="Add")
        add.add_css_class("suggested-action")
        add.connect("clicked", self._add)
        self.entry.connect("activate", self._add)
        box.append(self.entry)
        box.append(add)
        return box

    def _add(self, _w) -> None:
        cmd = self.entry.get_text().strip()
        if cmd and self.win.set(f"{self.section}.commands", self.items + [{"command": cmd, "enabled": True}]):
            self.entry.set_text("")

    def _toggle(self, index: int, enabled: bool) -> None:
        if self.updating or self.items[index]["enabled"] == enabled:
            return
        items = copy.deepcopy(self.items)
        items[index]["enabled"] = enabled
        self.save(items)

    def item_widget(self, index, item):
        box = Gtk.Box(spacing=12)
        sw = Gtk.Switch(active=item["enabled"], valign=Gtk.Align.CENTER)
        sw.connect("notify::active", lambda s, _p: self._toggle(index, s.get_active()))
        label = Gtk.Label(label=item["command"], xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        label.add_css_class("monospace")
        box.append(sw)
        box.append(label)
        box.append(self._delete_button(index))
        return box

    def update(self, values):
        self.updating = True
        try:
            super().update(values)
        finally:
            self.updating = False
        self.search.set_visible(len(self.items) > 8)


# --- window ----------------------------------------------------------------

class SettingsWindow(Adw.ApplicationWindow):
    def __init__(self, app: Gtk.Application, initial_page: str | None = None):
        super().__init__(application=app, title="ChoCaiDat")
        self.initial_page = initial_page
        self.set_default_size(980, 680)
        self.set_size_request(360, 400)
        self.client = Client()
        self.pages: dict[str, list[Page]] = {}

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toasts = Adw.ToastOverlay(child=outer)

        # shown while the daemon isn't running
        self.offline = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        msg = Gtk.Label(label="The settings service isn't running, so changes can't be applied.",
                        xalign=0, hexpand=True, wrap=True)
        start = Gtk.Button(label="Start service")
        start.add_css_class("suggested-action")
        start.connect("clicked", self._start_daemon)
        self.offline.append(msg)
        self.offline.append(start)
        self.offline_revealer = Gtk.Revealer(child=self.offline)
        outer.append(self.offline_revealer)

        # sidebar | page, collapsing into one column (with a back button) when narrow
        self.split = Adw.NavigationSplitView(vexpand=True, min_sidebar_width=220, max_sidebar_width=280)
        outer.append(self.split)
        # not homogeneous: one wide page mustn't widen every other page
        self.stack = Gtk.Stack(hexpand=True, hhomogeneous=False,
                               transition_type=Gtk.StackTransitionType.CROSSFADE)
        # light/dark text per pane follows the window and what's in it
        self.stack.connect("notify::visible-child", lambda *_: GLib.timeout_add(350, self._retag_backdrop))
        for prop in ("notify::default-width", "notify::default-height", "notify::is-active", "notify::maximized"):
            self.connect(prop, lambda *_: GLib.timeout_add(200, self._retag_backdrop))
        side = Adw.ToolbarView(content=self._build_sidebar())
        side.add_top_bar(Adw.HeaderBar(show_title=False))
        self.split.set_sidebar(Adw.NavigationPage(child=side, title="ChoCaiDat", tag="sidebar"))
        content = Adw.ToolbarView(content=self.stack)
        self.content_header = Adw.HeaderBar()
        content.add_top_bar(self.content_header)
        self.content_page = Adw.NavigationPage(child=content, title="", tag="content")
        self.split.set_content(self.content_page)
        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        narrow.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(narrow)

        # Every page gets its place now; daemon pages are filled in once the
        # daemon's schema is available.
        self.slots: dict[str, Gtk.ScrolledWindow] = {}
        for _group, entries in NAV:
            for page_id, title, _icon in entries:
                slot = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
                if page_id.startswith("system:"):
                    # these lists can hold long names (Wi-Fi, devices): scroll, don't clip
                    slot.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
                    slot.set_child(_system_page(page_id.split(":", 1)[1]))
                elif page_id == "app:system":
                    from .pages.system import SystemPage
                    self.system_page = SystemPage(self)
                    slot.set_child(self.system_page)
                else:
                    waiting = Gtk.Label(label="Waiting for the settings service…")
                    waiting.add_css_class("dim-label")
                    slot.set_child(waiting)
                self.slots[page_id] = slot
                self.stack.add_named(slot, page_id)
        self.show_page(self.initial_page or NAV[0][1][0][0])

        # errors from the daemon (e.g. "file not found")
        self.error_label = Gtk.Label(xalign=0, hexpand=True, wrap=True)
        err_box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        err_box.append(self.error_label)
        close = Gtk.Button(icon_name="window-close-symbolic")
        close.add_css_class("flat")
        close.connect("clicked", lambda _b: self.error_revealer.set_reveal_child(False))
        err_box.append(close)
        err_box.add_css_class("error")
        self.error_revealer = Gtk.Revealer(child=err_box, transition_type=Gtk.RevealerTransitionType.SLIDE_UP)
        outer.append(self.error_revealer)
        self.set_content(self.toasts)

        Gio.bus_watch_name(Gio.BusType.SESSION, BUS_NAME, Gio.BusNameWatcherFlags.NONE,
                           self._on_daemon_appeared, self._on_daemon_vanished)

    # daemon lifecycle
    def _on_daemon_appeared(self, conn, _name, _owner) -> None:
        self.offline_revealer.set_reveal_child(False)
        self._set_daemon_pages_sensitive(True)
        if not self.pages:
            self._build_pages()
        self._refresh_all()
        self._signal_id = conn.signal_subscribe(
            BUS_NAME, INTERFACE, "Changed", OBJECT_PATH, None, Gio.DBusSignalFlags.NONE,
            lambda *a: self._refresh(a[5].unpack()[0]))

    def _on_daemon_vanished(self, conn, _name) -> None:
        self.offline_revealer.set_reveal_child(True)
        self._set_daemon_pages_sensitive(False)
        if conn is not None and getattr(self, "_signal_id", None):
            conn.signal_unsubscribe(self._signal_id)
            self._signal_id = None

    def _build_sidebar(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=8, margin_start=8, margin_end=8)
        box.set_size_request(220, -1)
        self.search = Gtk.SearchEntry(placeholder_text=_("Search settings"))
        self.search.connect("search-changed", lambda _e: self.nav.invalidate_filter())
        box.append(self.search)
        self.nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.nav.add_css_class("navigation-sidebar")
        self.nav_rows: dict[str, Gtk.ListBoxRow] = {}
        self.keywords: dict[str, str] = {}
        for group, entries in NAV:
            head = Gtk.ListBoxRow(activatable=False, selectable=False)
            head.add_css_class("nav-header")
            label = Gtk.Label(label=_(group), xalign=0, margin_top=10, margin_start=6)
            label.add_css_class("nav-group")
            head.set_child(label)
            head.is_header = True
            self.nav.append(head)
            for page_id, title, icon in entries:
                row = Gtk.ListBoxRow()
                line = Gtk.Box(spacing=10, margin_top=6, margin_bottom=6, margin_start=6)
                line.append(Gtk.Image.new_from_icon_name(icon))
                line.append(Gtk.Label(label=_(title), xalign=0))
                row.set_child(line)
                row.page_id, row.title, row.is_header = page_id, _(title), False
                self.nav.append(row)
                self.nav_rows[page_id] = row
                self.keywords[page_id] = f"{title} {PAGE_KEYWORDS.get(page_id, '')}".lower()
        self.nav.set_filter_func(self._nav_filter)
        self.nav.connect("row-selected", self._nav_selected)
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER, child=self.nav)
        box.append(scroll)
        return box

    def _nav_filter(self, row) -> bool:
        query = self.search.get_text().strip().lower()
        if not query:
            return True
        if row.is_header:
            return False
        return all(word in self.keywords.get(row.page_id, "") for word in query.split())

    def _nav_selected(self, _list, row) -> None:
        if row is not None and not row.is_header:
            self.stack.set_visible_child_name(row.page_id)
            self.content_page.set_title(row.title)
            self.split.set_show_content(True)  # collapsed: slide to the page

    def show_page(self, page_id: str | None) -> None:
        """Show a page by its id, or by the id of a section it contains."""
        page_id = SECTION_PAGE.get(page_id, page_id)
        row = self.nav_rows.get(page_id)
        if row is not None:
            self.nav.select_row(row)
            self.stack.set_visible_child_name(page_id)
            self.content_page.set_title(row.title)

    def _set_daemon_pages_sensitive(self, on: bool) -> None:
        for page_id, slot in self.slots.items():
            if ":" not in page_id:
                slot.set_sensitive(on)

    def open_assistant(self) -> None:
        from .pages.wizard import SetupAssistant
        SetupAssistant(self).present()

    def refresh_everything(self) -> None:
        self._refresh_all()

    def _start_daemon(self, _button) -> None:
        # Installed: systemd unit. Running from a source checkout: spawn it directly.
        if subprocess.run(["systemctl", "--user", "start", "swayctl-center.service"],
                          capture_output=True).returncode == 0:
            return
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
        subprocess.Popen([sys.executable, "-m", "swayctl_center", "daemon"], env=env,
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _build_pages(self) -> None:
        try:
            schema = self.client.get_schema()
        except (DaemonUnavailable, CallError) as e:
            self.show_error(str(e))
            return
        keys_by_section: dict[str, list] = {}
        for k in schema:
            k["label"] = _(k["label"])  # the one place every setting's label passes
            if k.get("help"):
                k["help"] = _(k["help"])
            keys_by_section.setdefault(k["section"], []).append(k)
        page_classes: dict[str, Callable[..., Page]] = {
            "background": lambda w, s, t: BackgroundPage(w, s, t, keys_by_section[s]),
            "appearance": lambda w, s, t: AppearancePage(w, s, t, keys_by_section[s]),
            "night_light": lambda w, s, t: NightLightPage(w, s, t, keys_by_section[s]),
            "location": lambda w, s, t: LocationPage(w, s, t, keys_by_section[s]),
            "effects": lambda w, s, t: EffectsPage(w, s, t, keys_by_section[s]),
            "auth": lambda w, s, t: AuthPage(w, s, t, keys_by_section[s]),
            "bar": lambda w, s, t: BarPage(w, s, t, keys_by_section[s]),
            "notifications": lambda w, s, t: NotificationsPage(w, s, t, keys_by_section[s]),
            "idle": lambda w, s, t: IdlePage(w, s, t, keys_by_section[s]),
            "clipboard": lambda w, s, t: ClipboardPage(w, s, t, keys_by_section[s]),
            "input_method": lambda w, s, t: InputMethodPage(w, s, t, keys_by_section[s]),
            "launcher": lambda w, s, t: LauncherPage(w, s, t, keys_by_section[s]),
            "outputs": OutputsPage,
            "keybindings": lambda w, s, t: KeybindingsPage(w, s, t, keys_by_section[s]),
            "autostart": lambda w, s, t: AutostartPage(w, s, t, keys_by_section[s]),
            "keyremap": lambda w, s, t: KeyRemapPage(w, s, t, keys_by_section[s]),
            "theming": lambda w, s, t: ThemedAppsPage(w, s, t, keys_by_section[s]),
        }
        def register(page, section=None):
            self.pages.setdefault(section or page.section, []).append(page)
            return page

        pointing = PointingPage(self, keys_by_section)
        for page in pointing.pieces:
            register(page)
        self.slots["pointing"].set_child(pointing)

        titles = {pid: t for _g, entries in NAV for pid, t, _i in entries}
        for page_id, parts in PAGES.items():
            composite = CompositePage(titles[page_id])
            for section, heading in parts:
                if section.startswith("system:"):
                    part = _system_page(section.split(":", 1)[1])
                elif section in keys_by_section:
                    factory = page_classes.get(section, lambda w, s, t: SchemaPage(w, s, t, keys_by_section[s]))
                    part = register(factory(self, section, heading or titles[page_id]))
                else:
                    continue
                composite.add_part(part, heading)
            self.slots[page_id].set_child(composite)
            for section, _h in parts:  # searchable by every setting on the page
                self.keywords[page_id] += " " + " ".join(
                    k["label"].lower() for k in keys_by_section.get(section, []) if not k.get("hidden"))
        for section in ("input.touchpad", "input.pointer", "scrolling"):
            self.keywords["pointing"] += " " + " ".join(
                k["label"].lower() for k in keys_by_section.get(section, []) if not k.get("hidden"))

        # System: which components the app runs, and startup apps
        system = self.system_page
        toggles = _list_box()
        for section in COMPONENT_NAMES:
            if section in keys_by_section:
                toggles.append(register(ComponentToggle(self, section), section))
        system.add_part("Components", "What ChoCaiDat runs for you. Turn one off to keep your own "
                                      "setup for it.", _frame(toggles))
        autostart = register(AutostartPage(self, "autostart", "Startup apps", keys_by_section["autostart"]))
        system.add_part("Startup apps", "", _as_part(autostart, ""))

    def _refresh_all(self) -> None:
        try:
            values = self.client.get_all()
            status = self.client.status()
        except (DaemonUnavailable, CallError) as e:
            self.show_error(str(e))
            return
        for section, pages in self.pages.items():
            for page in pages:
                page.update(values[section])
                page.update_status(status)

    def _refresh(self, section: str) -> None:
        try:
            if section in self.pages:
                values = self.client.get_all()[section]
                for page in self.pages[section]:
                    page.update(values)
            # status (active theme, resolved location, night light) can move
            # with changes to other sections, so refresh it everywhere
            status = self.client.status()
        except (DaemonUnavailable, CallError) as e:
            self.show_error(str(e))
            return
        for pages in self.pages.values():
            for page in pages:
                page.update_status(status)

    def action(self, name: str) -> None:
        try:
            self.client.action(name)
        except (DaemonUnavailable, CallError) as e:
            self.show_error(str(e))

    def set_swatch_colors(self, theme: dict[str, Any], status: dict[str, Any] | None = None) -> None:
        css = "".join(f".swatch-{r} {{ background: {theme[r]}; min-width: 28px; min-height: 20px; }}"
                      for r in ("bg", "fg", "accent", "muted"))
        if "tokens" in theme:
            # this window follows the active theme too, gtk.css option or not
            from .theming import adwaita_css
            css = adwaita_css(theme["tokens"]) + css + self._glass_css(theme, status)
            Adw.StyleManager.get_default().set_color_scheme(
                Adw.ColorScheme.FORCE_DARK if theme.get("dark") else Adw.ColorScheme.FORCE_LIGHT)
        if not hasattr(self, "_swatch_css"):
            self._swatch_css = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), self._swatch_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._swatch_css.load_from_string(css)

    def _glass_css(self, theme: dict[str, Any], status: dict[str, Any] | None) -> str:
        """Liquid glass like the bar's, when it's on and swayctl-fx can put
        glass behind windows (it does: effects sends the for_window rule)."""
        features = ((status or {}).get("compositor") or {}).get("features") or []
        if "glass-windows" not in features:
            self._backdrop = None
            return ""
        try:
            fx = self.client.get_all()["effects"]
        except (DaemonUnavailable, CallError, KeyError):
            return ""
        if not fx.get("glass"):
            self._backdrop = None
            return ""
        from .modules.components import adaptive_css, app_glass_css, shell_milk
        pct = fx.get("glass_opacity", 50)
        try:
            bg = self.client.get_all()["background"]
        except (DaemonUnavailable, CallError, KeyError):
            bg = {}
        # what's behind the window, for light/dark text per pane (_retag_backdrop)
        image = str(store_config_dir() / bg["image"]) if bg.get("image") else ""
        from .modules.components import glass_tint
        self._backdrop = (image, bg.get("mode", "fill"), bg.get("color") or theme.get("bg", "#000000"),
                          glass_tint(pct, True), glass_tint(pct, False))
        k = theme["tokens"]
        # same milk + same per-pane adaptive text as the bar, Quick Settings,
        # notifications and OSD (shell_milk / adaptive_css)
        return app_glass_css(k, shell_milk(pct, True)) + adaptive_css(pct, k["accent"], k["accent_fg"])

    def _retag_backdrop(self, *_args) -> bool:
        """Tag each pane of glass on-light / on-dark by the wallpaper behind it
        (tiled windows don't overlap: the wallpaper is what's behind)."""
        info = getattr(self, "_backdrop", None)
        if not info or not self.get_mapped():
            return GLib.SOURCE_REMOVE
        from . import backdrop
        try:
            ipc = swayipc.Connection()
            found = backdrop.window_on_output(ipc.request(swayipc.GET_TREE), APP_ID, ipc.get_outputs())
        except (swayipc.IPCError, OSError, KeyError):
            return GLib.SOURCE_REMOVE
        if not found:
            return GLib.SOURCE_REMOVE
        rect, out = found
        image, mode, color, tint_dark, tint_light = info
        g = backdrop.grid(image, mode, color, out["width"], out["height"])
        ox, oy = rect["x"] - out["x"], rect["y"] - out["y"]
        stack = [self]
        while stack:
            w = stack.pop()
            if w is not self and _is_glass_pane(w):
                ok, b = w.compute_bounds(self)
                if ok:
                    lum = backdrop.stats(g, out["width"], out["height"], ox + b.get_x(), oy + b.get_y(),
                                         b.get_width(), b.get_height())
                    dark, step = backdrop.choose(lum, tint_dark, tint_light)
                    for c in w.get_css_classes():
                        if c.startswith("tint-"):
                            w.remove_css_class(c)
                    w.remove_css_class("on-dark" if dark else "on-light")
                    w.add_css_class("on-light" if dark else "on-dark")
                    w.add_css_class(f"tint-{step}")
                continue
            child = w.get_first_child()
            while child is not None:
                stack.append(child)
                child = child.get_next_sibling()
        return GLib.SOURCE_REMOVE

    # actions used by pages
    def set(self, path: str, value: Any) -> bool:
        try:
            self.client.set(path, value)
        except (DaemonUnavailable, CallError) as e:
            self.show_error(str(e))
            self._refresh(path.rpartition(".")[0])  # put the control back
            return False
        self.error_revealer.set_reveal_child(False)
        return True

    def reset(self, path: str) -> None:
        try:
            self.client.reset(path)
        except (DaemonUnavailable, CallError) as e:
            self.show_error(str(e))

    def show_error(self, text: str) -> None:
        self.error_label.set_label(text)
        self.error_revealer.set_reveal_child(True)

    def notify(self, text: str) -> None:
        """A short confirmation that goes away by itself."""
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))


class SettingsApp(Adw.Application):
    def __init__(self, page: str | None = None):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.page = page

    def do_startup(self):
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        # Running from a checkout: the icon isn't installed into hicolor yet.
        local_icons = Path(__file__).resolve().parent.parent / "data" / "icons"
        if local_icons.is_dir():
            Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(local_icons))
        Gtk.Window.set_default_icon_name(APP_ID)

    def do_activate(self):
        win = self.get_active_window()
        first = win is None
        if first:
            win = SettingsWindow(self, self.page)
            # theme and glass before the first frame, not after the first poll
            try:
                status = win.client.status()
                win.set_swatch_colors(status["appearance"]["theme"], status)
            except (DaemonUnavailable, CallError, KeyError):
                pass
        elif self.page:
            win.show_page(self.page)
        win.present()
        if first:
            from .pages import ui_state
            if not ui_state.get("setup_done"):
                GLib.timeout_add(600, lambda: (win.open_assistant(), GLib.SOURCE_REMOVE)[1])


def main(page: str | None = None) -> int:
    GLib.set_prgname(APP_ID)  # app_id of every window, dialogs included
    return SettingsApp(page).run([sys.argv[0]])

"""Typed description of every setting swayctl-center owns ("type B" settings -
the ones no other daemon on the system is the source of truth for).

The schema is the single place that knows a setting's type, default, allowed
values and scope. The store validates against it, the daemon applies from it,
and UIs can fetch it over D-Bus (GetSchema) to build generic widgets.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable

SHARED = "shared"    # travels with export/import to another machine
MACHINE = "machine"  # hardware-specific, stays on this machine


@dataclass(frozen=True)
class Key:
    section: str
    name: str
    type: str  # "bool" | "int" | "float" | "enum" | "str" | "list" | "map"
    default: Any
    label: str
    choices: tuple[str, ...] = ()
    min: float | None = None
    max: float | None = None
    scope: str = SHARED
    pattern: str | None = None  # "str": full-match regex
    # "list"/"map": normalizes the whole value or raises ValueError
    validator: Callable[[Any], Any] | None = field(default=None, compare=False)
    hidden: bool = False  # managed by the app itself; not shown in the UI
    # "list"/"map": {field: type description} of one item, for UIs
    item_fields: tuple[tuple[str, str], ...] = ()
    item_type: str | None = None  # "list" of plain values, e.g. "str"
    choices_hint: tuple[str, ...] = ()  # allowed list items, for UIs
    help: str = ""  # one line under the label in the UI (filled from HELP below)

    @property
    def path(self) -> str:
        return f"{self.section}.{self.name}"

    def validate(self, value: Any) -> Any:
        """Return the value (normalized) or raise ValueError."""
        if self.type == "bool":
            if not isinstance(value, bool):
                raise ValueError(f"{self.path}: expected true/false, got {value!r}")
            return value
        if self.type == "str":
            if not isinstance(value, str):
                raise ValueError(f"{self.path}: expected a string, got {value!r}")
            if self.pattern is not None and not re.fullmatch(self.pattern, value):
                raise ValueError(f"{self.path}: invalid value {value!r}")
            return value
        if self.type in ("list", "map"):
            expected = list if self.type == "list" else dict
            if not isinstance(value, expected):
                raise ValueError(f"{self.path}: expected a {self.type}, got {type(value).__name__}")
            return self.validator(value) if self.validator else value
        if self.type == "enum":
            if value not in self.choices:
                raise ValueError(f"{self.path}: expected one of {', '.join(self.choices)}, got {value!r}")
            return value
        if self.type == "int":
            # whole floats from JSON/CLI/sliders (48.0) are fine; 48.113 is not
            if isinstance(value, bool):
                raise ValueError(f"{self.path}: expected an integer, got {value!r}")
            if isinstance(value, float):
                if value != int(value):
                    raise ValueError(f"{self.path}: expected an integer, got {value!r}")
                value = int(value)
            elif not isinstance(value, int):
                raise ValueError(f"{self.path}: expected an integer, got {value!r}")
        elif self.type == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{self.path}: expected a number, got {value!r}")
            value = float(value)
        else:
            raise ValueError(f"{self.path}: unknown type {self.type}")
        if self.min is not None and value < self.min:
            raise ValueError(f"{self.path}: must be >= {self.min}, got {value}")
        if self.max is not None and value > self.max:
            raise ValueError(f"{self.path}: must be <= {self.max}, got {value}")
        return value

    def to_json(self) -> dict[str, Any]:
        out = {
            "section": self.section, "name": self.name, "type": self.type,
            "default": self.default, "label": self.label, "scope": self.scope,
        }
        if self.choices:
            out["choices"] = list(self.choices)
        if self.min is not None:
            out["min"] = self.min
        if self.max is not None:
            out["max"] = self.max
        if self.item_fields:
            out["item_fields"] = dict(self.item_fields)
        if self.item_type:
            out["item_type"] = self.item_type
        if self.hidden:
            out["hidden"] = True
        if self.help:
            out["help"] = self.help
        if self.choices_hint:
            out["choices_hint"] = list(self.choices_hint)
        return out


_SCROLL_METHODS = ("two_finger", "edge", "on_button_down", "none")
_ACCEL_PROFILES = ("adaptive", "flat")
TRANSFORMS = ("normal", "90", "180", "270", "flipped", "flipped-90", "flipped-180", "flipped-270")
MODE_RE = r"\d+x\d+(@\d+(\.\d+)?Hz)?"
COLOR_RE = r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?"
HHMM_RE = r"([01]\d|2[0-3]):[0-5]\d"
BINDING_FLAGS = ("--release", "--locked", "--to-code", "--inhibited", "--no-repeat",
                 "--whole-window", "--border", "--exclude-titlebar")


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(msg)


def _nonempty_str(value: Any, what: str) -> str:
    _require(isinstance(value, str) and value.strip() != "", f"{what}: expected a non-empty string")
    return value.strip()


def validate_outputs(value: dict) -> dict:
    """{identifier: {enabled, mode, position, scale, transform, adaptive_sync}}"""
    out = {}
    for ident, cfg in value.items():
        where = f"outputs.config[{ident!r}]"
        _require(isinstance(ident, str) and ident.strip() != "", "outputs.config: empty output identifier")
        _require(isinstance(cfg, dict), f"{where}: expected an object")
        item = {
            "enabled": cfg.get("enabled", True),
            "mode": cfg.get("mode", ""),
            "position": cfg.get("position"),
            "scale": cfg.get("scale", 1.0),
            "transform": cfg.get("transform", "normal"),
            "adaptive_sync": cfg.get("adaptive_sync", False),
        }
        _require(isinstance(item["enabled"], bool), f"{where}.enabled: expected true/false")
        _require(isinstance(item["mode"], str) and (item["mode"] == "" or re.fullmatch(MODE_RE, item["mode"])),
                 f"{where}.mode: expected WIDTHxHEIGHT[@RATEHz], got {item['mode']!r}")
        pos = item["position"]
        _require(pos is None or (isinstance(pos, list) and len(pos) == 2
                                 and all(isinstance(n, int) and not isinstance(n, bool) for n in pos)),
                 f"{where}.position: expected [x, y] or null")
        scale = item["scale"]
        _require(isinstance(scale, (int, float)) and not isinstance(scale, bool) and 0.25 <= scale <= 10,
                 f"{where}.scale: expected a number between 0.25 and 10")
        item["scale"] = float(scale)
        _require(item["transform"] in TRANSFORMS, f"{where}.transform: expected one of {', '.join(TRANSFORMS)}")
        _require(isinstance(item["adaptive_sync"], bool), f"{where}.adaptive_sync: expected true/false")
        if "name" in cfg:  # connector last seen on (eDP-1, HDMI-A-1...), informational
            item["name"] = _nonempty_str(cfg["name"], f"{where}.name")
        out[ident.strip()] = item
    return out


def validate_bindings(value: list) -> list:
    """[{keys, command, flags}] - later entries win for the same keys+flags."""
    seen: dict[tuple, dict] = {}
    for i, b in enumerate(value):
        where = f"keybindings.bindings[{i}]"
        _require(isinstance(b, dict), f"{where}: expected an object")
        keys = _nonempty_str(b.get("keys"), f"{where}.keys")
        _require(not any(c.isspace() for c in keys), f"{where}.keys: must not contain spaces")
        command = _nonempty_str(b.get("command"), f"{where}.command")
        flags = b.get("flags", [])
        _require(isinstance(flags, list) and all(f in BINDING_FLAGS for f in flags),
                 f"{where}.flags: allowed flags are {', '.join(BINDING_FLAGS)}")
        flags = sorted(set(flags))
        seen[(keys.lower(), tuple(flags))] = {"keys": keys, "command": command, "flags": flags}
    return list(seen.values())


_KEY_NAME = re.compile(r"[a-z0-9_]+")


def validate_remaps(value: list) -> list:
    """[{from, to, swap}] keyd key names; one entry per "from" key (a swap
    counts for both of its keys), later entries win."""
    out: list[dict] = []
    for i, r in enumerate(value):
        where = f"keyremap.remaps[{i}]"
        _require(isinstance(r, dict), f"{where}: expected an object")
        src, dst = (_nonempty_str(r.get(k), f"{where}.{k}").strip().lower() for k in ("from", "to"))
        for k, name in (("from", src), ("to", dst)):
            _require(_KEY_NAME.fullmatch(name) is not None, f"{where}.{k}: not a key name: {name}")
        _require(src != dst, f"{where}: a key can't be mapped to itself")
        swap = bool(r.get("swap", False))
        taken = {src, dst} if swap else {src}
        out = [o for o in out if not ({o["from"], o["to"]} if o["swap"] else {o["from"]}) & taken]
        out.append({"from": src, "to": dst, "swap": swap})
    return out


WAYBAR_MODULES = ("sway/workspaces", "sway/mode", "sway/window", "sway/scratchpad", "clock",
                  "tray", "pulseaudio", "network", "bluetooth", "battery", "backlight", "cpu",
                  "memory", "temperature", "idle_inhibitor", "power-profiles-daemon",
                  "keyboard-state", "custom/notifications")


_MODULE_RE = re.compile(r"[a-z][\w-]*(/[\w.-]+)?(#[\w.-]+)?")

# swayctl-bar's modules; "status" is the one Quick Settings button
BAR_MODULES = ("workspaces", "mode", "window", "clock", "tray", "status")
# waybar module -> swayctl-bar module, for settings saved before (anything
# status-like becomes the Quick Settings button; others have no equivalent)
LEGACY_BAR_MODULES = {"sway/workspaces": "workspaces", "sway/mode": "mode", "sway/window": "window"}
LEGACY_STATUS_MODULES = {"pulseaudio", "wireplumber", "network", "battery", "bluetooth", "backlight",
                         "power-profiles-daemon", "idle_inhibitor", "custom/notifications", "cpu", "memory"}


def bar_module(name: str) -> str | None:
    """A module name as swayctl-bar knows it (old waybar names converted), or None."""
    base = name.split("#")[0]
    if base in BAR_MODULES:
        return base
    if base in LEGACY_BAR_MODULES:
        return LEGACY_BAR_MODULES[base]
    if base in LEGACY_STATUS_MODULES:
        return "status"
    return None


def strftime_format(fmt: str) -> str:
    """waybar's "{:%H:%M}" -> "%H:%M"; strftime formats stay as they are."""
    return re.sub(r"\{:([^}]*)\}", r"\1", fmt)


def validate_bar_modules(value: list) -> list:
    """swayctl-bar modules, in order, each once. Old waybar names are converted
    (so settings saved before still load); ones it has no equivalent for drop."""
    out = []
    for m in value:
        _require(isinstance(m, str), f"bar: {m!r} is not a module name")
        native = bar_module(m)
        if native and native not in out:
            out.append(native)
    return out


def validate_templates(value: list) -> list:
    """[{template, output, reload}] - files rendered with theme placeholders."""
    out = []
    for i, t in enumerate(value):
        where = f"theming.templates[{i}]"
        _require(isinstance(t, dict), f"{where}: expected an object")
        reload = t.get("reload", "")
        _require(isinstance(reload, str), f"{where}.reload: expected a command or \"\"")
        enabled = t.get("enabled", True)
        _require(isinstance(enabled, bool), f"{where}.enabled: expected true/false")
        out.append({"template": _nonempty_str(t.get("template"), f"{where}.template"),
                    "output": _nonempty_str(t.get("output"), f"{where}.output"),
                    "reload": reload.strip(), "enabled": enabled})
    return out


def validate_folders(value: list) -> list:
    """Folder paths (~ allowed), without duplicates."""
    out = []
    for i, f in enumerate(value):
        f = _nonempty_str(f, f"folders[{i}]")
        _require(f.startswith(("/", "~")), f"{f!r}: expected a full path (starting with / or ~)")
        if f not in out:
            out.append(f)
    return out


PRIORITY_TIERS = ("ui", "interactive", "background", "batch")
PRIORITY_FIELDS = ("name", "cmdline")


def validate_priority_rules(value: list) -> list:
    """[{match, field, tier, enabled}] - `match` is a regular expression."""
    out = []
    for i, r in enumerate(value):
        where = f"priority.rules[{i}]"
        _require(isinstance(r, dict), f"{where}: expected an object")
        match = _nonempty_str(r.get("match"), f"{where}.match")
        try:
            re.compile(match)
        except re.error as e:
            raise ValueError(f"{where}.match: not a valid pattern ({e})") from None
        fld, tier, enabled = r.get("field", "name"), r.get("tier"), r.get("enabled", True)
        _require(fld in PRIORITY_FIELDS, f"{where}.field: expected one of {', '.join(PRIORITY_FIELDS)}")
        _require(tier in PRIORITY_TIERS, f"{where}.tier: expected one of {', '.join(PRIORITY_TIERS)}")
        _require(isinstance(enabled, bool), f"{where}.enabled: expected true/false")
        out.append({"match": match, "field": fld, "tier": tier, "enabled": enabled})
    return out


def validate_priority_protect(value: list) -> list:
    """Process names that are never touched."""
    out = []
    for i, n in enumerate(value):
        _require(isinstance(n, str) and n.strip() != "" and not re.search(r"\s", n.strip()),
                 f"priority.protect[{i}]: expected a process name without spaces")
        if n.strip() not in out:
            out.append(n.strip())
    return out


def _rule(match: str, tier: str, field: str = "name") -> dict:
    return {"match": match, "field": field, "tier": tier, "enabled": True}


# What slows the desktop down by default: builds wait behind everything, the
# language server and indexers behind the program in use.
PRIORITY_DEFAULT_RULES = [
    _rule(r"org\.codehaus\.plexus\.classworlds|org\.apache\.maven\.cli", "batch", "cmdline"),   # mvn
    _rule(r"org\.gradle\.launcher|GradleDaemon|gradle-wrapper", "batch", "cmdline"),
    _rule(r"^(cargo|rustc|cc1|cc1plus|gcc|g\+\+|clang|clang\+\+|ld|ld\.lld|lld|mold|make|ninja|cmake|ccache)$", "batch"),
    _rule(r"^(makepkg|paru|yay)$", "batch"),
    _rule(r"org\.eclipse\.jdt\.ls|org\.eclipse\.equinox\.launcher", "background", "cmdline"),   # jdtls
    _rule(r"^(rust-analyzer|activity-tracker.*|baloo.*|tracker-miner.*)$", "background"),
    # What you look at and type into goes ahead of normal work. Both tiers only ever raise a program
    # (one that already has more priority keeps it), and what such a program starts is not raised too.
    # "ui" is above what a favored app starts: those are born with the app's priority.
    _rule(r"^swayctl-bar$", "ui"),                                      # bar, Quick Settings, notifications
    _rule(r"^(fuzzel|walker|elephant|mako|swaync|dunst)$", "ui"),       # launcher and notification servers
    # terminals and editors
    _rule(r"^(kitty|foot|alacritty|wezterm-gui|ghostty|nvim)$", "interactive"),
    # the browser itself and its graphics process - not its tabs: the one in view can't be told apart
    _rule(r"^/opt/google/chrome/chrome(?!.*--type=)", "interactive", "cmdline"),
    _rule(r"^/opt/google/chrome/chrome .*--type=gpu-process", "interactive", "cmdline"),
    _rule(r"^(firefox|chromium)$", "interactive"),
]
# the programs that draw the screen, take input and play sound: never touched
PRIORITY_DEFAULT_PROTECT = ["sway", "swayctl-fx", "swayctl-lock", "swayctl-center",
                            "Xwayland", "pipewire", "pipewire-pulse", "wireplumber", "fcitx5",
                            "systemd", "dbus-broker", "dbus-daemon"]


FONT_WEIGHTS = ("thin", "light", "regular", "medium", "semibold", "bold", "heavy")
SEARCH_ENGINES = ("google", "duckduckgo", "bing", "brave", "startpage", "youtube")


def validate_autostart(value: list) -> list:
    """[{command, enabled}]"""
    out = []
    for i, a in enumerate(value):
        where = f"autostart.commands[{i}]"
        _require(isinstance(a, dict), f"{where}: expected an object")
        enabled = a.get("enabled", True)
        _require(isinstance(enabled, bool), f"{where}.enabled: expected true/false")
        out.append({"command": _nonempty_str(a.get("command"), f"{where}.command"), "enabled": enabled})
    return out


KEYS: tuple[Key, ...] = (
    # layout - window borders and gaps
    Key("layout", "window_style", "enum", "compact", "Window style", choices=("compact", "balanced", "spacious", "custom")),
    Key("layout", "border", "int", 2, "Window border", min=0, max=50),
    Key("layout", "floating_border", "int", 2, "Floating window border", min=0, max=50),
    Key("layout", "gaps_inner", "int", 0, "Inner gaps", min=0, max=200),  # the interface style sets it; change it after
    Key("layout", "gaps_outer", "int", 0, "Outer gaps", min=0, max=200),  # the interface style sets it; change it after
    Key("layout", "smart_gaps", "enum", "off", "Smart gaps", choices=("on", "off", "inverse_outer")),
    Key("layout", "border_style", "enum", "pixel", "Window border style", choices=("pixel", "normal", "none")),
    Key("layout", "focus_follows_mouse", "enum", "yes", "Focus follows mouse", choices=("yes", "no", "always")),
    Key("layout", "mouse_warping", "enum", "output", "Move pointer to focused window",
        choices=("output", "container", "none")),
    Key("layout", "focus_on_window_activation", "enum", "urgent", "When a window asks for attention",
        choices=("smart", "urgent", "focus", "none")),
    Key("layout", "workspace_auto_back_and_forth", "bool", False, "Switch back to the previous workspace"),
    Key("layout", "hide_edge_borders", "enum", "none", "Hide edge borders",
        choices=("none", "vertical", "horizontal", "both", "smart", "smart_no_gaps")),

    # input - touchpad
    Key("input.touchpad", "tap", "bool", False, "Tap to click"),
    Key("input.touchpad", "dwt", "bool", True, "Disable while typing"),
    Key("input.touchpad", "natural_scroll", "bool", False, "Natural scroll direction"),
    Key("input.touchpad", "scroll_method", "enum", "two_finger", "Scroll with", choices=_SCROLL_METHODS),
    Key("input.touchpad", "accel_profile", "enum", "adaptive", "Acceleration profile", choices=_ACCEL_PROFILES),
    Key("input.touchpad", "pointer_accel", "float", 0.0, "Pointer speed", min=-1.0, max=1.0),
    Key("input.touchpad", "scroll_factor", "float", 1.0, "Scroll speed", min=0.1, max=5.0),
    Key("input.touchpad", "click_method", "enum", "button_areas", "Click method",
        choices=("button_areas", "clickfinger", "none")),
    Key("input.touchpad", "tap_button_map", "enum", "lrm", "Two/three-finger tap", choices=("lrm", "lmr")),
    Key("input.touchpad", "drag", "bool", True, "Tap and drag"),
    Key("input.touchpad", "drag_lock", "bool", False, "Drag lock"),
    Key("input.touchpad", "middle_emulation", "bool", False, "Middle click (left + right)"),
    Key("input.touchpad", "left_handed", "bool", False, "Left-handed"),
    Key("input.touchpad", "events", "enum", "enabled", "Touchpad",
        choices=("enabled", "disabled", "disabled_on_external_mouse")),

    # input - mouse
    Key("input.pointer", "natural_scroll", "bool", False, "Natural scroll direction"),
    Key("input.pointer", "accel_profile", "enum", "adaptive", "Acceleration profile", choices=_ACCEL_PROFILES),
    Key("input.pointer", "pointer_accel", "float", 0.0, "Pointer speed", min=-1.0, max=1.0),
    Key("input.pointer", "scroll_factor", "float", 1.0, "Scroll speed", min=0.1, max=5.0),
    Key("input.pointer", "left_handed", "bool", False, "Left-handed"),
    Key("input.pointer", "middle_emulation", "bool", False, "Middle click (left + right)"),

    # smooth scrolling (swayctl-center's smoothscroll service); when it's off or
    # not installed, the touchpad/mouse scroll settings above apply instead
    Key("scrolling", "profile", "enum", "smooth", "Smooth scrolling", choices=("off", "light", "smooth", "fluid")),
    Key("scrolling", "page_keys", "bool", True, "Smooth Page Up and Page Down"),
    Key("scrolling", "page_share", "float", 0.5, "How far Page Up and Page Down go", min=0.1, max=2.0),
    Key("scrolling", "browser_scale", "float", 0.6, "Scroll speed in Chrome and Electron apps", min=0.1, max=2.0),
    Key("scrolling", "touchpad_smooth", "bool", True, "Smooth scrolling", hidden=True),
    Key("scrolling", "touchpad_natural", "bool", True, "Natural scroll direction"),
    Key("scrolling", "touchpad_speed", "float", 1.2, "Scroll speed", min=0.2, max=5.0),
    Key("scrolling", "touchpad_glide", "float", 0.98, "Glide", min=0.90, max=0.995),
    Key("scrolling", "touchpad_ramp_ms", "float", 290.0, "Ease-in time (ms)", min=0.0, max=1000.0),
    Key("scrolling", "touchpad_smoothing", "float", 0.4, "Smoothness", min=0.05, max=1.0),
    Key("scrolling", "touchpad_ramp_power", "float", 1.9, "Ease-in curve", min=0.3, max=4.0, hidden=True),
    Key("scrolling", "touchpad_min_velocity", "float", 7.0, "Stop threshold", min=0.5, max=50.0, hidden=True),
    Key("scrolling", "mouse_smooth", "bool", True, "Smooth scrolling", hidden=True),
    Key("scrolling", "mouse_natural", "bool", False, "Natural scroll direction"),
    Key("scrolling", "mouse_speed", "float", 0.45, "Scroll speed", min=0.05, max=4.0),
    Key("scrolling", "mouse_glide", "float", 0.98, "Glide", min=0.90, max=0.995),
    Key("scrolling", "mouse_smoothing", "float", 0.99, "Smoothness", min=0.05, max=1.0),
    Key("scrolling", "mouse_ramp_floor", "float", 0.45, "First notch strength", min=0.0, max=1.0, hidden=True),
    Key("scrolling", "mouse_ramp_ms", "float", 290.0, "Ease-in time (ms)", min=0.0, max=1000.0, hidden=True),
    Key("scrolling", "mouse_ramp_power", "float", 0.8, "Ease-in curve", min=0.3, max=4.0, hidden=True),
    Key("scrolling", "mouse_min_velocity", "float", 4.5, "Stop threshold", min=0.5, max=50.0, hidden=True),
    Key("scrolling", "mouse_burst_reset_ms", "float", 400.0, "Pause that restarts ease-in (ms)",
        min=50.0, max=2000.0, hidden=True),
    Key("scrolling", "mouse_auto_release_ms", "float", 180.0, "Glide starts after (ms)", min=20.0, max=1000.0,
        hidden=True),

    # keyboard
    Key("input.keyboard", "xkb_layout", "str", "us", "Layouts (comma separated, e.g. us,vn)",
        pattern=r"[\w,()-]+"),
    Key("input.keyboard", "xkb_variant", "str", "", "Variants", pattern=r"[\w,()-]*"),
    Key("input.keyboard", "xkb_options", "str", "", "Options (e.g. caps:escape,grp:alt_shift_toggle)",
        pattern=r"[\w,:()+-]*"),
    Key("input.keyboard", "repeat_delay", "int", 600, "Key repeat delay (ms)", min=100, max=2000),
    Key("input.keyboard", "repeat_rate", "int", 25, "Key repeat rate (per second)", min=1, max=100),

    # displays - keyed by "make model serial" so a monitor keeps its config on any port
    # the monitor treated as the main one ("make model serial", "" = the built-in screen, else the first)
    Key("outputs", "primary", "str", "", "Main display", scope=MACHINE, hidden=True),
    Key("outputs", "config", "map", {}, "Displays", scope=MACHINE, validator=validate_outputs,
        item_fields=(("enabled", "bool"), ("mode", "str"), ("position", "[int, int] | null"),
                     ("scale", "float"), ("transform", "enum"), ("adaptive_sync", "bool"))),

    # color theme and when it switches between its light and dark variant
    # SwayFX (swayctl-fx) only; kept and applied whenever that compositor runs
    Key("effects", "corner_radius", "int", 0, "Rounded window corners", min=0, max=40),
    Key("effects", "shadow_style", "enum", "off", "Shadows", choices=("off", "soft", "deep", "custom")),
    Key("effects", "shadows", "bool", False, "Window shadows"),
    Key("effects", "shadow_blur_radius", "int", 20, "Shadow softness", min=0, max=99),
    Key("effects", "shadow_offset_x", "int", 0, "Shadow shift sideways", min=-40, max=40),
    Key("effects", "shadow_offset_y", "int", 0, "Shadow drop", min=-40, max=40),
    Key("effects", "shadow_inactive", "int", 100, "Shadow of unfocused windows", min=0, max=100),
    Key("effects", "shadows_on_csd", "bool", False, "Shadow on windows that draw their own"),
    Key("effects", "blur", "bool", False, "Blur behind see-through windows", hidden=True),
    Key("effects", "blur_passes", "int", 2, "Blur strength", min=0, max=10, hidden=True),
    Key("effects", "blur_radius", "int", 5, "Blur spread", min=0, max=10, hidden=True),
    Key("effects", "dim_inactive", "float", 0.0, "Dim unfocused windows", min=0.0, max=1.0),
    Key("effects", "panels", "bool", False, "Blur and shadow under the bar, notifications and launcher", hidden=True),
    Key("effects", "glass", "bool", False, "Liquid glass popups", hidden=True),
    # There are no glass settings: one look for every pane of glass (swayctl_center/glass.py). The keys below are
    # kept so stored settings still load; nothing reads them.
    Key("effects", "glass_refraction", "int", 50, "Glass refraction", min=0, max=140, hidden=True),
    Key("effects", "glass_opacity", "int", 10, "Glass tint (%)", min=0, max=90, hidden=True),
    Key("effects", "glass_blur", "int", 0, "Glass frost (%)", min=0, max=100, hidden=True),
    Key("effects", "glass_highlight", "float", 0.90, "Glass specular", min=0.0, max=1.0, hidden=True),
    Key("effects", "glass_edge", "int", 100, "Glass bezel (% of the corners)", min=10, max=300, hidden=True),
    Key("effects", "glass_thickness", "int", 90, "Glass thickness (px)", min=0, max=1500, hidden=True),
    Key("effects", "glass_chroma", "float", 0.35, "Glass dispersion", min=0.0, max=1.0, hidden=True),
    Key("effects", "animations", "bool", False, "Window animations", hidden=True),  # retired master switch: one switch per kind now
    # each kind on its own (swayctl-fx "animation-kinds"); one speed for all
    Key("effects", "anim_feel", "enum", "off", "Animation feel",
        choices=("off", "subtle", "smooth", "playful", "quick", "custom")),
    Key("effects", "anim_open_close", "bool", False, "Opening and closing apps"),
    Key("effects", "anim_workspace", "bool", False, "Switching workspaces"),
    Key("effects", "anim_move", "bool", False, "Moving and resizing windows"),
    # the Quick Settings popup (swayctl-bar): opens as a drop of glass, closes back into the button
    Key("effects", "anim_quick", "bool", False, "Popups opening and closing"),
    # swayctl-fx "animation-slide": workspaces slide sideways instead of fading into each other
    Key("effects", "anim_slide", "bool", True, "Workspaces slide"),
    Key("effects", "anim_duration", "int", 200, "Animation length (ms)", min=80, max=800),
    # swayctl-fx "animation-spring": a spring that keeps its speed when the target moves, instead of
    # the fixed ease-out curve; response = pace, bounce = how far it overshoots and settles back
    Key("effects", "anim_curve", "enum", "spring", "Animation curve", choices=("ease", "spring")),
    Key("effects", "anim_response", "int", 340, "Spring pace (ms)", min=120, max=800),
    Key("effects", "anim_bounce", "int", 8, "Spring bounce (%)", min=0, max=40),
    Key("effects", "anim_close_pace", "int", 70, "Closing takes (% of opening)", min=30, max=100),
    Key("effects", "anim_close_bounce", "int", 0, "Bounce when closing (%)", min=0, max=40),
    Key("effects", "anim_popin", "int", 94, "Windows open from (% of their size)", min=70, max=100),
    Key("effects", "anim_fade", "int", 150, "Fade ahead of the motion (%)", min=100, max=300),
    # fingerprint (fprintd) unlock; written to PAM only when applied from the app
    Key("auth", "fingerprint_lock", "bool", False, "Fingerprint: unlock the screen"),
    Key("auth", "fingerprint_sudo", "bool", False, "Fingerprint: sudo"),
    Key("auth", "fingerprint_polkit", "bool", False, "Fingerprint: admin prompts"),
    Key("auth", "fingerprint_login", "bool", False, "Fingerprint: log in"),
    Key("auth", "face_lock", "bool", False, "Face: unlock the screen"),
    Key("auth", "face_sudo", "bool", False, "Face: sudo"),
    Key("auth", "face_polkit", "bool", False, "Face: admin prompts"),
    Key("auth", "lock_screen", "enum", "swayctl-lock", "Lock screen", choices=("swaylock", "swayctl-lock"),
        hidden=True),
    Key("appearance", "mode", "enum", "auto", "Appearance", choices=("light", "dark", "auto")),
    # only "light" and "dark" now; kept (hidden) for themes files people made
    Key("appearance", "light_theme", "str", "light", "Light theme", pattern=r"[\w.-]+", hidden=True),
    Key("appearance", "dark_theme", "str", "dark", "Dark theme", pattern=r"[\w.-]+", hidden=True),
    Key("appearance", "schedule", "enum", "sun", "Switch automatically", choices=("sun", "custom")),
    Key("appearance", "light_at", "str", "07:00", "Light from", pattern=HHMM_RE),
    Key("appearance", "dark_at", "str", "19:00", "Dark from", pattern=HHMM_RE),
    Key("appearance", "ui_style", "enum", "rounded", "Interface style", choices=("flat", "floating", "rounded", "liquid", "glass", "frame", "minimal")),
    # frame style: the bar and the space around the windows are one solid colour, no blur
    Key("appearance", "frame_color", "str", "#0b1014", "Frame color", pattern=r"#[0-9a-fA-F]{6}"),
    # frame style: solid colour, or one pane of liquid glass over the wallpaper (the bar, the edges and the gaps)
    # Quick Settings, the volume/brightness pill and the launcher as plain blocks (no glass, no blur) in a tone taken from the frame colour
    Key("appearance", "quick_surface", "enum", "auto", "Popup surface", choices=("auto", "flat")),
    Key("appearance", "style", "enum", "modern", "Style", choices=("classic", "modern"), hidden=True),
    Key("appearance", "gtk_css", "bool", False, "Theme colors in GTK 4 apps"),
    Key("appearance", "apps_follow", "bool", True, "Terminals, GTK 3 and Qt apps follow light/dark"),

    # where "sunrise/sunset" is computed for; by default guessed from the timezone
    Key("location", "source", "enum", "timezone", "Location", choices=("timezone", "manual"), scope=MACHINE),
    Key("location", "latitude", "float", 0.0, "Latitude", min=-90.0, max=90.0, scope=MACHINE),
    Key("location", "longitude", "float", 0.0, "Longitude", min=-180.0, max=180.0, scope=MACHINE),

    # blue-light filter (wlsunset)
    Key("night_light", "mode", "enum", "off", "Night light", choices=("off", "always", "sun", "custom")),
    Key("night_light", "temperature", "int", 4000, "Color temperature (K)", min=1500, max=6400),
    Key("night_light", "start", "str", "20:00", "Turn on at", pattern=HHMM_RE),
    Key("night_light", "end", "str", "07:00", "Turn off at", pattern=HHMM_RE),

    # wallpaper - images are copied into the app's own folder so export/import carries them
    Key("background", "image", "str", "", "Wallpaper image"),
    Key("background", "mode", "enum", "fill", "Wallpaper fit",
        choices=("fill", "fit", "stretch", "center", "tile")),
    # a video that plays as the wallpaper (the Glass desk style plays its own when this is empty)
    Key("background", "video", "str", "", "Video wallpaper"),
    # "" = the current theme's background color
    Key("background", "color", "str", "", "Background color", pattern=f"({COLOR_RE})?"),

    # fonts - window titles (sway) and the GTK interface/monospace fonts
    Key("font", "family", "str", "sans-serif", "Interface font", pattern=r".*\S.*"),
    Key("font", "weight", "enum", "regular", "Interface font weight", choices=FONT_WEIGHTS),
    Key("font", "size", "int", 10, "Interface font size", min=6, max=48),
    Key("font", "monospace_family", "str", "monospace", "Monospace font", pattern=r".*\S.*"),
    Key("font", "monospace_weight", "enum", "regular", "Monospace font weight", choices=FONT_WEIGHTS),
    Key("font", "monospace_size", "int", 10, "Monospace font size", min=6, max=48),

    # keyboard shortcuts - "$mod" in keys is replaced by the modifier setting
    Key("keybindings", "modifier", "enum", "Mod4", "Main modifier key",
        choices=("Mod4", "Mod1", "Control", "Mod3", "Mod5")),
    Key("keybindings", "bindings", "list", [], "Keyboard shortcuts", validator=validate_bindings,
        item_fields=(("keys", "str"), ("command", "str"), ("flags", "list[str]"))),

    # shell components. "managed": swayctl-center runs it (with its own config,
    # themed); otherwise it's left to the user's own setup.
    Key("bar", "managed", "bool", True, "Managed by swayctl-center"),
    Key("bar", "program", "enum", "swayctl-bar", "Bar program", choices=("waybar", "swayctl-bar"), hidden=True),
    Key("bar", "position", "enum", "top", "Position", choices=("top", "bottom", "left", "right")),
    # the bar's own drawn set (the iPadOS manner: a Wi-Fi fan, a filled battery) or the icon theme's
    Key("bar", "icon_style", "enum", "ipados", "Icon style", choices=("ipados", "system")),
    Key("bar", "layer", "enum", "top", "Layer", choices=("top", "bottom", "overlay"), hidden=True),
    Key("bar", "height", "int", 30, "Bar size", min=0, max=80),
    Key("bar", "padding", "int", 10, "Padding (px)", min=0, max=24, hidden=True),  # set by the interface style
    Key("bar", "shape", "enum", "pieces", "Style", choices=("pieces", "single"), hidden=True),  # set by the interface style
    Key("bar", "spacing", "int", 4, "Space between modules", min=0, max=64, hidden=True),
    Key("bar", "margin_top", "int", 0, "Margin top", min=0, max=200, hidden=True),
    Key("bar", "margin_right", "int", 0, "Margin right", min=0, max=200, hidden=True),
    Key("bar", "margin_bottom", "int", 0, "Margin bottom", min=0, max=200, hidden=True),
    Key("bar", "margin_left", "int", 0, "Margin left", min=0, max=200, hidden=True),
    Key("bar", "exclusive", "bool", True, "Keep windows from covering the bar", hidden=True),
    Key("bar", "modules_left", "list", ["workspaces", "mode"], "Left",
        validator=validate_bar_modules, item_type="str", choices_hint=BAR_MODULES),
    Key("bar", "modules_center", "list", ["clock"], "Center",
        validator=validate_bar_modules, item_type="str", choices_hint=BAR_MODULES),
    Key("bar", "modules_right", "list", ["tray", "status"],
        "Right", validator=validate_bar_modules, item_type="str", choices_hint=BAR_MODULES),
    Key("bar", "clock_format", "str", "%H:%M", "Clock format", pattern=r".*\S.*"),
    Key("bar", "clock_format_alt", "str", "%a %d %b  %H:%M", "Clock tooltip format", pattern=r".*\S.*", hidden=True),
    Key("bar", "theme", "str", "", "Bar colors", pattern=r"[\w.-]*", hidden=True),
    # your own waybar config as the base (module definitions, custom modules);
    # the settings above are applied on top of it
    Key("bar", "config_file", "str", "", "Base config", hidden=True),
    Key("bar", "style_template", "str", "", "Style template", hidden=True),

    Key("notifications", "managed", "bool", True, "Managed by swayctl-center"),
    # swayctl-bar shows notifications itself; swaync only for the old setup
    Key("notifications", "program", "enum", "swayctl-bar", "Notification program",
        choices=("swayctl-bar", "swaync"), hidden=True),
    Key("notifications", "max_visible", "int", 4, "Pop-ups on screen at once", min=1, max=10),
    Key("notifications", "dnd_on_start", "bool", False, "Do not disturb when logging in"),
    Key("notifications", "position_x", "enum", "right", "Horizontal position", choices=("left", "center", "right")),
    Key("notifications", "position_y", "enum", "top", "Vertical position", choices=("top", "center", "bottom")),
    Key("notifications", "output", "str", "", "Show on monitor", pattern=r"[\w.-]*"),
    Key("notifications", "layer", "enum", "overlay", "Pop-ups show above", choices=("overlay", "top"), hidden=True),
    Key("notifications", "width", "int", 400, "Pop-up width", min=200, max=1200),
    Key("notifications", "control_center_width", "int", 500, "Notification center width", min=200, max=1600, hidden=True),
    Key("notifications", "control_center_height", "int", 600, "Notification center height", min=200, max=2000, hidden=True),
    Key("notifications", "fit_to_screen", "bool", True, "Notification center fills the screen height", hidden=True),
    Key("notifications", "timeout", "int", 8, "Hide after (seconds)", min=1, max=120),
    Key("notifications", "timeout_low", "int", 4, "Hide low-priority after (seconds)", min=1, max=120),
    Key("notifications", "timeout_critical", "int", 0, "Hide critical after (seconds, 0 = never)", min=0, max=600),
    Key("notifications", "grouping", "bool", True, "Group notifications by app", hidden=True),
    Key("notifications", "relative_timestamps", "bool", True, "Relative times (5 min ago)", hidden=True),
    Key("notifications", "image_visibility", "enum", "when-available", "Show images",
        choices=("always", "when-available", "never"), hidden=True),
    Key("notifications", "hide_on_clear", "bool", False, "Close the center after Clear all", hidden=True),
    Key("notifications", "hide_on_action", "bool", True, "Close the center after an action", hidden=True),
    Key("notifications", "keyboard_shortcuts", "bool", True, "Keyboard shortcuts in the center", hidden=True),
    Key("notifications", "config_file", "str", "", "Base config", hidden=True),
    Key("notifications", "style_template", "str", "", "Style template", hidden=True),

    Key("idle", "managed", "bool", True, "Managed by swayctl-center"),
    Key("idle", "lock_after", "int", 300, "Lock screen after (seconds, 0 = never)", min=0, max=14400),
    Key("idle", "screen_off_after", "int", 600, "Turn screen off after (seconds, 0 = never)", min=0, max=14400),
    Key("idle", "suspend_after", "int", 0, "Suspend after (seconds, 0 = never)", min=0, max=86400),
    Key("idle", "lock_before_sleep", "bool", True, "Lock before suspend"),
    Key("idle", "lock_background", "enum", "color", "Lock screen background", choices=("color", "wallpaper"), hidden=True),
    Key("idle", "show_failed_attempts", "bool", False, "Show failed attempts", hidden=True),
    Key("idle", "ignore_empty_password", "bool", False, "Ignore Enter with an empty password", hidden=True),

    Key("clipboard", "managed", "bool", True, "Managed by swayctl-center"),
    Key("clipboard", "max_items", "int", 750, "History size", min=10, max=100000),
    Key("clipboard", "images", "bool", True, "Keep images"),
    Key("clipboard", "persist", "bool", True, "Keep copied text after the app closes (wl-clip-persist)"),

    Key("input_method", "managed", "bool", False, "Run fcitx5 (Vietnamese, Chinese, Japanese… input)"),

    Key("polkit_agent", "managed", "bool", True, "Managed by swayctl-center"),

    # keyd remaps (applied by a root service; see modules/keyremap.py)
    Key("keyremap", "copilot", "enum", "default", "Copilot key", choices=("default", "super", "rightcontrol")),
    Key("keyremap", "remaps", "list", [], "Remapped keys", validator=validate_remaps,
        item_fields=(("from", "key"), ("to", "key"), ("swap", "bool"))),

    # app launcher (Walker + elephant; fuzzel is the fallback when they're missing)
    Key("launcher", "managed", "bool", True, "Managed by swayctl-center"),
    # swayctl-bar's Spotlight (needs the bar to be swayctl-bar) or Walker
    Key("launcher", "program", "enum", "swayctl-bar", "Launcher", choices=("swayctl-bar", "walker")),
    Key("launcher", "apps", "bool", True, "Apps"),
    Key("launcher", "settings", "bool", True, "Settings and quick actions"),
    Key("launcher", "calc", "bool", True, "Calculator (type = first)"),
    Key("launcher", "files", "bool", True, "Files and folders (type / first)"),
    Key("launcher", "files_in_results", "bool", False, "Show files without typing /"),
    Key("launcher", "websearch", "bool", True, "Web search (type @ first)"),
    Key("launcher", "symbols", "bool", True, "Emoji and symbols (type . first)"),
    Key("launcher", "windows", "bool", True, "Open windows (type $ first)"),
    Key("launcher", "runner", "bool", False, "Run commands (type > first)"),
    Key("launcher", "app_actions", "bool", False, "Show app actions (e.g. New private window)"),
    Key("launcher", "search_engine", "enum", "google", "Search engine", choices=SEARCH_ENGINES),
    Key("launcher", "file_folders", "list", ["~"], "Search in", validator=validate_folders,
        item_type="folder"),
    Key("launcher", "file_excluded", "list", [], "Skip", validator=validate_folders, item_type="folder"),
    Key("launcher", "file_watch", "bool", True, "Find new files right away"),

    # other apps' config files that follow the theme (fuzzel, kitty, btop...)
    Key("theming", "templates", "list", [], "Themed config files", validator=validate_templates,
        item_fields=(("template", "path"), ("output", "path"), ("reload", "command"))),

    # programs started once per login
    Key("autostart", "commands", "list", [], "Startup applications", validator=validate_autostart,
        item_fields=(("command", "str"), ("enabled", "bool"))),
    # keeps the desktop responsive while builds and indexers run (see governor.py)
    Key("priority", "responsiveness", "enum", "balanced", "Keep the desktop responsive",
        choices=("off", "balanced", "maximum", "custom")),
    Key("priority", "enabled", "bool", True, "Keep the desktop responsive under load"),
    Key("priority", "focus_boost", "bool", True, "Favor the app you are using"),
    Key("priority", "favor_windows", "bool", True, "Favor every app that draws on screen"),
    Key("priority", "focus_nice", "int", -4, "Priority of the app you are using", min=-11, max=0),
    Key("priority", "ui_nice", "int", -10, "Priority of the interface (bar, launcher, notifications)", min=-11, max=0),
    Key("priority", "background_nice", "int", 10, "Priority of background work", min=1, max=19),
    Key("priority", "compositor_realtime", "bool", True, "Keep the screen compositor ahead of everything"),
    Key("priority", "cpu_cap", "int", 75, "Background work: processor ceiling (%)", min=20, max=100),
    Key("priority", "cpu_cap_battery", "int", 60, "Background work on battery: processor ceiling (%)", min=20, max=100),
    Key("priority", "gpu_guard", "bool", True, "Hold back background programs when the graphics card is saturated"),
    Key("priority", "gpu_limit", "int", 80, "Graphics card busy limit (%)", min=30, max=100),
    Key("priority", "pressure_guard", "bool", True, "Slow background work further when the computer struggles"),
    Key("priority", "pressure_cpu", "int", 60, "Processor busy limit (%)", min=10, max=100),
    Key("priority", "pressure_io", "int", 10, "Disk waiting limit (%)", min=1, max=100),
    Key("priority", "interval", "int", 5, "Check every (seconds)", min=2, max=60),
    Key("priority", "rules", "list", PRIORITY_DEFAULT_RULES, "Priority rules", validator=validate_priority_rules,
        item_fields=(("match", "str"), ("field", "enum"), ("tier", "enum"), ("enabled", "bool"))),
    Key("priority", "protect", "list", PRIORITY_DEFAULT_PROTECT, "Never change these programs",
        validator=validate_priority_protect, item_type="str"),
)

# One-line explanations shown under each setting (translated in i18n.py).
HELP: dict[str, str] = {
    "layout.border": "Thickness of the line around windows, in pixels.",
    "layout.gaps_inner": "Space between windows, in pixels.",
    "layout.gaps_outer": "Extra space between windows and the screen edges.",
    "layout.smart_gaps": "Drop the gaps when a workspace has a single window.",
    "appearance.apps_follow": "foot, kitty and alacritty colors, the GTK 3 theme (browsers and Electron go by it) "
                              "and Qt apps switch with the desktop.",
    "layout.focus_follows_mouse": "Focus the window under the pointer without clicking.",
    "effects.corner_radius": "Round the corners of every window by this many pixels (0 = square).",
    "effects.shadows": "A soft shadow under windows.",
    "effects.shadow_blur_radius": "How far the shadow spreads; higher is softer.",
    "effects.shadow_offset_x": "Moves the shadow left (negative) or right.",
    "effects.shadow_offset_y": "How far the shadow drops below the window; negative lifts it above.",
    "effects.shadow_inactive": "How strong the shadow of a window you are not using is, as a share of the focused one's (100 = the same).",
    "effects.shadows_on_csd": "Also put a shadow under windows that draw their own frame and shadow (GTK apps without server decorations), which then get two.",
    "effects.blur": "Blur what's behind windows that are partly see-through (terminals...).",
    "effects.blur_passes": "How many times the blur is applied; more is smoother and heavier.",
    "effects.blur_radius": "How far each blur pass reaches.",
    "effects.dim_inactive": "Darken windows you aren't using (0 = off, 1 = black).",
    "effects.panels": "Blur and shadow behind the bar, notifications and launcher.",
    "effects.glass": "Quick Settings, the volume pill, the launcher and notifications become liquid glass: what's behind bends at the edges. The bar and the apps stay plain.",
    "effects.glass_refraction": "How hard the bezel bends what's behind it, in pixels (demo Refraction Scale). The flat centre stays clear; only the rim pulls and magnifies.",
    "effects.glass_opacity": "How much of the theme's color tints the glass (0 = clear; dark mode is always smoked glass). When glass is on, the shell's milk fill is thinned so the bend shows through.",
    "effects.glass_blur": "How frosted the glass is (0 = crystal clear, 100 = frosted). The demo precision lens is clear (default 0).",
    "effects.glass_highlight": "Brightness of the thin specular band on the glass edge (0 = none, 1 = full shine). Demo capsule rim is bright (default 0.90).",
    "effects.glass_edge": "Width of the curved glass rim, as a share of each pane's corner radius: 100 % is as wide as the corners, up to 300 %.",
    "effects.glass_thickness": "Glass optical depth in pixels (demo Glass Thickness): how far light travels through the rim, so a thicker pane bends colours harder at the edge.",
    "effects.glass_chroma": "Colour split at the rim (red bends less, blue more) — high-contrast edges behind the glass fringe into colour (0 = none).",
    "bar.icon_style": "Wi-Fi, sound, battery, Bluetooth and brightness: drawn in the iPadOS manner, or from the icon theme.",
    "bar.shape": "One bar of glass across the screen, or a piece of glass for each group (workspaces, clock, status).",
    "bar.padding": "Room around what's inside each pill of the bar: less fits more, more feels airier.",
    "effects.animations": "Animate windows opening, closing and moving.",
    "effects.anim_open_close": "Apps pop in when they open and shrink away when they close.",
    "effects.anim_workspace": "Switching workspaces is animated: a fade, or a slide when that option below is on.",
    "effects.anim_move": "Windows glide to their new place and size.",
    "layout.window_style": "How windows sit: Compact tiles them edge to edge with square corners; Balanced and Spacious leave gaps and round the corners.",
    "effects.shadow_style": "The shadow under windows: none, a soft one, or a deep one.",
    "priority.responsiveness": "How much of the computer builds and indexers may use, so the desktop never stutters: Maximum keeps the most free.",
    "effects.anim_feel": "How windows, popups and workspaces move. Pick one; the options below tune it and make it Custom.",
    "effects.anim_close_pace": "An exit is quicker than an entrance: closing, and leaving a workspace, take this share of the opening time (100 = as long).",
    "effects.anim_close_bounce": "How much a spring bounces when something closes (it does not on a Mac).",
    "effects.anim_popin": "A window opens from, and closes to, this share of its own size: 94 is a small step in, 80 a big pop.",
    "effects.anim_fade": "Opacity moves this much faster than the size: above 100 it is already there before the motion ends.",
    "effects.anim_quick": "Quick Settings, the launcher and the volume pill open and close with the same animation as windows (the style below); the compositor does it.",
    "effects.anim_slide": "Switching workspaces slides them sideways, in order, instead of fading.",
    "effects.anim_duration": "How long each animation takes; shorter feels snappier.",
    "effects.anim_curve": "Spring keeps its speed when a window is moved again mid-way; ease restarts every time.",
    "effects.anim_response": "How quickly the spring settles; lower is snappier.",
    "effects.anim_bounce": "How far windows overshoot before settling; 0 is none.",
    "scrolling.touchpad_smooth": "Scroll smoothly and keep gliding after your fingers lift.",
    "scrolling.touchpad_natural": "Content follows your fingers, like a phone.",
    "scrolling.touchpad_speed": "How far a swipe scrolls.",
    "scrolling.touchpad_glide": "How long it keeps gliding after you lift your fingers.",
    "scrolling.touchpad_ramp_ms": "Time to reach full speed at the start of a swipe; avoids jumps.",
    "scrolling.touchpad_smoothing": "Lower is smoother but lags a little behind your fingers.",
    "scrolling.mouse_smooth": "Turn each wheel notch into a short glide instead of a jump.",
    "scrolling.mouse_natural": "Reverse the wheel direction.",
    "scrolling.mouse_speed": "How far one wheel notch scrolls.",
    "scrolling.mouse_glide": "How long each notch keeps gliding.",
    "scrolling.mouse_smoothing": "Lower is smoother but less direct.",
    "appearance.mode": "Light, dark, or switch on a schedule.",
    "scrolling.browser_scale": "Chrome, Edge, Brave, VS Code and Discord scroll further per step than other apps; this evens it out.",
    "scrolling.page_keys": "In browsers and document viewers the page glides when you press Page Up or Page Down, instead of jumping.",
    "scrolling.profile": "How the touchpad and the mouse wheel scroll: off, or a glide that carries on a little, some or a lot after you stop.",
    "appearance.frame_color": "The solid colour of the bar and of the space around and between the windows (frame style).",
    "appearance.quick_surface": "Auto follows the interface style; flat draws Quick Settings, the volume pill and the launcher as plain blocks without glass or blur.",
    "appearance.ui_style": "One look for the bar, Quick Settings, OSD, notifications, launcher and windows: square and attached, rounded with gaps, liquid glass popups, Glass desk (the whole desktop is one sheet of glass over a moving video) or Modern Minimal cards.",
    "background.video": "A video file played muted and in a loop behind everything (needs the GStreamer plugins from gst-plugins-good and gst-libav). Leave empty for none; the Glass desk style plays a built-in one.",
    "appearance.schedule": "When automatic: follow sunrise and sunset, or your own times.",
    "appearance.gtk_css": "Also color GTK 4 / libadwaita apps with the theme (edits your gtk.css).",
    "priority.enabled": "Builds, language servers and indexers run behind the program you are using, so the desktop never stutters.",
    "priority.focus_boost": "The window you are looking at gets the processor first.",
    "priority.favor_windows": "Any program with a window (it has the graphics card open) is favored on its own, so new apps need no rule. Rules still win; builds and language servers never count.",
    "priority.focus_nice": "How strongly the focused app is favored (-11 is the most, 0 is none).",
    "priority.ui_nice": "The bar, Quick Settings, launcher and notifications run ahead of everything - even programs a favored app has just started (-11 is the most).",
    "priority.background_nice": "How far language servers and indexers step back (19 is the most).",
    "priority.compositor_realtime": "The program that draws the screen runs ahead of every normal program, so a busy computer never delays a frame.",
    "priority.cpu_cap": "All waiting work (builds, language servers, indexers) together may use at most this share of the processor; the rest is always free for the interface. 75 % costs a build little (a 16-thread processor has 8 real cores) and keeps 4 threads free. 100 = no ceiling.",
    "priority.cpu_cap_battery": "The same ceiling while on battery: less heat, longer charge.",
    "priority.gpu_guard": "The graphics card cannot be split by program, so this holds back what you are not looking at once it is saturated: those programs get the processor last, which slows how fast they feed it.",
    "priority.gpu_limit": "Held back while the graphics card is busier than this (it lets go at three quarters of it). 80 keeps a fifth of the card for animations.",
    "priority.pressure_guard": "When the processor is saturated or the disk is the bottleneck, background work steps back as far as builds do.",
    "priority.pressure_cpu": "Share of time something waits for a processor core that counts as struggling.",
    "priority.pressure_io": "Share of time everything waits for the disk that counts as struggling.",
    "priority.interval": "How often new programs are looked at.",
    "priority.protect": "Programs left exactly as they are: no rule and no favoring changes them. They draw the screen, take input and play sound, so touching them could only make the desktop worse (names must match exactly).",
    "bar.position": "Screen edge the bar sits on.",
    "bar.height": "How tall the bar is.",
    "bar.exclusive": "Windows stop at the bar instead of going under it.",
    "bar.modules_left": "What each side of the bar shows, in order.",
    "bar.clock_format_alt": "Shown when the pointer rests on the clock.",
    "bar.clock_format": "strftime codes, e.g. %H:%M for 14:05 or %a %d %b for Sat 03 Oct.",
    "bar.theme": "Use a different theme for the bar only (empty = same as the desktop).",
    "auth.fingerprint_lock": "Unlock the screen with a finger as well as the password.",
    "auth.fingerprint_sudo": "Confirm sudo in a terminal with a finger.",
    "auth.fingerprint_polkit": "Confirm admin prompts with a finger.",
    "auth.fingerprint_login": "Log in from the login screen with a finger.",
    "idle.lock_after": "Lock after this long without input.",
    "idle.screen_off_after": "Turn the screen off after this long without input.",
    "idle.suspend_after": "Put the computer to sleep after this long without input.",
    "idle.lock_before_sleep": "Always lock before the computer sleeps.",
    "notifications.dnd_on_start": "Start each session with Do Not Disturb on.",
    "notifications.timeout": "Seconds a normal notification stays on screen.",
    "notifications.grouping": "Stack notifications from the same app together.",
}

KEYS = tuple(replace(k, help=HELP.get(k.path, "")) for k in KEYS)

BY_PATH: dict[str, Key] = {k.path: k for k in KEYS}
SECTIONS: tuple[str, ...] = tuple(dict.fromkeys(k.section for k in KEYS))


def lookup(section: str, name: str) -> Key:
    try:
        return BY_PATH[f"{section}.{name}"]
    except KeyError:
        raise KeyError(f"unknown setting {section}.{name}") from None


def split_path(path: str) -> tuple[str, str]:
    """"input.touchpad.tap" -> ("input.touchpad", "tap")."""
    section, _, name = path.rpartition(".")
    if not section:
        raise KeyError(f"setting path must look like section.name, got {path!r}")
    return section, name


def defaults() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for k in KEYS:
        out.setdefault(k.section, {})[k.name] = copy.deepcopy(k.default)
    return out

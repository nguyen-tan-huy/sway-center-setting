"""Looks that set several settings at once (action preset.<name>). Each only
touches the keys listed; everything else the user set stays. "classic" puts
those keys back to their defaults."""
from __future__ import annotations

from typing import Any

from . import schema

MODERN: dict[str, dict[str, Any]] = {
    "appearance": {"style": "modern", "light_theme": "light", "dark_theme": "dark"},
    "layout": {"gaps_inner": 8, "gaps_outer": 4, "border": 2, "floating_border": 2,
               "border_style": "pixel", "smart_gaps": "off"},
    "bar": {"height": 34, "theme": ""},
    # only take effect under SwayFX (swayctl-fx); harmless on plain sway
    "effects": {"corner_radius": 10, "shadows": True, "blur": True, "dim_inactive": 0.06,
                "panels": True, "glass": True},
}


def _defaults_for(keys: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    d = schema.defaults()
    return {section: {name: d[section][name] for name in items} for section, items in keys.items()}


PRESETS = {"modern": MODERN, "classic": _defaults_for(MODERN)}


def values(name: str) -> dict[str, dict[str, Any]]:
    return PRESETS[name]


def current(effective: dict[str, dict[str, Any]]) -> str | None:
    """The preset the settings match exactly, if any."""
    for name, preset in PRESETS.items():
        if all(effective[s][k] == v for s, items in preset.items() for k, v in items.items()):
            return name
    return None


# Interface style: one choice that shapes the bar, popups, OSD and the windows
# (gaps, corners). appearance.ui_style itself drives the shell's radii (themes
# get square tokens); these are the plain settings it sets at the same time.
# the look: windows, effects and animations follow it (scrolling has its own profile below)
UI_STYLES: dict[str, dict[str, dict[str, Any]]] = {
    # square: the bar sits against the screen edge, windows are square and tile
    # without gaps; no glass, no animations
    "flat": {"layout": {"gaps_inner": 0, "gaps_outer": 0},
             "effects": {"corner_radius": 0, "glass": False, "anim_open_close": False, "anim_workspace": False, "anim_move": False, "anim_quick": False, "dim_inactive": 0.0},
             "bar": {"shape": "single", "margin_top": 0, "margin_right": 0, "margin_bottom": 0, "margin_left": 0}},
    # rounded: everything floats off the edges - a pill bar, round windows with gaps; no glass
    "rounded": {"layout": {"gaps_inner": 8, "gaps_outer": 8},
                "effects": {"corner_radius": 12, "glass": False, "anim_open_close": True, "anim_workspace": True, "anim_move": True, "anim_quick": True, "dim_inactive": 0.06},
                "bar": {"shape": "single", "margin_top": 0, "margin_right": 0, "margin_bottom": 0, "margin_left": 0}},
}
# liquid: the rounded look with the compositor's liquid glass
UI_STYLES["liquid"] = {**UI_STYLES["rounded"],
                       "effects": {**UI_STYLES["rounded"]["effects"], "glass": True}}
# frame: the bar sits against the top edge and, with the space around and between the windows, is one
# solid colour (appearance.frame_color); rounded windows sit in it, Quick Settings are flat blocks
UI_STYLES["frame"] = {"layout": {"gaps_inner": 8, "gaps_outer": 8},
                      "effects": {"corner_radius": 12, "glass": False, "anim_open_close": True, "anim_workspace": True, "anim_move": True, "anim_quick": True, "dim_inactive": 0.06},
                      "bar": {"shape": "single", "margin_top": 0, "margin_right": 0, "margin_bottom": 0, "margin_left": 0},
                      "appearance": {"quick_surface": "flat"}}
# minimal: Modern Minimal - the bar stays attached to its screen edge, rounded windows with wide gaps, no glass
UI_STYLES["minimal"] = {"layout": {"gaps_inner": 12, "gaps_outer": 12},
                        "effects": {"corner_radius": 16, "glass": False, "anim_open_close": True, "anim_workspace": True, "anim_move": True, "anim_quick": True, "dim_inactive": 0.0},
                        "bar": {"shape": "single", "margin_top": 0, "margin_right": 0, "margin_bottom": 0, "margin_left": 0},
                        "appearance": {"quick_surface": "auto"}}
# an earlier "floating square" is the square style now
UI_STYLES["floating"] = UI_STYLES["flat"]


def ui_style_values(style: str) -> dict[str, dict[str, Any]]:
    return UI_STYLES[style]


# How windows, popups and workspaces move: one choice that sets the whole bundle of animation settings
# (which kinds are on, the spring, how an exit differs from an entrance). Tuning any of them by hand
# makes it "custom"; the one that matches is named again.
_KINDS = ("anim_open_close", "anim_workspace", "anim_move", "anim_quick")


def _feel(response: int, bounce: int, close_pace: int, close_bounce: int, popin: int, fade: int) -> dict[str, dict[str, Any]]:
    return {"effects": {**{k: True for k in _KINDS}, "anim_curve": "spring", "anim_response": response,
                        "anim_bounce": bounce, "anim_close_pace": close_pace, "anim_close_bounce": close_bounce,
                        "anim_popin": popin, "anim_fade": fade}}


ANIM_FEELS: dict[str, dict[str, dict[str, Any]]] = {
    "off": {"effects": {k: False for k in _KINDS}},
    "subtle": _feel(300, 0, 70, 0, 96, 180),     # barely a movement: a quiet fade and a small step
    "smooth": _feel(340, 8, 70, 0, 94, 150),     # the default: settles softly, leaves quicker than it came
    "playful": _feel(420, 25, 80, 8, 88, 130),   # a visible bounce and a bigger pop
    "quick": _feel(220, 0, 65, 0, 96, 200),      # snappy, no bounce
}


# The other choices of the Desktop page, in the same way: each one is a handful of plain settings.
# Window style is the interface style's own gaps and corners, so choosing a style and choosing this
# name each other.
WINDOW_STYLES: dict[str, dict[str, dict[str, Any]]] = {
    "compact": {"layout": {"gaps_inner": 0, "gaps_outer": 0}, "effects": {"corner_radius": 0}},
    "balanced": {"layout": {"gaps_inner": 8, "gaps_outer": 8}, "effects": {"corner_radius": 12}},
    "spacious": {"layout": {"gaps_inner": 12, "gaps_outer": 12}, "effects": {"corner_radius": 16}},
}

SHADOW_STYLES: dict[str, dict[str, dict[str, Any]]] = {
    "off": {"effects": {"shadows": False}},
    "soft": {"effects": {"shadows": True, "shadow_blur_radius": 30, "shadow_offset_x": 0, "shadow_offset_y": 8,
                         "shadow_inactive": 70}},
    "deep": {"effects": {"shadows": True, "shadow_blur_radius": 60, "shadow_offset_x": 0, "shadow_offset_y": 20,
                         "shadow_inactive": 55}},
}


def _glass(refraction: int, blur: int, opacity: int, highlight: float, edge: int, thickness: int,
           chroma: float) -> dict[str, dict[str, Any]]:
    return {"effects": {"glass": True, "glass_refraction": refraction, "glass_blur": blur, "glass_opacity": opacity,
                        "glass_highlight": highlight, "glass_edge": edge, "glass_thickness": thickness,
                        "glass_chroma": chroma}}


# Liquid glass looks: each is every glass knob at once. "clear" is the stock values, so the
# Liquid interface style reads as it.
GLASS_STYLES: dict[str, dict[str, dict[str, Any]]] = {
    "off": {"effects": {"glass": False}},
    "subtle": _glass(25, 40, 15, 0.45, 60, 30, 0.0),     # a calm frosted sheet, a hint of bend
    "clear": _glass(50, 0, 10, 0.9, 100, 90, 0.35),      # see-through glass with a bright rim
    "frosted": _glass(40, 60, 22, 0.6, 100, 60, 0.0),    # milky: what is behind is blurred, soft light
    "prism": _glass(90, 0, 8, 0.9, 100, 90, 0.6),        # clear, strong bend and a rainbow rim
    "bold": _glass(140, 25, 10, 0.9, 180, 0, 0.0),       # deep lens: the biggest bend, no colour split
}


def _responsive(cpu: int, battery: int, gpu: int) -> dict[str, dict[str, Any]]:
    return {"priority": {"enabled": True, "focus_boost": True, "favor_windows": True, "compositor_realtime": True,
                         "pressure_guard": True, "gpu_guard": True, "cpu_cap": cpu, "cpu_cap_battery": battery,
                         "gpu_limit": gpu}}


# how much of the machine background work (builds, indexers) may take, so the desktop never stutters
RESPONSIVENESS: dict[str, dict[str, dict[str, Any]]] = {
    "off": {"priority": {"enabled": False}},
    "balanced": _responsive(75, 60, 80),
    "maximum": _responsive(60, 50, 70),
}

# the choice's setting -> its profiles
PROFILES: dict[str, dict[str, dict[str, dict[str, Any]]]] = {
    "effects.anim_feel": ANIM_FEELS,
    "layout.window_style": WINDOW_STYLES,
    "effects.shadow_style": SHADOW_STYLES,
    "effects.glass_style": GLASS_STYLES,
    "priority.responsiveness": RESPONSIVENESS,
}


def profile_values(path: str, name: str) -> dict[str, dict[str, Any]]:
    """The plain settings a profile sets ({} for "custom" or an unknown one)."""
    return PROFILES.get(path, {}).get(name, {})


def profile_matching(path: str, effective: dict[str, dict[str, Any]]) -> str:
    """The profile the settings amount to, or "custom"."""
    for name, preset in PROFILES[path].items():
        if all(effective[s].get(k) == v for s, items in preset.items() for k, v in items.items()):
            return name
    return "custom"


def anim_feel_values(name: str) -> dict[str, dict[str, Any]]:
    return profile_values("effects.anim_feel", name)


def anim_feel_matching(effective: dict[str, dict[str, Any]]) -> str:
    return profile_matching("effects.anim_feel", effective)


# Smooth scrolling, its own choice (not tied to the interface style): how far a
# glide carries on after the fingers or the wheel stop
SCROLL_PROFILES: dict[str, dict[str, dict[str, Any]]] = {
    "off": {"scrolling": {"touchpad_smooth": False, "mouse_smooth": False}},
    "light": {"scrolling": {"touchpad_smooth": True, "mouse_smooth": True,
                            "touchpad_glide": 0.96, "mouse_glide": 0.96}},
    "smooth": {"scrolling": {"touchpad_smooth": True, "mouse_smooth": True,
                             "touchpad_glide": 0.98, "mouse_glide": 0.98}},
    "fluid": {"scrolling": {"touchpad_smooth": True, "mouse_smooth": True,
                            "touchpad_glide": 0.99, "mouse_glide": 0.99}},
}


def scroll_values(profile: str) -> dict[str, dict[str, Any]]:
    return SCROLL_PROFILES[profile]

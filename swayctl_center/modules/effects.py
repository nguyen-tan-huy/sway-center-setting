"""SwayFX effects: rounded corners, shadows, blur, dimming, panel effects.

Only sent when the running compositor is SwayFX (swayctl-fx or upstream
SwayFX; get_version has "sway_original_version"). On plain sway the settings
are kept and nothing is sent, so the same store works in both sessions and
the user's sway config never needs SwayFX-only lines.
"""
from __future__ import annotations

from typing import Any

from .. import swayconfig, swayipc
from . import Context

# layer-shell namespaces of the panels we run
PANEL_NAMESPACES = ("waybar", "swayctl-bar", "swayctl-quick", "swayctl-osd", "swayctl-notifications",
                    "swayctl-launcher", "swayctl-traymenu",
                    "swaync-control-center",
                    "swaync-notification-window", "walker", "launcher")
# swayctl-bar's own surfaces: glass-ready (they fill the surface exactly), with
# the corner radius their CSS draws. OSD is one milky pill (volume/brightness):
# a full-round radius so the compositor's glass is a pill, not a soft box.
# Half the pill's height (osd.rs: 44 px): the radius also clips the surface's
# own content, so anything bigger eats the icon and the percent at the ends.
# (layer_effects takes 0-99; the old 999 was rejected and took the OSD's
# blur/glass with it)
GLASS_RADIUS = {"swayctl-osd": 22}
# Shaped glass: the glass follows what's drawn in the surface (read from its
# alpha), not the surface's box. Notifications (cards inside one big
# transparent surface) and Quick Settings, whose panel is invisible: each
# tile, slider and button is its own pane of glass.
SHAPED = ("swayctl-bar", "swayctl-quick", "swayctl-traymenu", "swayctl-launcher", "swayctl-notifications", "walker", "swaync-control-center", "swaync-notification-window")
# Of those, the ones whose surface box is *bigger* than what's drawn (cards
# floating inside one transparent surface): a compositor box shadow there
# would ring the whole surface, so it stays off. The bar and Quick Settings
# fill their surface exactly, but their box shadow read as a halo under the
# pills / around the panel — off by request.
CARD_SURFACE = ("swayctl-notifications", "walker",
                "swaync-control-center", "swaync-notification-window")
NO_SHADOW = CARD_SURFACE + ("swayctl-quick", "swayctl-traymenu", "swayctl-bar", "swayctl-launcher")
# these panels draw their own corners in CSS; the compositor's corner_radius
# (rounded blur region, rounded shadow) must match them — the blur radius is
# 0 in glass mode, so it can't be the source of truth there
PANE_RADIUS = ("swayctl-bar", "swayctl-quick")


def is_swayfx(version: dict[str, Any] | None) -> bool:
    return bool(version) and "sway_original_version" in version


def fork_features(version: dict[str, Any] | None) -> list[str]:
    return list((version or {}).get("swayctl_features", []))


def _onoff(b: bool) -> str:
    return "enable" if b else "disable"


# pick light or dark text per pane themselves (swayctl-bar, from what's behind):
# the compositor mustn't push their glass toward the theme's text
ADAPTIVE = ("swayctl-bar", "swayctl-quick", "swayctl-traymenu", "swayctl-osd", "swayctl-launcher", "swayctl-notifications")

# swayctl-center's own window (it draws only panes, the rest is clear)
SETTINGS_APP_ID = "io.github.huyhappy.SwayctlCenter.Settings"
# Windows that are liquid glass with the shell's settings: they draw only
# their panes (the rest is clear). chosua: the Matrix client
# (~/Downloads/Element).
GLASS_APPS = (SETTINGS_APP_ID, "chosua")
# The text each one draws, for the compositor's `glass text`: "none" = the app
# picks light/dark per pane itself from what's behind (GET_BACKDROP); "light"
# = always light text, and the glass darkens just enough behind it where the
# backdrop is too bright (the app asks the compositor nothing)
GLASS_APP_TEXT = {SETTINGS_APP_ID: "none", "chosua": "light"}
# With the fork's key ink ("glass-ink"): these draw their text in the key
# colour and the compositor inks it light or dark from what's behind the glass
# (`glass text auto`); they ask nothing (no GET_BACKDROP) and pick nothing
INK_APPS = ("chosua",)
INK_LAYERS = ("swayctl-bar", "swayctl-quick", "swayctl-traymenu", "swayctl-launcher")


class EffectsModule:
    sections = ("effects",)
    # "[app_id=...] glass ..." while the settings window isn't open
    tolerated_errors = ("No matching node.",)
    depends_on = ("theme",)
    _app_glass: str | None = None  # the for_window rule last added (sway keeps every one)

    def snapshot(self, ipc: swayipc.Connection) -> dict[str, Any]:
        return ipc.get_version()

    def commands(self, section: str, v: dict[str, Any], changed: set[str] | None,
                 ctx: Context | None = None) -> list[str]:
        if ctx is None or not is_swayfx(ctx.live):
            return []
        shadow = "#00000060"
        radius = 14
        if ctx.theme is not None:
            shadow = "#00000070" if ctx.theme.dark else "#00000038"
            radius = ctx.theme.tokens["radius_lg"]
        cmds = [
            f"corner_radius {v['corner_radius']}",
            f"shadows {_onoff(v['shadows'])}",
            f"shadow_blur_radius {v['shadow_blur_radius']}",
            f"shadow_color {shadow}",
            f"blur {_onoff(v['blur'])}",
            f"blur_passes {v['blur_passes']}",
            f"blur_radius {v['blur_radius']}",
            f"default_dim_inactive {v['dim_inactive']:g}",
            f"animation_duration_ms {200 if v['animations'] else 0}",
        ]
        glass = v["glass"] and "glass" in fork_features(ctx.live)
        if glass:
            # Demo lens (kube.io / winaviation): nearly clear, so the Snell
            # bezel stays sharp. Frost 0 = sharp backdrop; higher = frosted.
            frost = v["glass_blur"] / 100
            passes, radius = (0, 0) if frost <= 0 else (1 + round(2 * frost), max(1, round(5 * frost)))
            cmds += [f"blur_passes {passes}", f"blur_radius {radius}", "blur_saturation 1.4", "blur_brightness 1.08"]
        else:
            cmds += ["blur_saturation 1", "blur_brightness 1"]
        for ns in PANEL_NAMESPACES:
            on = v["panels"] or (glass and (ns in GLASS_RADIUS or ns in SHAPED))
            if not on:
                cmds.append(f'layer_effects "{ns}" "reset"')
                continue
            r = GLASS_RADIUS.get(ns, radius)
            r = ctx.theme.tokens[r] if isinstance(r, str) and ctx.theme else (14 if isinstance(r, str) else r)
            if ns in PANE_RADIUS and ctx.theme is not None:
                # match the CSS corners (native_css): .quick-panel radius_lg+6,
                # window.bar radius_lg — modern style only
                modern = ((ctx.values or {}).get("appearance") or {}).get("style") == "modern"
                r = ctx.theme.tokens["radius_lg"] + 6 if ns == "swayctl-quick" else (
                    ctx.theme.tokens["radius_lg"] if modern else 0)
            # one effect per command over IPC
            # Shaped panes (bar modules, Quick Settings tiles) mask by the
            # surface's alpha: glass.frag reads that as the pane's *shape* —
            # its 6 % tint saturates coverage — and bends the backdrop along
            # each capsule's outline, like the mock's per-control panes.
            # The OSD is one pill filling its surface, so it masks off and
            # follows corner_radius instead.
            mask = not (glass and ns in GLASS_RADIUS)
            cmds += [f'layer_effects "{ns}" "blur enable"',
                     f'layer_effects "{ns}" "blur_ignore_transparent {"enable" if mask else "disable"}"',
                     f'layer_effects "{ns}" "shadows {"disable" if ns in NO_SHADOW else "enable"}"',
                     f'layer_effects "{ns}" "corner_radius {r}"']
            if "glass" in fork_features(ctx.live):
                # shaped glass (notifications) needs the shaped-glass patch
                shaped_ok = ns not in SHAPED or "glass-shaped" in fork_features(ctx.live)
                use = glass and (ns in GLASS_RADIUS or ns in SHAPED) and shaped_ok
                cmds.append(f'layer_effects "{ns}" "glass {"enable" if use else "disable"}"')
                if use:
                    # the Liquid glass knobs: bar, Quick Settings and OSD
                    # follow the same settings the windows do
                    cmds.append(f'layer_effects "{ns}" "glass_refraction {v["glass_refraction"]}"')
                    # rim/specular light: always part of the glass patch
                    cmds.append(f'layer_effects "{ns}" "glass_highlight {v["glass_highlight"]:g}"')
                    if "glass-blur" in fork_features(ctx.live):
                        cmds.append(f'layer_effects "{ns}" "glass_blur {v["glass_blur"]}"')
                    if "glass-text" in fork_features(ctx.live):
                        cmds.append(f'layer_effects "{ns}" "glass_text {self.text_on(ns, ctx)}"')
                    if "glass-tune" in fork_features(ctx.live):
                        # rim path length + RGB dispersion (Thickness / colour at the rim)
                        cmds.append(f'layer_effects "{ns}" "glass_edge {v["glass_edge"]}"')
                        cmds.append(f'layer_effects "{ns}" "glass_thickness {v["glass_thickness"]}"')
                        cmds.append(f'layer_effects "{ns}" "glass_chroma {v["glass_chroma"]:g}"')
        if "glass-windows" in fork_features(ctx.live):
            # the settings window tags its panes light/dark itself (backdrop.py)
            text = "none" if "glass-text" in fork_features(ctx.live) else None
            cmds += self.app_glass(glass, v, text, ctx)
        return cmds

    def apply_extra(self, section: str, v: dict[str, Any], changed: set[str] | None,
                    ctx: Context | None = None) -> list[str]:
        """Save what was just sent for swayctl-fx to read at its next start
        (with its config), so the first frame after login already has glass."""
        if ctx is None or not is_swayfx(ctx.live):
            return []
        # rules only: "[criteria] cmd" needs a window and fails in a config
        cmds = self.commands(section, v, None, ctx)
        lines = [c for c in cmds if not c.startswith("[")]
        # the glass windows' rules, so they open as glass (a reload clears
        # rules and reads this file again: no pile-up)
        if not any(c.startswith("for_window") for c in lines):
            for app in GLASS_APPS:
                rule = [c for c in cmds if c.startswith(f'[app_id="{app}"]')]
                if rule:
                    what = rule[0].split("] ", 1)[1]
                    lines.append(f'for_window [app_id="{app}"] "{what}"')
        text = "# written by swayctl-center: effects for swayctl-fx at startup\n" + "\n".join(lines) + "\n"
        path = ctx.data_dir / "generated" / "swayctl-fx.conf"
        try:
            if not path.exists() or path.read_text() != text:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
        except OSError as e:
            return [f"effects: {e}"]
        return []

    @staticmethod
    def text_on(ns: str, ctx: Context) -> str:
        """The text drawn on a pane of glass, for the compositor: "auto" (key
        ink, the compositor inks it from what's behind) for the bar and Quick
        Settings when the fork can; else "none" - the other surfaces pick
        their own text per pane from what's behind."""
        if ns in INK_LAYERS and "glass-ink" in fork_features(ctx.live):
            return "auto"
        return "none"

    def app_glass(self, glass: bool, v: dict[str, Any], text: str | None = None,
                  ctx: Context | None = None) -> list[str]:
        """The settings window as liquid glass: now (open windows) and for new
        ones. for_window rules can't be removed, so one is added only when the
        wanted state changes (the newest rule runs last and wins)."""
        # no border: the window is panes on the desktop, a focus frame around it
        # would draw a box the glass doesn't have
        tune = ""
        if glass:
            tune += f", glass highlight {v.get('glass_highlight', 0.50):g}"
            if ctx is not None and "glass-tune" in fork_features(ctx.live):
                tune += (f", glass edge {v.get('glass_edge', 70)}"
                         f", glass thickness {v.get('glass_thickness', 200)}"
                         f", glass chroma {v.get('glass_chroma', 0.40):g}")
        def what(app: str) -> str:
            if not glass:
                return "glass disable"
            app_text = GLASS_APP_TEXT.get(app, text) if text else None
            if app_text and app in INK_APPS and ctx is not None and "glass-ink" in fork_features(ctx.live):
                app_text = "auto"
            return (f"glass enable, glass refraction {v['glass_refraction']}, glass blur {v['glass_blur']}"
                    + tune
                    + (f", glass text {app_text}" if app_text else "") + ", border none, shadows disable")

        cmds = [f'[app_id="{app}"] {what(app)}' for app in GLASS_APPS]
        wanted = "\n".join(what(app) for app in GLASS_APPS)
        if wanted != self._app_glass:
            self._app_glass = wanted
            # quoted: sway splits commands at commas, which would leave the rest
            # of the list outside the for_window
            cmds = [f'for_window [app_id="{app}"] "{what(app)}"' for app in GLASS_APPS] + cmds
        return cmds

    def import_current(self, ipc: swayipc.Connection, config: swayconfig.Config,
                       ctx: Context) -> dict[str, dict[str, Any]]:
        return {}

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

# swayctl-frame: the frame style's pane under the windows (bar, edges and gaps in one piece, with a
# cut-out for every window), see swayctl-bar's ui/frame.rs
FRAME_NS = "swayctl-frame"
# layer-shell namespaces of the panels we run
PANEL_NAMESPACES = ("waybar", "swayctl-bar", "swayctl-frame", "swayctl-quick", "swayctl-osd", "swayctl-notifications",
                    "swayctl-launcher", "swayctl-traymenu",
                    "swaync-control-center",
                    "swaync-notification-window", "walker", "launcher")
# Liquid glass is for these popups only - never the bar, the frame, a tray menu or any app window. (The
# glass setting turns it on for exactly these; everything else is a plain material.)
GLASS_NAMESPACES = ("swayctl-quick", "swayctl-osd", "swayctl-launcher", "swayctl-notifications")
# swayctl-bar's own surfaces: glass-ready (they fill the surface exactly), with
# the corner radius their CSS draws. OSD is one milky pill (volume/brightness):
# a full-round radius so the compositor's glass is a pill, not a soft box.
# Half the pill's height (osd.rs: 44 px): the radius also clips the surface's
# own content, so anything bigger eats the icon and the percent at the ends.
# (layer_effects takes 0-99; the old 999 was rejected and took the OSD's
# blur/glass with it)
GLASS_RADIUS = {"swayctl-osd": 22}
# The bezel (glass_edge) no wider than the smallest corner radius a target
# draws, less 1 px - as the demo builds its glass (bezel = min(edge, r - 1)).
# A wider bezel met itself across a pane's corners on a diagonal crease:
# each edge bent on its own and a bubble or pill read as eight pieces.
# (swayctl-fx now rounds those corners, so up to 3x this is allowed.)
# The popups share the OSD's bezel (21): the same lens on every one of them. A pill or card shorter than two
# bezels gets a narrower rim by itself (the shader caps the bezel at half the pane's thickness).
EDGE_CAP = {"chosua": 17, "swayctl-bar": 14, FRAME_NS: 7, "swayctl-quick": 21,
            "swayctl-launcher": 21, "swayctl-traymenu": 13, "swayctl-osd": 21,
            "swayctl-notifications": 21}
EDGE_CAP_DEFAULT = 11  # libadwaita's own panes (the settings window), cards


# How far the glass may bend what is behind it, whatever the sliders say. Past these the backdrop of a small
# pane (a tile, a slider, a card) bleeds into it - colours from beside and below dragged across it. The
# settings keep what was asked for; only what is sent to the compositor is held to this.
GLASS_REFRACTION_MAX = 90
GLASS_EDGE_SHARE_MAX = 150


def glass_refraction(v: dict[str, Any]) -> int:
    return min(int(v["glass_refraction"]), GLASS_REFRACTION_MAX)


def glass_edge(target: str, share: int) -> int:
    """glass_edge (the setting) is a share of the cap, 10-300 %: 100 % is as
    wide as the corners (swayctl-fx rounds a wider rim's corners, so it stays
    one piece); anything else (an old px value) counts as 100 %."""
    cap = EDGE_CAP.get(target, EDGE_CAP_DEFAULT)
    share = int(share)
    if not 10 <= share <= 300:
        share = 100
    share = min(share, GLASS_EDGE_SHARE_MAX)
    return max(1, round(cap * share / 100))
# Shaped glass: the glass follows what's drawn in the surface (read from its
# alpha), not the surface's box. Notifications (cards inside one big
# transparent surface) and Quick Settings, whose panel is invisible: each
# tile, slider and button is its own pane of glass.
SHAPED = ("swayctl-bar", FRAME_NS, "swayctl-quick", "swayctl-traymenu", "swayctl-launcher", "swayctl-notifications", "walker", "swaync-control-center", "swaync-notification-window")
# Of those, the ones whose surface box is *bigger* than what's drawn (cards
# floating inside one transparent surface): a compositor box shadow there
# would ring the whole surface, so it stays off. The bar and Quick Settings
# fill their surface exactly, but their box shadow read as a halo under the
# pills / around the panel — off by request.
CARD_SURFACE = ("swayctl-notifications", "walker",
                "swaync-control-center", "swaync-notification-window")
# With the fork's shaped shadows ("shaped-shadow": the shadow of what a surface draws, not of its box)
# the popups follow the Window shadows setting like windows do; only these never cast one (a halo
# under the bar's pills and the frame's pane — off by request).
NO_SHADOW = ("swayctl-bar", FRAME_NS)
# Without it, a box shadow rings the whole surface: these stay off, as they always were
BOX_SHADOW_UNFIT = CARD_SURFACE + ("swayctl-quick", "swayctl-traymenu", "swayctl-launcher")
# these panels draw their own corners in CSS; the compositor's corner_radius
# (rounded blur region, rounded shadow) must match them — the blur radius is
# 0 in glass mode, so it can't be the source of truth there
PANE_RADIUS = ("swayctl-bar", "swayctl-quick")


def desk_style(ctx: Context | None) -> bool:
    """Interface style "glass": the whole desktop is one sheet of glass over a video."""
    return ((getattr(ctx, "values", None) or {}).get("appearance") or {}).get("ui_style") == "glass"


def is_swayfx(version: dict[str, Any] | None) -> bool:
    return bool(version) and "sway_original_version" in version


ANIMATION_KINDS = ("anim_open_close", "anim_workspace", "anim_move", "anim_quick")


def _scaled_alpha(color: str, percent: int) -> str:
    """#rrggbbaa with its alpha scaled to `percent` of itself (the shadow of an unfocused window)."""
    alpha = round(int(color[7:9], 16) * max(0, min(100, int(percent))) / 100)
    return f"{color[:7]}{alpha:02x}"


def _any_animation(v: dict[str, Any]) -> bool:
    return any(v.get(k) for k in ANIMATION_KINDS)


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
# xdg-desktop-portal-gtk: the file / app chooser, one frosted sheet with
# its own theme (portalglass.py) and the theme's text: no ink, no probing
PORTAL_APP_ID = "xdg-desktop-portal-gtk"
GLASS_APPS = (SETTINGS_APP_ID, "chosua", PORTAL_APP_ID)
# The text each one draws, for the compositor's `glass text`: "none" = the app
# picks light/dark per pane itself from what's behind (GET_BACKDROP); "light"
# = always light text, and the glass darkens just enough behind it where the
# backdrop is too bright (the app asks the compositor nothing)
GLASS_APP_TEXT = {SETTINGS_APP_ID: "none", "chosua": "light", PORTAL_APP_ID: "none"}
# With the fork's key ink ("glass-ink"): these draw their text in the key
# colour and the compositor inks it light or dark from what's behind the glass
# (`glass text auto`); they ask nothing (no GET_BACKDROP) and pick nothing
INK_APPS = (SETTINGS_APP_ID, "chosua")
INK_LAYERS = ("swayctl-quick", "swayctl-launcher", "swayctl-notifications")


class EffectsModule:
    sections = ("effects",)
    # "[app_id=...] glass ..." while the settings window isn't open
    tolerated_errors = ("No matching node.",)
    depends_on = ("theme",)
    _app_glass: str | None = None  # the for_window rule last added (sway keeps every one)
    # each glass app's rule as it applies to one window, as of the last apply
    window_rules: dict[str, str] | None = None

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
            f"shadow_inactive_color {_scaled_alpha(shadow, v['shadow_inactive'])}",
            f"shadow_offset {v['shadow_offset_x']} {v['shadow_offset_y']}",
            f"shadows_on_csd {_onoff(v['shadows_on_csd'])}",
            f"blur {_onoff(v['blur'])}",
            f"blur_passes {v['blur_passes']}",
            f"blur_radius {v['blur_radius']}",
            f"default_dim_inactive {v['dim_inactive']:g}",
            # one switch per kind; the length is only on while some kind is
            f"animation_duration_ms {v.get('anim_duration', 200) if _any_animation(v) else 0}",
        ]
        if "animation-kinds" in fork_features(ctx.live):
            cmds += [f"animations {kind} {'enable' if v.get(key) else 'disable'}"
                     for kind, key in (("open_close", "anim_open_close"), ("workspace", "anim_workspace"),
                                       ("move", "anim_move"))]
        if "animation-popups" in fork_features(ctx.live):
            # Quick Settings, the launcher and the volume pill: the compositor opens and closes them
            cmds.append(f"animations popups {'enable' if v.get('anim_quick') else 'disable'}")
        if "animation-slide" in fork_features(ctx.live):
            cmds.append(f"animations workspace_slide {'enable' if v.get('anim_slide', True) else 'disable'}")
        if "animation-spring" in fork_features(ctx.live):
            cmds += [f"animation_curve {v.get('anim_curve', 'spring')}",
                     f"animation_spring {v.get('anim_response', 340)} {v.get('anim_bounce', 8) / 100:g}"]
        if "animation-apple" in fork_features(ctx.live):
            cmds += [f"animation_close {v.get('anim_close_pace', 70) / 100:g} {v.get('anim_close_bounce', 0) / 100:g}",
                     f"animation_popin {v.get('anim_popin', 94) / 100:g}",
                     f"animation_fade {v.get('anim_fade', 150) / 100:g}"]
        glass = v["glass"] and "glass" in fork_features(ctx.live)
        if glass:
            # Demo lens (kube.io / winaviation): nearly clear, so the Snell
            # bezel stays sharp. Frost 0 = sharp backdrop; higher = frosted.
            # The glass desk plays a video under everything: a frost makes the compositor blur the whole
            # screen again for every video frame (about twice the frame time at 120 Hz, measured), so
            # the desk is always clear glass - tools/video_glass_cost_probe.sh
            frost = 0 if desk_style(ctx) else v["glass_blur"] / 100
            passes, radius = (0, 0) if frost <= 0 else (1 + round(2 * frost), max(1, round(5 * frost)))
            cmds += [f"blur_passes {passes}", f"blur_radius {radius}", "blur_saturation 1.4", "blur_brightness 1.08"]
        else:
            cmds += ["blur_saturation 1", "blur_brightness 1"]
        for ns in PANEL_NAMESPACES:
            ns_glass = glass and (ns in GLASS_NAMESPACES or (desk_style(ctx) and ns == FRAME_NS))
            on = v["panels"] or (ns_glass and (ns in GLASS_RADIUS or ns in SHAPED))
            if not on:
                cmds.append(f'layer_effects "{ns}" "reset"')
                continue
            r = GLASS_RADIUS.get(ns, radius)
            r = ctx.theme.tokens[r] if isinstance(r, str) and ctx.theme else (14 if isinstance(r, str) else r)
            if ctx.theme is not None and ctx.theme.tokens["radius_lg"] == 0:
                r = 0  # square interface style: the OSD's pill and every pane lose their corners
            if ns in PANE_RADIUS and ctx.theme is not None:
                # match the CSS corners (native_css): .quick-panel radius_lg+6,
                # window.bar radius_lg — modern style only
                modern = ((ctx.values or {}).get("appearance") or {}).get("style") == "modern"
                lg = ctx.theme.tokens["radius_lg"]
                r = (lg + 6 if lg else 0) if ns == "swayctl-quick" else 0   # the bar is square, attached
            # one effect per command over IPC
            # Shaped panes (bar modules, Quick Settings tiles) mask by the
            # surface's alpha: glass.frag reads that as the pane's *shape* —
            # its 6 % tint saturates coverage — and bends the backdrop along
            # each capsule's outline, like the mock's per-control panes.
            # The OSD is one pill filling its surface, so it masks off and
            # follows corner_radius instead.
            if ns == FRAME_NS:
                r = 0  # the cut-outs carry the corners, not the pane
            mask = not (ns_glass and ns in GLASS_RADIUS)
            # the bar sits on the wallpaper as a plain light/dark material: nothing to
            # blur. Popups (Quick Settings, menus, notifications) float over windows
            # and keep their blur, or the text behind shows through them.
            flat_quick = ns in ("swayctl-quick", "swayctl-osd", "swayctl-launcher") and ((ctx.values or {}).get("appearance") or {}).get("quick_surface") == "flat"
            minimal = ((ctx.values or {}).get("appearance") or {}).get("ui_style") == "minimal"  # cards, never blur
            plain = (ns == "swayctl-bar" and not ns_glass) or flat_quick or minimal
            cmds += [f'layer_effects "{ns}" "blur {"disable" if plain else "enable"}"',
                     f'layer_effects "{ns}" "blur_ignore_transparent {"enable" if mask else "disable"}"',
                     f'layer_effects "{ns}" "shadows {"enable" if self.popup_shadow(ns, mask, v, ctx) else "disable"}"',
                     f'layer_effects "{ns}" "corner_radius {r}"']
            if "glass" in fork_features(ctx.live):
                # shaped glass (notifications) needs the shaped-glass patch
                shaped_ok = ns not in SHAPED or "glass-shaped" in fork_features(ctx.live)
                use = ns_glass and (ns in GLASS_RADIUS or ns in SHAPED) and shaped_ok
                cmds.append(f'layer_effects "{ns}" "glass {"enable" if use else "disable"}"')
                if use:
                    # the Liquid glass knobs: bar, Quick Settings and OSD
                    # follow the same settings the windows do
                    cmds.append(f'layer_effects "{ns}" "glass_refraction {glass_refraction(v)}"')
                    # rim/specular light: always part of the glass patch
                    cmds.append(f'layer_effects "{ns}" "glass_highlight {v["glass_highlight"]:g}"')
                    if "glass-blur" in fork_features(ctx.live):
                        blur = 0 if desk_style(ctx) else v["glass_blur"]
                        cmds.append(f'layer_effects "{ns}" "glass_blur {blur}"')
                    if "glass-text" in fork_features(ctx.live):
                        cmds.append(f'layer_effects "{ns}" "glass_text {self.text_on(ns, ctx)}"')
                    if "glass-tune" in fork_features(ctx.live):
                        # rim path length + RGB dispersion (Thickness / colour at the rim)
                        cmds.append(f'layer_effects "{ns}" "glass_edge {glass_edge(ns, v["glass_edge"])}"')
                        cmds.append(f'layer_effects "{ns}" "glass_thickness {v["glass_thickness"]}"')
                        cmds.append(f'layer_effects "{ns}" "glass_chroma {v["glass_chroma"]:g}"')
        if "glass-windows" in fork_features(ctx.live):
            # no app window is glass (the settings window, chosua, the portal's dialogs): they are told once,
            # so a rule an older run left in sway is overruled by this one
            text = "none" if "glass-text" in fork_features(ctx.live) else None
            cmds += self.app_glass(False, v, text, ctx)
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
        problems = self.portal_theme(v, ctx)
        # the rest of the settings (gaps, colors, outputs...) ride along from startup.conf
        startup = ctx.data_dir / "generated" / "startup.conf"
        text = ("# written by swayctl-center: effects for swayctl-fx at startup\n"
                f"include {startup}\n" + "\n".join(lines) + "\n")
        path = ctx.data_dir / "generated" / "swayctl-fx.conf"
        try:
            if not path.exists() or path.read_text() != text:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
        except OSError as e:
            return problems + [f"effects: {e}"]
        return problems

    @staticmethod
    def portal_theme(v: dict[str, Any], ctx: Context) -> list[str]:
        """The portal's dialogs as a frosted sheet when windows can be glass."""
        from .. import portalglass
        from .components import shell_milk
        feats = fork_features(ctx.live)
        on = False   # no app window is glass any more: this takes the frosted sheet away if an older run installed it
        css = ""
        if on and ctx.theme is not None:
            t = ctx.theme.tokens
            css = portalglass.css(ctx.theme.dark, t["accent"], t["accent_fg"], shell_milk(v.get("glass_opacity", 50), True),
                                 v.get("corner_radius", 12))
        try:
            portalglass.sync(on and bool(css), css)
        except OSError as e:
            return [f"effects: portal theme: {e}"]
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

    @staticmethod
    def popup_shadow(ns: str, mask: bool, v: dict[str, Any], ctx: Context | None) -> bool:
        """Does this layer surface cast a shadow? It follows the Window shadows setting, as windows do:
        a surface that draws a shape casts a shadow of that shape (needs the fork's shaped shadows; a
        box shadow would ring the whole surface), one that fills its box a box shadow."""
        if not v.get("shadows") or ns in NO_SHADOW:
            return False
        # Glass panes drawn by their alpha (Quick Settings, the launcher, notifications) cast no shadow: it
        # showed as a dark ring just outside each pane's bright rim, which the OSD (one pill, a soft halo)
        # does not have. Without the glass they keep it, as windows do.
        if mask and v.get("glass") and ns in GLASS_NAMESPACES:
            return False
        if mask and not (ctx is not None and "shaped-shadow" in fork_features(ctx.live)):
            return ns not in BOX_SHADOW_UNFIT
        return True

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
                tune += (f", glass edge {{edge}}"
                         f", glass thickness {v.get('glass_thickness', 200)}"
                         f", glass chroma {v.get('glass_chroma', 0.40):g}")
        ink = ctx is not None and "glass-ink" in fork_features(ctx.live)
        # their shadow follows the Window shadows setting (a shadow of the panes they draw, not of
        # their box) when the compositor can; else none, as it always was
        shaped_shadow = ctx is not None and "shaped-shadow" in fork_features(ctx.live)
        shadow = "enable" if (shaped_shadow and v.get("shadows")) else "disable"

        def what(app: str) -> str:
            if not glass:
                return "glass disable"
            app_text = GLASS_APP_TEXT.get(app, text) if text else None
            if app_text and app in INK_APPS and ink:
                app_text = "auto"
            return (f"glass enable, glass refraction {glass_refraction(v)}, glass blur {v['glass_blur']}"
                    + tune.replace("{edge}", str(glass_edge(app, v.get("glass_edge", 70))))
                    + (f", glass text {app_text}" if app_text else "") + f", border none, shadows {shadow}")

        cmds = [f'[app_id="{app}"] {what(app)}' for app in GLASS_APPS]
        self.window_rules = {app: what(app) for app in GLASS_APPS}
        wanted = "\n".join(what(app) for app in GLASS_APPS)
        if wanted != self._app_glass:
            self._app_glass = wanted
            # quoted: sway splits commands at commas, which would leave the rest
            # of the list outside the for_window
            cmds = [f'for_window [app_id="{app}"] "{what(app)}"' for app in GLASS_APPS] + cmds
        return cmds

    def window_opened(self, payload: dict[str, Any] | None) -> list[str]:
        """A window just opened: its glass rule sent to it directly. The
        for_window rules should have done it as it mapped, but a window that
        opened without them (sway held an older set) stayed plain glass with
        its key-coloured text un-inked until a `reload` re-ran them; this
        makes it right at once, whatever sway held."""
        if (payload or {}).get("change") != "new" or not self.window_rules:
            return []
        con = (payload or {}).get("container") or {}
        rule = self.window_rules.get(con.get("app_id"))
        if not rule or con.get("id") is None:
            return []
        return [f'[con_id={con["id"]}] {rule}']

    def import_current(self, ipc: swayipc.Connection, config: swayconfig.Config,
                       ctx: Context) -> dict[str, dict[str, Any]]:
        return {}

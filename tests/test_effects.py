import unittest
from pathlib import Path

from swayctl_center import presets, schema, themes
from swayctl_center.modules import Context
from swayctl_center.modules.effects import EffectsModule, fork_features, is_swayfx

STOCK = {"human_readable": "1.12", "variant": "sway", "major": 1}
FX = {"human_readable": "0.6", "sway_original_version": "1.12.0", "variant": "sway",
      "swayctl_features": ["ipc-features"]}


def run(live, **values):
    v = schema.defaults()["effects"] | values
    ctx = Context(Path("/app"), live=live, theme=themes.BUILTIN["dark"])
    return EffectsModule().commands("effects", v, None, ctx)


class EffectsTest(unittest.TestCase):
    def test_nothing_on_plain_sway(self):
        self.assertEqual(run(STOCK, blur=True), [])
        self.assertEqual(run(None, blur=True), [])

    def test_detection(self):
        self.assertTrue(is_swayfx(FX))
        self.assertFalse(is_swayfx(STOCK))
        self.assertEqual(fork_features(FX), ["ipc-features"])
        self.assertEqual(fork_features(STOCK), [])

    def test_defaults_are_off(self):
        cmds = run(FX)
        for c in ("corner_radius 0", "shadows disable", "blur disable", "default_dim_inactive 0",
                  "animation_duration_ms 0", 'layer_effects "waybar" "reset"'):
            self.assertIn(c, cmds)

    def test_shadow_options_are_swayfx_s(self):
        cmds = run(FX)
        self.assertIn("shadow_offset 0 0", cmds)
        self.assertIn("shadows_on_csd disable", cmds)
        base = [c for c in cmds if c.startswith("shadow_color")][0].split()[1]
        same = [c for c in cmds if c.startswith("shadow_inactive_color")][0].split()[1]
        self.assertEqual(same, base)                              # 100 %: as strong as the focused one
        cmds = run(FX, shadow_inactive=50, shadow_offset_x=3, shadow_offset_y=9, shadows_on_csd=True)
        half = [c for c in cmds if c.startswith("shadow_inactive_color")][0].split()[1]
        self.assertEqual(int(half[7:9], 16), round(int(base[7:9], 16) / 2))
        self.assertIn("shadow_offset 3 9", cmds)
        self.assertIn("shadows_on_csd enable", cmds)

    def test_popups_follow_the_shadow_setting_with_shaped_shadows(self):
        fx = FX | {"swayctl_features": ["ipc-features", "glass", "glass-windows", "shaped-shadow"]}
        for on in (True, False):
            cmds = run(fx, shadows=on, panels=True, glass=True)
            word = "enable" if on else "disable"
            # glass panes drawn by their alpha cast no shadow (a dark ring outside their rim); the tray menu
            # is not one of them
            for ns in ("swayctl-quick", "swayctl-launcher", "swayctl-notifications"):
                self.assertIn(f'layer_effects "{ns}" "shadows disable"', cmds, ns)
            self.assertIn(f'layer_effects "swayctl-traymenu" "shadows {word}"', cmds)
        # the same surfaces keep it when the glass is off, as windows do
        cmds = run(fx, shadows=True, panels=True, glass=False)
        for ns in ("swayctl-quick", "swayctl-launcher", "swayctl-notifications"):
            self.assertIn(f'layer_effects "{ns}" "shadows enable"', cmds, ns)
            # the bar and the frame never cast one
            self.assertIn('layer_effects "swayctl-bar" "shadows disable"', cmds)

    def test_without_shaped_shadows_nothing_changes(self):
        old = FX | {"swayctl_features": ["ipc-features", "glass", "glass-windows"]}
        cmds = run(old, shadows=True, panels=True, glass=True)
        self.assertIn('layer_effects "swayctl-quick" "shadows disable"', cmds)    # a box shadow would ring the surface

    def test_apple_like_animation_settings_go_to_a_compositor_that_has_them(self):
        fx = FX | {"swayctl_features": ["ipc-features", "animation-apple"]}
        cmds = run(fx)
        for c in ("animation_close 0.7 0", "animation_popin 0.94", "animation_fade 1.5"):
            self.assertIn(c, cmds)
        cmds = run(fx, anim_close_pace=100, anim_close_bounce=10, anim_popin=80, anim_fade=100)
        for c in ("animation_close 1 0.1", "animation_popin 0.8", "animation_fade 1"):
            self.assertIn(c, cmds)
        self.assertFalse([c for c in run(FX) if c.startswith(("animation_close", "animation_popin", "animation_fade"))])

    def test_modern_preset(self):
        cmds = run(FX, **presets.MODERN["effects"])
        self.assertIn("corner_radius 10", cmds)
        self.assertIn("default_dim_inactive 0.06", cmds)
        self.assertIn('layer_effects "waybar" "blur enable"', cmds)
        self.assertIn('layer_effects "waybar" "corner_radius 14"', cmds)  # theme radius_lg
        self.assertIn("shadow_color #00000070", cmds)


class WindowGlassTest(unittest.TestCase):
    """No app window is glass: liquid glass is for the popups only."""
    FX = {"sway_original_version": "x", "swayctl_features": ["glass", "glass-shaped", "glass-windows"]}
    APPS = ("io.github.huyhappy.SwayctlCenter.Settings", "chosua", "xdg-desktop-portal-gtk")

    def test_no_app_window_is_glass_however_the_setting_is(self):
        m = EffectsModule()
        ctx = Context(Path("/app"), live=self.FX, theme=themes.BUILTIN["dark"])
        for glass in (True, False):
            cmds = EffectsModule().commands("effects", schema.defaults()["effects"] | {"glass": glass}, None, ctx)
            for app in self.APPS:
                self.assertIn(f'[app_id="{app}"] glass disable', cmds, app)
                self.assertIn(f'for_window [app_id="{app}"] "glass disable"', cmds, app)
            self.assertFalse(any("glass enable" in c and "app_id" in c for c in cmds))
        # told once: a rule an older run left in sway is overruled by the newest, and none piles up
        v = schema.defaults()["effects"] | {"glass": True}
        m.commands("effects", v, None, ctx)
        self.assertFalse(any(c.startswith("for_window") for c in m.commands("effects", v, None, ctx)))
        self.assertIn("No matching node.", m.tolerated_errors)  # the settings window is not open

    def test_a_new_window_of_those_apps_is_told_it_is_not_glass(self):
        m = EffectsModule()
        app = "io.github.huyhappy.SwayctlCenter.Settings"
        opened = {"change": "new", "container": {"id": 42, "app_id": app}}
        self.assertEqual(m.window_opened(opened), [])  # nothing applied yet
        ctx = Context(Path("/app"), live=self.FX, theme=themes.BUILTIN["dark"])
        m.commands("effects", schema.defaults()["effects"] | {"glass": True}, None, ctx)
        self.assertEqual(m.window_opened(opened), ["[con_id=42] glass disable"])
        self.assertEqual(m.window_opened({"change": "new", "container": {"id": 7, "app_id": "firefox"}}), [])

    def test_needs_the_feature(self):
        ctx = Context(Path("/app"), live=FX | {"swayctl_features": ["glass"]}, theme=themes.BUILTIN["dark"])
        cmds = EffectsModule().commands("effects", schema.defaults()["effects"] | {"glass": True}, None, ctx)
        self.assertFalse(any("SwayctlCenter" in c for c in cmds))


class GlassTextTest(unittest.TestCase):
    FX = {"sway_original_version": "x", "swayctl_features": ["glass", "glass-shaped", "glass-text", "glass-windows"]}

    def cmds(self, theme, features=None):
        live = self.FX if features is None else {"sway_original_version": "x", "swayctl_features": features}
        ctx = Context(Path("/app"), live=live, theme=themes.BUILTIN[theme])
        return EffectsModule().commands("effects", schema.defaults()["effects"] | {"glass": True}, None, ctx)

    def test_no_adaptive_text(self):
        # the glass doesn't adapt to what's behind it any more
        for theme in ("dark", "light"):
            cmds = self.cmds(theme)
            self.assertTrue(all(c.endswith('"glass_text none"') for c in cmds if "glass_text" in c))

    def test_the_glass_is_always_clear_whatever_an_old_frost_says(self):
        # a frost over a playing video makes the compositor blur the whole screen again for every frame; there is
        # no frost setting any more, so every style gets the same clear glass
        feats = ["glass", "glass-shaped", "glass-text", "glass-windows", "glass-blur", "glass-tune"]
        live = {"sway_original_version": "x", "swayctl_features": feats}
        for style in ("glass", "liquid"):
            ctx = Context(Path("/app"), live=live, values={"appearance": {"ui_style": style}}, theme=themes.BUILTIN["dark"])
            cmds = EffectsModule().commands("effects", schema.defaults()["effects"] | {"glass": True, "glass_blur": 60}, None, ctx)
            for ns in ("swayctl-quick", "swayctl-notifications", "swayctl-osd"):
                self.assertIn(f'layer_effects "{ns}" "glass_blur 0"', cmds, (style, ns))
            self.assertIn("blur_passes 0", cmds)
        desk = Context(Path("/app"), live=live, values={"appearance": {"ui_style": "glass"}}, theme=themes.BUILTIN["dark"])
        cmds = EffectsModule().commands("effects", schema.defaults()["effects"] | {"glass": True}, None, desk)
        self.assertIn('layer_effects "swayctl-frame" "glass enable"', cmds)
        self.assertIn('layer_effects "swayctl-frame" "glass_blur 0"', cmds)

    def test_the_launchers_selected_row_keeps_its_own_colour_not_the_key(self):
        from swayctl_center.modules import components
        css = components.key_ink_css("#ffffff")
        # text on the solid accent can't be inked by the compositor: it would show the key's purple
        self.assertIn("window.ink-key .launcher-row.selected label", css)
        self.assertIn("window.ink-key .launcher-row.selected image", css)

    def test_key_ink_for_quick_settings_the_launcher_and_notifications_only(self):
        cmds = self.cmds("dark", ["glass", "glass-shaped", "glass-text", "glass-windows", "glass-ink"])
        self.assertIn('layer_effects "swayctl-quick" "glass_text auto"', cmds)
        self.assertIn('layer_effects "swayctl-launcher" "glass_text auto"', cmds)
        self.assertIn('layer_effects "swayctl-notifications" "glass_text auto"', cmds)
        self.assertFalse(any(c == 'layer_effects "swayctl-osd" "glass_text auto"' for c in cmds))
        # the bar and the apps are not glass: no ink to pick for them
        self.assertFalse(any('"swayctl-bar" "glass_text' in c for c in cmds))
        self.assertFalse(any(c.startswith("[app_id=") and "glass text" in c for c in cmds))

    def test_needs_the_feature(self):
        cmds = self.cmds("dark", ["glass", "glass-shaped"])
        self.assertFalse(any("glass_text" in c for c in cmds))


class GlassTest(unittest.TestCase):
    FX_GLASS = FX | {"swayctl_features": ["ipc-features", "smooth-scroll", "glass"]}

    def test_needs_the_feature(self):
        cmds = run(FX, glass=True)  # SwayFX without the glass patch
        self.assertFalse(any("glass" in c for c in cmds))
        self.assertNotIn("blur_passes 3", cmds)

    def test_corner_radius_in_range(self):
        # SwayFX rejects layer_effects corner_radius outside 0-99, and a
        # rejected effect used to wipe every effect set before it
        import re
        for cmds in (run(self.FX_GLASS, glass=True),
                     run(self.FX_GLASS | {"swayctl_features": ["glass", "glass-shaped"]}, glass=True)):
            for c in cmds:
                m = re.search(r'"corner_radius (\d+)"', c)
                if m:
                    self.assertLessEqual(int(m.group(1)), 99, c)

    def test_glass_on_our_surfaces_only(self):
        cmds = run(self.FX_GLASS, glass=True)
        self.assertIn('layer_effects "swayctl-osd" "glass enable"', cmds)
        self.assertIn('layer_effects "swayctl-osd" "corner_radius 22"', cmds)
        # the bar is never glass: it has no effects at all while the panels' effects are off
        self.assertIn('layer_effects "swayctl-bar" "reset"', cmds)
        self.assertFalse(any('"swayctl-bar" "glass enable"' in c for c in cmds))
        panels = run(self.FX_GLASS, glass=True, panels=True)
        self.assertIn('layer_effects "swayctl-bar" "glass disable"', panels)
        # Quick Settings: shaped glass (per control) needs the fork's shaped-glass patch
        self.assertIn('layer_effects "swayctl-quick" "glass disable"', cmds)
        shaped = run(self.FX_GLASS | {"swayctl_features": ["glass", "glass-shaped"]}, glass=True)
        self.assertIn('layer_effects "swayctl-quick" "glass enable"', shaped)
        self.assertIn('layer_effects "swayctl-quick" "blur_ignore_transparent enable"', shaped)
        # the card surfaces, the Quick Settings panel and the bar keep shadow
        # off (their compositor box shadow read as a halo around the pills)
        self.assertIn('layer_effects "swayctl-quick" "shadows disable"', shaped)
        self.assertIn('layer_effects "swayctl-quick" "corner_radius 20"', shaped)
        self.assertIn('layer_effects "swayctl-notifications" "shadows disable"', shaped)
        self.assertIn('layer_effects "swayctl-launcher" "glass enable"', shaped)
        self.assertIn('layer_effects "swayctl-notifications" "glass enable"', shaped)
        for ns in ("swayctl-bar", "swayctl-frame", "swayctl-traymenu"):
            self.assertFalse(any(c == f'layer_effects "{ns}" "glass enable"' for c in shaped), ns)
        self.assertIn('layer_effects "swayctl-osd" "glass_refraction 50"', cmds)
        self.assertIn('layer_effects "swayctl-osd" "glass_highlight 0.9"', cmds)
        self.assertIn("blur_passes 0", cmds)  # frost 0 (default): clear body
        clear = run(self.FX_GLASS, glass=True, glass_blur=0)
        self.assertIn("blur_passes 0", clear)  # frost 0: what's behind stays sharp
        self.assertIn('layer_effects "waybar" "reset"', cmds)  # panels off: others untouched
        # bezel + body + dispersion only on forks that speak glass-tune
        tune = run(self.FX_GLASS | {"swayctl_features": ["glass", "glass-tune"]}, glass=True)
        self.assertIn('layer_effects "swayctl-osd" "glass_edge 21"', tune)  # 100 % of its corners
        self.assertIn('layer_effects "swayctl-osd" "glass_thickness 90"', tune)
        # a faint colour fringe, the one look's (no setting)
        self.assertIn('layer_effects "swayctl-osd" "glass_chroma 0.1"', tune)
        self.assertFalse(any("glass_edge" in c for c in cmds))
        # bar / Quick Settings: the same Liquid glass knobs as windows…
        lens = run(self.FX_GLASS | {"swayctl_features": ["glass", "glass-shaped", "glass-tune"]}, glass=True)
        # every popup has the OSD's bezel (21): the same lens everywhere
        for ns in ("swayctl-launcher", "swayctl-quick", "swayctl-notifications", "swayctl-osd"):
            self.assertIn(f'layer_effects "{ns}" "glass_edge 21"', lens, ns)
        self.assertIn('layer_effects "swayctl-launcher" "glass_highlight 0.9"', lens)
        self.assertIn('layer_effects "swayctl-quick" "glass_thickness 90"', lens)
        # …and there are no sliders: whatever an old settings file holds, every pane gets the one look
        moved = run(self.FX_GLASS | {"swayctl_features": ["glass", "glass-shaped", "glass-tune"]},
                    glass=True, glass_refraction=120, glass_thickness=300, glass_highlight=0.2,
                    glass_edge=40, glass_chroma=0.7, glass_blur=60)
        for ns in ("swayctl-launcher", "swayctl-quick", "swayctl-osd", "swayctl-notifications"):
            for want in ("glass_refraction 50", "glass_thickness 90", "glass_highlight 0.9", "glass_edge 21", "glass_chroma 0.1"):
                self.assertIn(f'layer_effects "{ns}" "{want}"', moved, (ns, want))

    def test_glass_blur_needs_its_feature(self):
        self.assertFalse(any("glass_blur" in c for c in run(self.FX_GLASS, glass=True)))
        fx = self.FX_GLASS | {"swayctl_features": ["glass", "glass-blur"]}
        self.assertIn('layer_effects "swayctl-osd" "glass_blur 0"', run(fx, glass=True))

    def test_off_disables_glass(self):
        cmds = run(self.FX_GLASS, glass=False, panels=True)
        self.assertIn('layer_effects "swayctl-bar" "glass disable"', cmds)
        self.assertIn("blur_saturation 1", cmds)


if __name__ == "__main__":
    unittest.main()


class GlassEdgeCapTest(unittest.TestCase):
    def test_edge_capped_at_corner_radius(self):
        from swayctl_center.modules.effects import glass_edge
        self.assertEqual(glass_edge("chosua", 100), 17)       # its bubbles: 18 px corners
        self.assertEqual(glass_edge("chosua", 50), 8)         # half of that (8.5, to even)
        self.assertEqual(glass_edge("chosua", 300), 26)       # asked for 3x, held to 1.5x: past it colours bleed in
        self.assertEqual(glass_edge("swayctl-bar", 400), 14)  # out of range (an old px value): 100 %
        self.assertEqual(glass_edge("unknown-app", 100), 11)  # libadwaita panes


class PortalGlassTest(unittest.TestCase):
    def test_theme_and_dropin(self):
        import tempfile
        from unittest import mock
        from swayctl_center import portalglass
        css = portalglass.css(True, "#0a84ff", "#ffffff", 0.1)
        self.assertNotIn("#FF00FE", css)           # the theme's text, not the key ink
        self.assertIn("alpha(#1c1c1e, 0.76)", css)  # one sheet of the dark surface
        self.assertIn("@import", css)              # on the desktop's GTK 3 theme
        with tempfile.TemporaryDirectory() as d, mock.patch("subprocess.run") as run:
            home = Path(d)
            self.assertTrue(portalglass.sync(True, css, home))
            self.assertEqual((portalglass.theme_dir(home) / "gtk-3.0/gtk.css").read_text(), css)
            self.assertIn("GTK_THEME=SwayctlGlass", portalglass.dropin_path(home).read_text())
            self.assertTrue(any("try-restart" in c.args[0] for c in run.call_args_list))
            run.reset_mock()
            self.assertFalse(portalglass.sync(True, css, home))   # unchanged: no restart
            run.assert_not_called()
            self.assertTrue(portalglass.sync(False, "", home))    # off: the drop-in goes
            self.assertFalse(portalglass.dropin_path(home).exists())

    def test_no_portal_sheet(self):
        ctx = Context(Path("/app"), live={"sway_original_version": "x", "swayctl_features":
                      ["glass", "glass-shaped", "glass-text", "glass-windows"]},
                      theme=themes.BUILTIN["dark"])
        cmds = EffectsModule().commands("effects", schema.defaults()["effects"] | {"glass": True}, None, ctx)
        self.assertFalse(any(c.startswith('[app_id="xdg-desktop-portal-gtk"]') and "glass enable" in c for c in cmds))


class AnimationKindsTest(unittest.TestCase):
    def ctx(self):
        return Context(Path("/app"), live={"sway_original_version": "x", "swayctl_features": ["animation-kinds"]},
                       theme=themes.BUILTIN["dark"])

    def test_each_kind_and_length(self):
        v = schema.defaults()["effects"] | {"anim_open_close": True, "anim_workspace": False, "anim_move": True,
                                            "anim_duration": 300}
        cmds = EffectsModule().commands("effects", v, None, self.ctx())
        self.assertIn("animation_duration_ms 300", cmds)
        self.assertIn("animations open_close enable", cmds)
        self.assertIn("animations workspace disable", cmds)
        self.assertIn("animations move enable", cmds)

    def test_every_kind_is_its_own_switch(self):
        base = schema.defaults()["effects"] | {"anim_duration": 250}
        for kind, flag in (("open_close", "anim_open_close"), ("workspace", "anim_workspace"), ("move", "anim_move")):
            cmds = EffectsModule().commands("effects", base | {flag: True}, None, self.ctx())
            self.assertIn("animation_duration_ms 250", cmds, kind)  # one kind alone is enough
            for other in ("open_close", "workspace", "move"):
                self.assertIn(f"animations {other} {'enable' if other == kind else 'disable'}", cmds, f"{kind}/{other}")

    def test_nothing_on_means_no_animation_at_all(self):
        cmds = EffectsModule().commands("effects", schema.defaults()["effects"], None, self.ctx())
        self.assertIn("animation_duration_ms 0", cmds)
        self.assertIn("animations workspace disable", cmds)

    def test_the_old_master_switch_does_nothing_now(self):
        v = schema.defaults()["effects"] | {"animations": True}
        self.assertIn("animation_duration_ms 0", EffectsModule().commands("effects", v, None, self.ctx()))

    def test_no_kinds_without_the_fork_feature(self):
        ctx = Context(Path("/app"), live={"sway_original_version": "x", "swayctl_features": []},
                      theme=themes.BUILTIN["dark"])
        cmds = EffectsModule().commands("effects", schema.defaults()["effects"] | {"anim_move": True}, None, ctx)
        self.assertFalse(any(c.startswith("animations ") for c in cmds))


class SpringAndSlideTest(unittest.TestCase):
    def ctx(self, *features):
        return Context(Path("/app"), live={"sway_original_version": "x", "swayctl_features": list(features)},
                       theme=themes.BUILTIN["dark"])

    def test_spring_settings_reach_the_fork(self):
        v = schema.defaults()["effects"] | {"animations": True, "anim_curve": "spring", "anim_response": 280, "anim_bounce": 15}
        cmds = EffectsModule().commands("effects", v, None, self.ctx("animation-spring"))
        self.assertIn("animation_curve spring", cmds)
        self.assertIn("animation_spring 280 0.15", cmds)
        cmds = EffectsModule().commands("effects", v | {"anim_curve": "ease"}, None, self.ctx("animation-spring"))
        self.assertIn("animation_curve ease", cmds)

    def test_slide_is_a_setting(self):
        v = schema.defaults()["effects"] | {"animations": True}
        on = EffectsModule().commands("effects", v, None, self.ctx("animation-slide"))
        off = EffectsModule().commands("effects", v | {"anim_slide": False}, None, self.ctx("animation-slide"))
        self.assertIn("animations workspace_slide enable", on)
        self.assertIn("animations workspace_slide disable", off)

    def test_neither_is_sent_to_a_fork_without_them(self):
        v = schema.defaults()["effects"] | {"animations": True}
        cmds = EffectsModule().commands("effects", v, None, self.ctx("animation-kinds"))
        self.assertFalse(any(c.startswith(("animation_curve", "animation_spring", "animations workspace_slide")) for c in cmds))

    def test_spring_values_are_bounded(self):
        for name, bad in (("anim_response", 50), ("anim_response", 5000), ("anim_bounce", -1), ("anim_bounce", 90)):
            with self.assertRaises(ValueError, msg=f"{name}={bad}"):
                schema.lookup("effects", name).validate(bad)

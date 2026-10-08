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

    def test_modern_preset(self):
        cmds = run(FX, **presets.MODERN["effects"])
        self.assertIn("corner_radius 10", cmds)
        self.assertIn("default_dim_inactive 0.06", cmds)
        self.assertIn('layer_effects "waybar" "blur enable"', cmds)
        self.assertIn('layer_effects "waybar" "corner_radius 14"', cmds)  # theme radius_lg
        self.assertIn("shadow_color #00000070", cmds)


class WindowGlassTest(unittest.TestCase):
    FX = {"sway_original_version": "x", "swayctl_features": ["glass", "glass-shaped", "glass-windows"]}

    def test_settings_window_glass(self):
        m = EffectsModule()
        ctx = Context(Path("/app"), live=self.FX, theme=themes.BUILTIN["dark"])
        v = schema.defaults()["effects"] | {"glass": True}
        cmds = m.commands("effects", v, None, ctx)
        rule = [c for c in cmds if c.startswith("for_window")]
        # quoted: sway splits at commas
        what = ('"glass enable, glass refraction 50, glass blur 0, glass highlight 0.9, '
                'border none, shadows disable"')
        # the settings window and every other glass app (ChoSua) get the same rule
        self.assertEqual(rule, ['for_window [app_id="io.github.huyhappy.SwayctlCenter.Settings"] ' + what,
                                'for_window [app_id="chosua"] ' + what])
        self.assertIn('[app_id="chosua"] glass enable, glass refraction 50, '
                      'glass blur 0, glass highlight 0.9, border none, shadows disable', cmds)
        self.assertIn('[app_id="io.github.huyhappy.SwayctlCenter.Settings"] glass enable, glass refraction 50, '
                      'glass blur 0, glass highlight 0.9, border none, shadows disable', cmds)
        # same again: no new for_window (sway keeps every rule)
        self.assertFalse(any(c.startswith("for_window") for c in m.commands("effects", v, None, ctx)))
        off = m.commands("effects", v | {"glass": False}, None, ctx)
        self.assertIn('for_window [app_id="io.github.huyhappy.SwayctlCenter.Settings"] "glass disable"', off)
        self.assertIn("No matching node.", m.tolerated_errors)  # settings window not open

    def test_needs_the_feature(self):
        ctx = Context(Path("/app"), live=FX | {"swayctl_features": ["glass"]}, theme=themes.BUILTIN["dark"])
        cmds = EffectsModule().commands("effects", schema.defaults()["effects"] | {"glass": True}, None, ctx)
        self.assertFalse(any("SwayctlCenter" in c for c in cmds))


class GlassTextTest(unittest.TestCase):
    FX = {"sway_original_version": "x", "swayctl_features": ["glass", "glass-shaped", "glass-text", "glass-windows"]}

    def cmds(self, theme):
        ctx = Context(Path("/app"), live=self.FX, theme=themes.BUILTIN[theme])
        return EffectsModule().commands("effects", schema.defaults()["effects"] | {"glass": True}, None, ctx)

    def test_no_adaptive_text(self):
        # the glass doesn't adapt to what's behind it any more
        for theme in ("dark", "light"):
            cmds = self.cmds(theme)
            self.assertTrue(all(c.endswith('"glass_text none"') for c in cmds if "glass_text" in c))
            self.assertTrue(any("glass text none" in c for c in cmds if "SwayctlCenter" in c))

    def test_key_ink(self):
        # with the fork's key ink: ChoSua, the bar and Quick Settings get
        # `auto`; the other surfaces and the settings window keep picking
        ctx = Context(Path("/app"), live={"sway_original_version": "x", "swayctl_features":
                      ["glass", "glass-shaped", "glass-text", "glass-windows", "glass-ink"]},
                      theme=themes.BUILTIN["dark"])
        cmds = EffectsModule().commands("effects", schema.defaults()["effects"] | {"glass": True}, None, ctx)
        self.assertTrue(any(c.startswith('[app_id="chosua"]') and "glass text auto" in c for c in cmds))
        self.assertIn('layer_effects "swayctl-bar" "glass_text auto"', cmds)
        self.assertIn('layer_effects "swayctl-quick" "glass_text auto"', cmds)
        self.assertFalse(any(c == 'layer_effects "swayctl-osd" "glass_text auto"' for c in cmds))
        self.assertTrue(any(c.startswith('[app_id="io.github.huyhappy.SwayctlCenter.Settings"]')
                            and "glass text none" in c for c in cmds))

    def test_chosua_light_text(self):
        # ChoSua draws light text and leaves its readability to the glass;
        # the settings window still picks its own per pane
        cmds = self.cmds("dark")
        self.assertTrue(any(c.startswith('[app_id="chosua"]') and c.endswith("glass text light, border none, shadows disable")
                            for c in cmds))
        self.assertTrue(any(c.startswith('for_window [app_id="chosua"]') and "glass text light" in c for c in cmds))
        self.assertTrue(any(c.startswith('[app_id="io.github.huyhappy.SwayctlCenter.Settings"]') and "glass text none" in c
                            for c in cmds))

    def test_needs_the_feature(self):
        ctx = Context(Path("/app"), live=self.FX | {"swayctl_features": ["glass", "glass-shaped"]},
                      theme=themes.BUILTIN["dark"])
        cmds = EffectsModule().commands("effects", schema.defaults()["effects"] | {"glass": True}, None, ctx)
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
        # the bar is shaped glass too (a pane per module): needs shaped-glass
        self.assertIn('layer_effects "swayctl-bar" "glass disable"', cmds)
        # Quick Settings: shaped glass (per control) needs the fork's shaped-glass patch
        self.assertIn('layer_effects "swayctl-quick" "glass disable"', cmds)
        shaped = run(self.FX_GLASS | {"swayctl_features": ["glass", "glass-shaped"]}, glass=True)
        self.assertIn('layer_effects "swayctl-quick" "glass enable"', shaped)
        self.assertIn('layer_effects "swayctl-quick" "blur_ignore_transparent enable"', shaped)
        # the card surfaces, the Quick Settings panel and the bar keep shadow
        # off (their compositor box shadow read as a halo around the pills)
        self.assertIn('layer_effects "swayctl-quick" "shadows disable"', shaped)
        self.assertIn('layer_effects "swayctl-quick" "corner_radius 20"', shaped)
        self.assertIn('layer_effects "swayctl-bar" "shadows disable"', shaped)
        self.assertIn('layer_effects "swayctl-notifications" "shadows disable"', shaped)
        self.assertIn('layer_effects "swayctl-bar" "glass enable"', shaped)
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
        # dispersion follows the setting (default 0.35)
        self.assertIn('layer_effects "swayctl-osd" "glass_chroma 0.35"', tune)
        self.assertFalse(any("glass_edge" in c for c in cmds))
        # bar / Quick Settings: the same Liquid glass knobs as windows…
        lens = run(self.FX_GLASS | {"swayctl_features": ["glass", "glass-shaped", "glass-tune"]}, glass=True)
        self.assertIn('layer_effects "swayctl-bar" "glass_edge 14"', lens)  # capped at the pills' radius
        self.assertIn('layer_effects "swayctl-quick" "glass_edge 16"', lens)
        self.assertIn('layer_effects "swayctl-bar" "glass_highlight 0.9"', lens)
        self.assertIn('layer_effects "swayctl-quick" "glass_thickness 90"', lens)
        # …and they move with the sliders (no demo-capsule pinning)
        moved = run(self.FX_GLASS | {"swayctl_features": ["glass", "glass-shaped", "glass-tune"]},
                    glass=True, glass_refraction=120, glass_thickness=300, glass_highlight=0.2,
                    glass_edge=40, glass_chroma=0)
        self.assertIn('layer_effects "swayctl-bar" "glass_refraction 120"', moved)
        self.assertIn('layer_effects "swayctl-quick" "glass_thickness 300"', moved)
        self.assertIn('layer_effects "swayctl-quick" "glass_highlight 0.2"', moved)
        self.assertIn('layer_effects "swayctl-bar" "glass_edge 6"', moved)  # 40 % of the pills' 14
        self.assertIn('layer_effects "swayctl-osd" "glass_chroma 0"', moved)

    def test_glass_blur_needs_its_feature(self):
        self.assertFalse(any("glass_blur" in c for c in run(self.FX_GLASS, glass=True, glass_blur=0)))
        fx = self.FX_GLASS | {"swayctl_features": ["glass", "glass-blur"]}
        self.assertIn('layer_effects "swayctl-osd" "glass_blur 0"', run(fx, glass=True, glass_blur=0))

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
        self.assertEqual(glass_edge("chosua", 300), 51)       # up to 3x
        self.assertEqual(glass_edge("swayctl-bar", 400), 14)  # out of range (an old px value): 100 %
        self.assertEqual(glass_edge("unknown-app", 100), 11)  # libadwaita panes

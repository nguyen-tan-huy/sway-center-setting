import unittest
from pathlib import Path

from swayctl_center import presets, schema, themes
from swayctl_center.modules import Context, components
from swayctl_center.modules.background import BackgroundModule
from swayctl_center.modules.components import BarModule, frame_css, popup_flat_css
from swayctl_center.modules.effects import EffectsModule


def ctx(**appearance):
    values = {"appearance": {"style": "modern", **appearance}, "effects": {"glass": False}}
    return Context(data_dir=Path("/tmp"), values=values, theme=themes.BUILTIN["dark"])


class FrameStyleTest(unittest.TestCase):
    def test_the_style_sits_on_the_edge_with_gaps_and_flat_quick_settings(self):
        f = presets.ui_style_values("frame")
        self.assertTrue(all(f["bar"][f"margin_{e}"] == 0 for e in ("top", "right", "bottom", "left")))
        self.assertEqual(f["layout"]["gaps_inner"], 8)
        self.assertGreater(f["effects"]["corner_radius"], 0)
        self.assertFalse(f["effects"]["glass"])
        self.assertEqual(f["appearance"]["quick_surface"], "flat")

    def test_colour_must_be_a_six_digit_hex(self):
        key = schema.lookup("appearance", "frame_color")
        self.assertEqual(key.validate("#102030"), "#102030")
        for bad in ("102030", "#123", "red", "#12345g"):
            with self.assertRaises(ValueError, msg=bad):
                key.validate(bad)

    def test_bar_margins_stay_zero_in_the_frame_style(self):
        v = schema.defaults()["bar"]
        self.assertEqual(BarModule().margins(v, ctx(ui_style="frame"))["top"], 0)
        self.assertEqual(BarModule().margins(v, ctx(ui_style="rounded"))["top"], 0)   # attached in every style

    def test_bar_is_one_solid_colour_and_text_follows_its_lightness(self):
        dark = frame_css(ctx(ui_style="frame", frame_color="#0b1014"))
        self.assertIn("background: #0b1014", dark)
        self.assertIn("color: #ffffff", dark)
        self.assertNotIn("blur(", dark)
        light = frame_css(ctx(ui_style="frame", frame_color="#eef0f4"))
        self.assertIn("color: #111317", light)
        self.assertEqual(frame_css(ctx(ui_style="rounded")), "")

    def test_a_bad_colour_falls_back(self):
        self.assertIn("#0b1014", frame_css(ctx(ui_style="frame", frame_color="nope")))

    def test_flat_quick_settings_take_a_tone_of_the_frame_colour(self):
        dark = popup_flat_css(ctx(quick_surface="flat", frame_color="#000000"))
        self.assertIn("background: #1f1f1f", dark)  # 12% toward white
        light = popup_flat_css(ctx(quick_surface="flat", frame_color="#ffffff"))
        self.assertIn("background: #ebebeb", light)  # 8% toward black
        self.assertEqual(popup_flat_css(ctx(quick_surface="auto")), "")

    def test_the_osd_and_the_launcher_are_flat_blocks_too(self):
        css = popup_flat_css(ctx(quick_surface="flat", frame_color="#000000"))
        self.assertIn(".osd.osd.osd { background: #1f1f1f", css)
        for sheet in ("launcher-search", "launcher-results", "launcher-keys", "launcher-suggest"):
            self.assertIn(f".{sheet}.{sheet}.{sheet}", css)
        self.assertIn(".launcher-search.launcher-search.launcher-search, .launcher-results.launcher-results.launcher-results, "
                      ".launcher-keys.launcher-keys.launcher-keys, .launcher-suggest.launcher-suggest.launcher-suggest "
                      "{ background: #000000;", css)  # the bar's colour exactly, not a tone of it
        self.assertIn(".launcher-row.selected label", css)  # the chosen row keeps white text on the accent
        self.assertNotIn("blur(", css)

    def test_the_pages_inside_quick_settings_follow_the_tone_too(self):
        css = popup_flat_css(ctx(quick_surface="flat", frame_color="#000000"))
        self.assertIn("list.boxed-list.boxed-list.boxed-list { background: #1f1f1f", css)  # the rows' block
        self.assertIn("border-top: 1px solid", css)                                        # divided by a line
        self.assertIn(".quick-panel headerbar.flat.flat.flat { background: #1f1f1f", css)  # the title has a block, it sits over any window
        # the footer buttons sit outside every block: opaque, or the window behind shows through them
        self.assertIn(".quick-footer button.circular { background: #1f1f1f", css)

    def test_no_blur_behind_any_flat_popup(self):
        v = schema.defaults()["effects"] | {"panels": True}
        live = {"sway_original_version": "x", "swayctl_features": ["glass"]}
        flat = Context(Path("/app"), live=live, theme=themes.BUILTIN["dark"],
                       values={"appearance": {"style": "modern", "quick_surface": "flat"}})
        cmds = EffectsModule().commands("effects", v, None, flat)
        for ns in ("swayctl-quick", "swayctl-osd", "swayctl-launcher"):
            self.assertIn(f'layer_effects "{ns}" "blur disable"', cmds, ns)
        auto = Context(Path("/app"), live=live, theme=themes.BUILTIN["dark"],
                       values={"appearance": {"style": "modern", "quick_surface": "auto"}})
        self.assertIn('layer_effects "swayctl-osd" "blur enable"', EffectsModule().commands("effects", v, None, auto))

    def test_gaps_are_settings_you_can_change(self):
        for name in ("gaps_inner", "gaps_outer"):
            self.assertFalse(schema.lookup("layout", name).hidden, name)
        from swayctl_center import ui
        self.assertIn("gaps_inner", dict(ui.GROUPS["layout"])["~More window options"])
        for name in ("gaps_inner", "gaps_outer"):
            self.assertIn(8, [v for _l, v in ui.LEVELS[f"layout.{name}"]])  # what the frame style sets

    def test_the_wallpaper_gives_way_to_the_frame_colour(self):
        v = schema.defaults()["background"]
        v = {**v, "image": "wallpapers/x.jpg"}
        cmds = BackgroundModule().commands("background", v, None, ctx(ui_style="frame", frame_color="#123456"))
        self.assertEqual(cmds, ["output * bg #123456 solid_color"])
        other = BackgroundModule().commands("background", v, None, ctx(ui_style="rounded"))
        self.assertIn("wallpapers/x.jpg", other[0])

    def test_the_frame_is_always_solid_so_its_colour_shows_in_the_frame_style(self):
        from swayctl_center import ui
        vw = ui.AppearancePage.visible_when
        self.assertNotIn("frame_surface", vw)
        self.assertTrue(vw["frame_color"]({"ui_style": "frame"}))
        self.assertFalse(vw["frame_color"]({"ui_style": "rounded"}))

    def test_the_bars_icon_style_reaches_it(self):
        c = ctx(ui_style="frame")
        bar = schema.defaults()["bar"]
        self.assertEqual(BarModule().native_config(bar, c)["icon_style"], "ipados")
        self.assertEqual(BarModule().native_config(bar | {"icon_style": "system"}, c)["icon_style"], "system")
        key = schema.lookup("bar", "icon_style")
        self.assertEqual(key.default, "ipados")
        with self.assertRaises(ValueError):
            key.validate("material")

    def test_hex_helpers(self):
        self.assertEqual(components._mix_hex("#000000", "#ffffff", 0.5), "#808080")
        self.assertAlmostEqual(components._luminance("#ffffff"), 1.0)
        self.assertEqual(components._luminance("#000000"), 0.0)


if __name__ == "__main__":
    unittest.main()

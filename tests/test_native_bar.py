import json
import unittest
from pathlib import Path

from swayctl_center import schema, themes
from swayctl_center.modules import Context
from swayctl_center.modules.components import OSD_KEYS, BarModule


def ctx(style="modern"):
    v = schema.defaults()
    v["appearance"]["style"] = style
    return Context(Path("/app"), values=v, theme=themes.BUILTIN["dark"])


def bar(**kw):
    return schema.defaults()["bar"] | {"program": "swayctl-bar"} | kw


class NativeBarTest(unittest.TestCase):
    def test_program(self):
        self.assertEqual(BarModule().programs(bar(), ctx())[""],
                         ["swayctl-bar", "--config-dir", "/app/generated/bar"])
        self.assertEqual(BarModule().programs(schema.defaults()["bar"] | {"program": "waybar"}, ctx())[""][0], "waybar")

    def test_modules_map_and_status_cluster(self):
        v = bar(modules_left=["sway/workspaces", "sway/mode"], modules_center=["clock"],
                modules_right=["pulseaudio", "network", "battery#bat2", "tray", "custom/weather"])
        cfg = json.loads(BarModule().files(v, ctx())["config.json"])
        self.assertEqual(cfg["modules_left"], ["workspaces", "mode"])
        self.assertEqual(cfg["modules_center"], ["clock"])
        self.assertEqual(cfg["modules_right"], ["status", "tray"])  # one cluster, unknown custom dropped

    def test_one_status_cluster(self):
        cfg = BarModule().native_config(bar(modules_left=["sway/workspaces", "custom/notifications"],
                                            modules_right=["network", "tray"]), ctx())
        self.assertEqual(cfg["modules_left"], ["workspaces"])
        self.assertEqual(cfg["modules_right"], ["status", "tray"])

    def test_status_always_reachable(self):
        cfg = BarModule().native_config(bar(modules_right=[]), ctx())
        self.assertEqual(cfg["modules_right"], ["status"])

    def test_clock_format_and_margins(self):
        cfg = BarModule().native_config(bar(), ctx())
        self.assertEqual(cfg["clock_format"], "%H:%M")
        self.assertEqual(cfg["margins"], [8, 8, 0, 8])
        self.assertEqual(BarModule().native_config(bar(), ctx("classic"))["margins"], [0, 0, 0, 0])

    def test_css_from_tokens(self):
        t = themes.BUILTIN["dark"]
        css = BarModule().files(bar(), ctx())["style.css"]
        self.assertIn(f"@define-color accent_bg_color {t.accent};", css)
        self.assertIn(f".tile.active {{ background: {t.accent};", css)
        self.assertIn("border-radius: 14px", css)

    def test_bar_height_sizes_the_modules(self):
        """bar.height used to be only the window's minimum: lower than the
        pills' CSS (~34 px) did nothing, higher just stretched them."""
        from swayctl_center.modules.components import bar_size_css
        c = ctx()
        c.values["effects"]["glass"] = True
        for h in (26, 34, 53):
            css = BarModule().files(bar(height=h), c)["style.css"]
            self.assertIn(f"/* bar.height = {h}px", css)
        # pill + gaps + the 1.5 px glass rim add up to the height asked for
        css = bar_size_css(53, 1.5)
        self.assertIn("min-height: 40px; margin-top: 5px", css)   # 40 + 3 (rim) + 2*5 = 53
        # too low for the text: the font shrinks to fit instead
        self.assertIn("window.bar label { font-size:", bar_size_css(24, 1.5, 12))
        self.assertNotIn("font-size", bar_size_css(53, 1.5, 12))
        # 0 = fit the contents: no sizing rules
        self.assertEqual(bar_size_css(0), "")

    def test_glass_settings_reach_the_adaptive_ink(self):
        """Settings > Liquid glass: every knob the ink pick uses lands in
        config.json (the bar reloads it: bar, Quick Settings, OSD retag),
        and the glass toggle switches the CSS to the lens ink."""
        c = ctx()
        b = json.loads(BarModule().files(bar(), c)["config.json"])["backdrop"]
        self.assertFalse(b["lens"])
        self.assertNotIn("halo-", BarModule().files(bar(), c)["style.css"])
        c.values["effects"] |= {"glass": True, "glass_opacity": 50, "glass_blur": 40}
        files = BarModule().files(bar(), c)
        b = json.loads(files["config.json"])["backdrop"]
        self.assertTrue(b["lens"])
        self.assertAlmostEqual(b["lens_tint"], 0.10)   # = the capsule body CSS paints
        self.assertAlmostEqual(b["frost"], 0.40)
        self.assertIn(".on-dark.halo-4 label", files["style.css"])
        c.values["effects"]["glass_opacity"] = 80
        self.assertAlmostEqual(json.loads(BarModule().files(bar(), c)["config.json"])["backdrop"]["lens_tint"], 0.16)
        # the bar's files are rebuilt whenever effects change
        self.assertIn("effects", BarModule.depends_on)

    def test_glass_css(self):
        c = ctx()
        self.assertNotIn("liquid glass", BarModule().files(bar(), c)["style.css"])
        c.values["effects"]["glass"] = True
        css = BarModule().files(bar(), c)["style.css"]
        self.assertIn("liquid glass", css)
        # the pill tint follows effects.glass_opacity (thinned while glass is
        # on: default 10 % -> 4 % floor so shaped panes still draw)
        self.assertIn("alpha(white, 0.040)", css)
        c.values["effects"]["glass_opacity"] = 50
        css = BarModule().files(bar(), c)["style.css"]
        self.assertIn("alpha(white, 0.100)", css)   # moves with the slider
        self.assertIn("1.5px solid alpha(white, 0.88)", css)
        self.assertIn("#1d1d1f", css)
        self.assertIn("alpha(black, 0.14)", css)  # soft dark trough under the blue bar
        self.assertIn("inset 0 1px 0 alpha(white, 0.55)", css)

    def test_osd_keys_bound_then_released(self):
        m = BarModule()
        on = m.commands("bar", bar(), None, ctx())
        self.assertIn(f"bindsym --no-warn --locked {OSD_KEYS[0][0]} exec swayctl-bar osd volume-up", on)
        off = m.commands("bar", bar(program="waybar"), None, ctx())
        self.assertIn(f"unbindsym --locked {OSD_KEYS[0][0]}", off)
        self.assertEqual(m.commands("bar", bar(program="waybar"), None, ctx()), [])


if __name__ == "__main__":
    unittest.main()

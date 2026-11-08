import tempfile
import unittest
from pathlib import Path

from swayctl_center import presets, schema
from swayctl_center.daemon import Daemon
from swayctl_center.modules import appearance, by_section
from swayctl_center.store import Store


class UiStyleTest(unittest.TestCase):
    def test_every_value_a_style_sets_is_valid(self):
        for style, tree in presets.UI_STYLES.items():
            for section, items in tree.items():
                for name, value in items.items():
                    key = schema.lookup(section, name)
                    self.assertEqual(key.validate(value), value, f"{style} {section}.{name}")

    def test_scrolling_has_its_own_profile(self):
        for style, tree in presets.UI_STYLES.items():
            self.assertNotIn("scrolling", tree, style)
        for name, tree in presets.SCROLL_PROFILES.items():
            for section, items in tree.items():
                for key, value in items.items():
                    self.assertEqual(schema.lookup(section, key).validate(value), value, f"{name} {key}")
        self.assertIn(schema.lookup("scrolling", "profile").default, presets.SCROLL_PROFILES)
        self.assertFalse(presets.scroll_values("off")["scrolling"]["mouse_smooth"])
        glides = [presets.scroll_values(n)["scrolling"]["touchpad_glide"] for n in ("light", "smooth", "fluid")]
        self.assertEqual(glides, sorted(glides))

    def test_square_has_no_gaps_and_sits_on_the_edge(self):
        flat = presets.ui_style_values("flat")
        self.assertEqual(flat["layout"], {"gaps_inner": 0, "gaps_outer": 0})
        self.assertEqual(flat["effects"]["corner_radius"], 0)
        self.assertTrue(all(flat["bar"][f"margin_{e}"] == 0 for e in ("top", "right", "bottom", "left")))
        rounded = presets.ui_style_values("rounded")
        self.assertGreater(rounded["layout"]["gaps_inner"], 0)
        self.assertGreater(rounded["effects"]["corner_radius"], 0)

    def test_only_liquid_turns_the_glass_on(self):
        glass = {n: presets.ui_style_values(n)["effects"]["glass"] for n in ("flat", "rounded", "liquid")}
        self.assertEqual(glass, {"flat": False, "rounded": False, "liquid": True})
        self.assertEqual(presets.ui_style_values("liquid")["effects"]["corner_radius"], 12)

    def test_square_styles_give_the_theme_square_tokens(self):
        from swayctl_center import themes
        r = appearance.Resolved(themes.BUILTIN["light"], "light", "fixed", None)
        self.assertEqual(appearance.shaped(r, "flat").theme.tokens["radius_lg"], 0)
        self.assertGreater(appearance.shaped(r, "rounded").theme.tokens["radius_lg"], 0)

    def test_the_bar_has_no_margins_in_any_style(self):
        from swayctl_center import themes
        from swayctl_center.modules import Context
        from swayctl_center.modules.components import BarModule
        v = schema.defaults()["bar"]
        base = themes.BUILTIN["light"]
        square = appearance.shaped(appearance.Resolved(base, "light", "fixed", None), "flat").theme
        for theme, expect in ((square, 0), (base, 0)):   # attached to the edge, square or round
            ctx = Context(data_dir=Path("/tmp"), values={"appearance": {"style": "modern"}}, theme=theme)
            self.assertEqual(BarModule().margins(v, ctx)["top"], expect)

    def test_rounded_with_glass_on_becomes_liquid(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "settings.json").write_text('{"version": 1, "values": {"appearance": {"ui_style": "rounded"}, "effects": {"glass": true}}}')
            daemon = Daemon.__new__(Daemon)
            daemon.store = Store(d)
            daemon.modules = by_section()
            daemon.store.load()
            daemon._retire_old_choices()
            self.assertEqual(daemon.store.effective()["appearance"]["ui_style"], "liquid")

    def test_an_old_floating_choice_becomes_square(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "settings.json").write_text('{"version": 1, "values": {"appearance": {"ui_style": "floating"}}}')
            daemon = Daemon.__new__(Daemon)
            daemon.store = Store(d)
            daemon.modules = by_section()
            daemon.store.load()
            daemon._retire_old_choices()
            v = daemon.store.effective()
            self.assertEqual(v["appearance"]["ui_style"], "flat")
            self.assertEqual(v["layout"]["gaps_inner"], 0)
            self.assertEqual(v["bar"]["margin_top"], 0)


if __name__ == "__main__":
    unittest.main()

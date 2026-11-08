import tempfile
import unittest
from pathlib import Path

from swayctl_center import presets, schema
from swayctl_center.daemon import Daemon
from swayctl_center.modules import by_section
from swayctl_center.store import Store


def daemon(tmp: Path) -> Daemon:
    d = Daemon.__new__(Daemon)
    d.store = Store(tmp)
    d.modules = by_section()
    d.store.load()
    return d


class AnimationFeelTest(unittest.TestCase):
    def test_the_defaults_are_the_off_feel(self):
        self.assertEqual(presets.anim_feel_matching(schema.defaults()), "off")
        self.assertEqual(schema.lookup("effects", "anim_feel").default, "off")

    def test_every_feel_is_a_choice_and_a_complete_set_of_valid_values(self):
        key = schema.lookup("effects", "anim_feel")
        self.assertEqual(set(presets.ANIM_FEELS) | {"custom"}, set(key.choices))
        for name, preset in presets.ANIM_FEELS.items():
            for k, v in preset["effects"].items():
                self.assertEqual(schema.lookup("effects", k).validate(v), v, (name, k))

    def test_choosing_a_feel_sets_the_bundle_and_is_named_back(self):
        with tempfile.TemporaryDirectory() as d:
            dm = daemon(Path(d))
            for name in ("smooth", "playful", "quick", "subtle", "off"):
                dm.store.set_many(presets.anim_feel_values(name))
                dm._name_profiles()
                self.assertEqual(dm.store.effective()["effects"]["anim_feel"], name)

    def test_tuning_one_option_makes_it_custom_and_putting_it_back_names_it_again(self):
        with tempfile.TemporaryDirectory() as d:
            dm = daemon(Path(d))
            dm.store.set_many(presets.anim_feel_values("smooth"))
            dm._name_profiles()
            dm.store.set("effects", "anim_bounce", 30)
            dm._name_profiles()
            self.assertEqual(dm.store.effective()["effects"]["anim_feel"], "custom")
            dm.store.set("effects", "anim_bounce", 8)
            dm._name_profiles()
            self.assertEqual(dm.store.effective()["effects"]["anim_feel"], "smooth")

    def test_an_interface_style_that_animates_reads_as_smooth(self):
        # the styles turn the kinds on and leave the spring at its defaults, which is the smooth feel
        with tempfile.TemporaryDirectory() as d:
            dm = daemon(Path(d))
            dm.store.set_many(presets.ui_style_values("rounded"))
            dm._name_profiles()
            self.assertEqual(dm.store.effective()["effects"]["anim_feel"], "smooth")
            dm.store.set_many(presets.ui_style_values("flat"))
            dm._name_profiles()
            self.assertEqual(dm.store.effective()["effects"]["anim_feel"], "off")

    def test_the_settings_page_shows_the_feel_and_folds_the_rest_away(self):
        from swayctl_center import ui
        for groups in (ui.EFFECT_GROUPS, ui.GROUPS["effects"]):
            shown = {t: names for t, names in groups}
            self.assertEqual(shown["Animations"], ["anim_feel"])
            self.assertEqual(shown["Shadows"], ["shadow_style"])
            more = [names for t, names in groups if t == "~More effect options"][0]
            self.assertIn("anim_curve", more)
            self.assertIn("anim_open_close", more)


class DesktopProfilesTest(unittest.TestCase):
    PATHS = ("effects.anim_feel", "layout.window_style", "effects.shadow_style", "effects.glass_style",
             "priority.responsiveness")

    def test_every_profile_is_a_choice_and_a_complete_set_of_valid_values(self):
        for path in self.PATHS:
            section, name = path.split(".")
            key = schema.lookup(section, name)
            self.assertEqual(set(presets.PROFILES[path]) | {"custom"}, set(key.choices), path)
            self.assertIn(key.default, key.choices)
            for profile, preset in presets.PROFILES[path].items():
                for sec, items in preset.items():
                    for k, v in items.items():
                        self.assertEqual(schema.lookup(sec, k).validate(v), v, (path, profile, k))

    def test_the_defaults_name_themselves(self):
        d = schema.defaults()
        for path in self.PATHS:
            section, name = path.split(".")
            self.assertEqual(presets.profile_matching(path, d), d[section][name], path)

    def test_choosing_a_profile_names_itself_and_no_other_choice_is_disturbed(self):
        with tempfile.TemporaryDirectory() as d:
            dm = daemon(Path(d))
            for path in self.PATHS:
                for name in presets.PROFILES[path]:
                    dm.store.set_many(presets.profile_values(path, name))
                    dm._name_profiles()
                    eff = dm.store.effective()
                    section, key = path.split(".")
                    self.assertEqual(eff[section][key], name, (path, name))
            # the last of each was applied: every one still reads as itself
            for path in self.PATHS:
                section, key = path.split(".")
                self.assertEqual(eff[section][key], list(presets.PROFILES[path])[-1], path)

    def test_an_interface_style_and_the_window_style_name_each_other(self):
        with tempfile.TemporaryDirectory() as d:
            dm = daemon(Path(d))
            for style, window in (("flat", "compact"), ("rounded", "balanced"), ("liquid", "balanced"),
                                  ("frame", "balanced"), ("minimal", "spacious")):
                dm.store.set_many(presets.ui_style_values(style))
                dm._name_profiles()
                self.assertEqual(dm.store.effective()["layout"]["window_style"], window, style)

    def test_a_glass_look_sets_every_knob_and_the_liquid_style_reads_as_clear(self):
        with tempfile.TemporaryDirectory() as d:
            dm = daemon(Path(d))
            knobs = ("glass_refraction", "glass_blur", "glass_opacity", "glass_highlight", "glass_edge",
                     "glass_thickness", "glass_chroma")
            for name, preset in presets.GLASS_STYLES.items():
                if name != "off":
                    self.assertEqual(set(preset["effects"]) - {"glass"}, set(knobs), name)
            dm.store.set_many(presets.ui_style_values("liquid"))
            dm._name_profiles()
            self.assertEqual(dm.store.effective()["effects"]["glass_style"], "clear")
            dm.store.set("effects", "glass_refraction", 77)
            dm._name_profiles()
            self.assertEqual(dm.store.effective()["effects"]["glass_style"], "custom")

    def test_a_hand_tuned_value_makes_a_profile_custom(self):
        with tempfile.TemporaryDirectory() as d:
            dm = daemon(Path(d))
            dm.store.set_many(presets.profile_values("effects.shadow_style", "soft"))
            dm.store.set("effects", "shadow_blur_radius", 45)
            dm._name_profiles()
            self.assertEqual(dm.store.effective()["effects"]["shadow_style"], "custom")
            dm.store.set("priority", "cpu_cap", 50)
            dm._name_profiles()
            self.assertEqual(dm.store.effective()["priority"]["responsiveness"], "custom")

    def test_the_desktop_page_leads_with_the_profiles_and_folds_the_values_away(self):
        from swayctl_center import ui
        self.assertEqual(dict(ui.GROUPS["layout"])[""], ["window_style", "focus_follows_mouse"])
        self.assertEqual(dict(ui.GROUPS["priority"])[""], ["responsiveness"])
        self.assertEqual(dict(ui.GROUPS["bar"])[""], ["position", "height"])
        for section in ("layout", "priority", "bar"):
            self.assertTrue([t for t, _n in ui.GROUPS[section] if t.startswith("~")], section)


if __name__ == "__main__":
    unittest.main()


class SettingsWindowCornersTest(unittest.TestCase):
    def test_the_settings_window_draws_no_corners_of_its_own(self):
        from swayctl_center import ui
        self.assertIn("border-radius: 0", ui.SettingsWindow._corner_css(object()))

import unittest

from swayctl_center import presets, schema


class PresetTest(unittest.TestCase):
    def test_every_value_is_valid(self):
        for preset in presets.PRESETS.values():
            for section, items in preset.items():
                for name, value in items.items():
                    self.assertEqual(schema.lookup(section, name).validate(value), value)

    def test_themes_exist(self):
        from swayctl_center import themes
        m = presets.MODERN["appearance"]
        self.assertIn(m["light_theme"], themes.BUILTIN)
        self.assertIn(m["dark_theme"], themes.BUILTIN)

    def test_classic_is_defaults_and_matches_fresh_install(self):
        self.assertEqual(presets.current(schema.defaults()), "classic")

    def test_current(self):
        v = schema.defaults()
        for s, items in presets.MODERN.items():
            v[s].update(items)
        self.assertEqual(presets.current(v), "modern")
        v["layout"]["gaps_inner"] = 3
        self.assertIsNone(presets.current(v))


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from swayctl_center import daemon, schema
from swayctl_center.store import Store


class RetireOldChoicesTest(unittest.TestCase):
    def test_old_values_are_dropped_others_kept(self):
        d = Path(tempfile.mkdtemp())
        store = Store(d)
        store.load()
        store.set("bar", "program", "waybar")
        store.set("appearance", "style", "classic")
        store.set("auth", "lock_screen", "swaylock")
        store.set("layout", "gaps_inner", 12)
        dm = daemon.Daemon.__new__(daemon.Daemon)
        dm.store = store
        dm._retire_old_choices()
        for section, name in daemon.RETIRED_CHOICES:
            self.assertFalse(store.is_set(section, name), f"{section}.{name}")
        self.assertEqual(store.effective()["bar"]["program"], "swayctl-bar")
        self.assertEqual(store.effective()["appearance"]["style"], "modern")
        self.assertEqual(store.effective()["layout"]["gaps_inner"], 12)

    def test_waybar_settings_become_swayctl_bar_settings(self):
        d = Path(tempfile.mkdtemp())
        store = Store(d)
        store.load()
        store._data["shared"]["bar"] = {"modules_left": ["sway/workspaces", "custom/notifications"],
                                         "modules_right": ["idle_inhibitor", "pulseaudio", "tray"],
                                         "clock_format": "{:%a %H:%M}"}
        dm = daemon.Daemon.__new__(daemon.Daemon)
        dm.store = store
        dm._retire_old_choices()
        bar = store.effective()["bar"]
        self.assertEqual(bar["modules_left"], ["workspaces"])  # Quick Settings kept on the right only
        self.assertEqual(bar["modules_right"], ["status", "tray"])
        self.assertEqual(bar["clock_format"], "%a %H:%M")

    def test_old_choices_are_not_in_the_ui(self):
        for section, name in daemon.RETIRED_CHOICES:
            self.assertTrue(schema.lookup(section, name).hidden)

    def test_explanations_reach_the_ui(self):
        keys = {k["section"] + "." + k["name"]: k for k in (k.to_json() for k in schema.KEYS)}
        self.assertIn("help", keys["effects.glass_blur"])
        self.assertIn("help", keys["effects.glass_highlight"])
        self.assertIn("help", keys["effects.glass_edge"])
        self.assertIn("help", keys["effects.glass_thickness"])
        self.assertIn("help", keys["effects.glass_chroma"])
        self.assertNotIn("help", keys["bar.config_file"])

    def test_every_level_is_a_value_its_key_accepts(self):
        from swayctl_center.ui import LEVELS, slider_out
        for path, levels in LEVELS.items():
            key = schema.lookup(*path.rsplit(".", 1)) if path.count(".") == 1 else None
            if key is None:  # "input.touchpad" style sections
                section, name = path.rsplit(".", 1)
                key = schema.lookup(section, name)
            self.assertIsNotNone(key, path)
            self.assertEqual(len({v for _l, v in levels}), len(levels), path)
            for label, value in levels:
                self.assertEqual(key.validate(slider_out(key.type, value)), slider_out(key.type, value), f"{path} {label}")
            self.assertIn(key.default, [v for _l, v in levels], f"{path}: default is one of the steps")

    def test_int_sliders_do_not_send_floats(self):
        # Gtk.Scale is float: glass_opacity 48.113 used to fail store validation
        from swayctl_center.ui import SLIDERS, slider_out
        for path in ("effects.glass_opacity", "effects.glass_refraction",
                     "effects.glass_blur", "effects.glass_edge", "effects.glass_thickness"):
            key = schema.lookup(*path.split(".", 1))
            self.assertEqual(key["type"] if isinstance(key, dict) else key.type, "int", path)
            self.assertIn(path, SLIDERS)
            self.assertEqual(slider_out("int", 48.113), 48)
            self.assertEqual(slider_out("float", 0.556), 0.556)
        k = schema.lookup("effects", "glass_opacity")
        self.assertEqual(k.validate(48.0), 48)  # whole float ok
        self.assertEqual(k.validate(48), 48)
        with self.assertRaises(ValueError):
            k.validate(48.113)
        store = Store(Path(tempfile.mkdtemp()))
        store.load()
        self.assertEqual(store.set("effects", "glass_opacity", 48.0), 48)
        self.assertEqual(store.effective()["effects"]["glass_opacity"], 48)
        with self.assertRaises(ValueError):
            store.set("effects", "glass_opacity", 48.113)

    def test_demo_body_defaults(self):
        # winaviation liquid-glass-demo capsule (Precision Lens): clear body,
        # bright rim; every surface (windows, bar, quick, osd) follows these
        eff = schema.defaults()["effects"]
        self.assertEqual(eff["glass_edge"], 100)
        self.assertEqual(eff["glass_thickness"], 90)
        self.assertEqual(eff["glass_refraction"], 50)
        self.assertEqual(eff["glass_chroma"], 0.35)
        self.assertEqual(eff["glass_blur"], 0)
        self.assertEqual(eff["glass_highlight"], 0.90)
        self.assertEqual(eff["glass_opacity"], 10)


if __name__ == "__main__":
    unittest.main()

import unittest

from swayctl_center import keyd_sync, schema
from swayctl_center.modules.keyremap import expand, parse_keyd

KEYS = {"capslock", "esc", "leftcontrol", "leftalt", "rightalt", "a"}


class KeyRemapTest(unittest.TestCase):
    def test_import_pairs_swaps(self):
        text = "[ids]\n*\n\n[main]\ncapslock = esc\nesc = capslock\nrightalt = layer(control)  # altgr\n"
        remaps, other, copilot = parse_keyd(text)
        self.assertEqual(copilot, "default")
        self.assertEqual(remaps, [{"from": "capslock", "to": "esc", "swap": True},
                                  {"from": "rightalt", "to": "leftcontrol", "swap": False}])
        self.assertFalse(other)

    def test_import_notices_what_it_cant_show(self):
        self.assertTrue(parse_keyd("[main]\ncapslock = overload(control, esc)\n")[1])
        self.assertTrue(parse_keyd("[ids]\n046d:b023\n[main]\na = b\n")[1])
        self.assertTrue(parse_keyd("[main]\na = b\n[nav]\nh = left\n")[1])

    def test_rendered_for_keyd(self):
        remaps = expand([{"from": "capslock", "to": "esc", "swap": True},
                         {"from": "rightalt", "to": "leftcontrol", "swap": False}])
        text = keyd_sync.render(remaps, KEYS)
        self.assertIn("[main]\ncapslock = esc\nesc = capslock\nrightalt = layer(control)\n", text)

    def test_copilot_key(self):
        text = keyd_sync.render([{"from": "capslock", "to": "esc"}], KEYS | {"f23", "enter"}, "super")
        self.assertIn("\n[copilot]\n\n[meta+shift]\nf23 = layer(copilot)\n\n[meta+shift+copilot]\n", text)
        self.assertIn("\nenter = M-enter\n", text)
        self.assertIn("\ncapslock = M-esc\n", text)       # remaps still apply
        self.assertNotIn("leftalt = M-", text)             # modifiers keep working
        self.assertNotIn("f23 = M-", text)
        self.assertEqual(parse_keyd(keyd_sync.render([], KEYS, "rightcontrol"))[2], "rightcontrol")
        self.assertNotIn("meta+shift", keyd_sync.render([], KEYS, "default"))
        self.assertNotIn("meta+shift", keyd_sync.render([], KEYS, "command(x)"))
        self.assertEqual(parse_keyd(text), ([{"from": "capslock", "to": "esc", "swap": False}], False, "super"))

    def test_root_side_only_takes_key_names(self):
        bad = [{"from": "a", "to": "command(touch /tmp/pwned)"}, {"from": "a\n[x]", "to": "esc"},
               {"from": "capslock", "to": "esc"}]
        text = keyd_sync.render(bad, KEYS)
        self.assertNotIn("command", text)
        self.assertTrue(text.endswith("[main]\ncapslock = esc\n"))

    def test_validator(self):
        v = schema.validate_remaps([{"from": "CapsLock", "to": "esc", "swap": True},
                                    {"from": "esc", "to": "leftalt"}])
        self.assertEqual(v, [{"from": "esc", "to": "leftalt", "swap": False}])  # replaces the swap using esc
        with self.assertRaises(ValueError):
            schema.validate_remaps([{"from": "a", "to": "command(x)"}])
        with self.assertRaises(ValueError):
            schema.validate_remaps([{"from": "a", "to": "a"}])


if __name__ == "__main__":
    unittest.main()

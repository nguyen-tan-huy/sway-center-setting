import json
import tempfile
import unittest
from pathlib import Path

from swayctl_center import jsonc, schema, swayconfig, themes
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule, lock_command
from swayctl_center.modules.input import InputModule
from swayctl_center.modules.layout import LayoutModule

WAYBAR = """{
    // my bar
    "layer": "top", "position": "top", "height": 30, "spacing": 4,
    "margin-top": 2,
    "include": ["modules.jsonc"],
    "modules-left": ["custom/media", "sway/workspaces"],
    "modules-right": ["battery#bat2", "clock",],
    "clock": {"format": "{:%H:%M:%S}", "tooltip": true},
    "custom/media": {"exec": "~/.config/waybar/scripts/media.sh"},
}"""


class FakeIPC:
    def __init__(self, inputs=()):
        self.inputs = list(inputs)

    def get_inputs(self):
        return self.inputs


class JsoncTest(unittest.TestCase):
    def test_comments_strings_trailing_commas(self):
        text = '{"u": "http://x", /* c */ "a": [1, 2,], // t\n}'
        self.assertEqual(jsonc.loads(text), {"u": "http://x", "a": [1, 2]})


class BarBaseConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "config.jsonc").write_text(WAYBAR)

    def tearDown(self):
        self.tmp.cleanup()

    def adopted(self):
        return BarModule().related_values("bar", "config_file", str(self.d / "config.jsonc"), None)

    def test_adopt_values_from_base(self):
        got = self.adopted()
        self.assertEqual(got["modules_left"], ["custom/media", "sway/workspaces"])
        self.assertEqual(got["modules_center"], [])
        self.assertEqual(got["margin_top"], 2)
        self.assertEqual(got["clock_format"], "{:%H:%M:%S}")
        for k, val in got.items():  # everything adopted is valid for the schema
            schema.lookup("bar", k).validate(val)

    def test_merge_keeps_user_modules_and_fixes_includes(self):
        v = schema.defaults()["bar"] | self.adopted()
        v |= {"config_file": str(self.d / "config.jsonc"), "margin_top": 8,
              "modules_right": ["clock", "battery#bat2", "cpu"]}
        c = Context(self.d / "app", values=schema.defaults(), theme=themes.BUILTIN["nord"])
        cfg = json.loads(BarModule().files(v, c)["config.json"])
        self.assertEqual(cfg["margin-top"], 8)
        self.assertEqual(cfg["custom/media"]["exec"], "~/.config/waybar/scripts/media.sh")
        self.assertEqual(cfg["include"], [str(self.d / "modules.jsonc")])
        self.assertEqual(cfg["modules-right"], ["clock", "battery#bat2", "cpu"])
        self.assertIn("format", cfg["cpu"])            # built-in default for a newly added module
        self.assertNotIn("sway/workspaces", cfg)       # in the base already: waybar's own defaults
        self.assertEqual(cfg["clock"]["tooltip"], True)  # the user's other clock options are kept


class LayoutOptionsTest(unittest.TestCase):
    def test_border_style_and_behaviour(self):
        v = schema.defaults()["layout"] | {"border_style": "normal", "border": 3, "focus_follows_mouse": "no",
                                           "workspace_auto_back_and_forth": True}
        cmds = LayoutModule().commands("layout", v, {"border_style"})
        self.assertIn("default_border normal 3", cmds)
        self.assertIn("[tiling] border normal 3", cmds)
        self.assertIn("focus_follows_mouse no", cmds)
        self.assertIn("workspace_auto_back_and_forth yes", cmds)
        v["border_style"] = "none"
        self.assertIn("default_border none", LayoutModule().commands("layout", v, None))

    def test_import(self):
        cfg = swayconfig.parse("focus_follows_mouse no\nworkspace_auto_back_and_forth yes\n"
                               "default_border normal 4\n", Path("/x"))
        got = LayoutModule().import_current(None, cfg, None)["layout"]
        self.assertEqual((got["focus_follows_mouse"], got["workspace_auto_back_and_forth"],
                          got["border_style"], got["border"]), ("no", True, "normal", 4))


class InputOptionsTest(unittest.TestCase):
    def test_keyboard_import_and_commands(self):
        cfg = swayconfig.parse("input type:keyboard {\n  xkb_layout us,vn\n  xkb_options caps:escape\n}\n"
                               "input * repeat_rate 50\n", Path("/x"))
        ipc = FakeIPC([{"type": "keyboard", "repeat_delay": 300, "repeat_rate": 40, "libinput": {}}])
        got = InputModule().import_current(ipc, cfg, None)["input.keyboard"]
        self.assertEqual(got, {"repeat_delay": 300, "repeat_rate": 50, "xkb_layout": "us,vn",
                               "xkb_options": "caps:escape"})
        v = schema.defaults()["input.keyboard"] | got
        cmds = InputModule().commands("input.keyboard", v, None)
        self.assertIn("input type:keyboard xkb_layout us,vn", cmds)
        self.assertNotIn("xkb_variant", " ".join(cmds))  # empty on a full apply: skipped
        self.assertEqual(InputModule().commands("input.keyboard", v | {"xkb_options": ""}, {"xkb_options"}),
                         ['input type:keyboard xkb_options ""'])

    def test_touchpad_import_maps_libinput_fields(self):
        li = {"tap": "enabled", "tap_drag": "enabled", "tap_drag_lock": "disabled",
              "click_method": "clickfinger", "send_events": "disabled_on_external_mouse",
              "accel_speed": 0.2, "accel_profile": "adaptive"}
        got = InputModule().import_current(FakeIPC([{"type": "touchpad", "libinput": li}]),
                                           swayconfig.Config(), None)["input.touchpad"]
        self.assertEqual(got, {"tap": True, "drag": True, "drag_lock": False, "click_method": "clickfinger",
                               "events": "disabled_on_external_mouse", "pointer_accel": 0.2,
                               "accel_profile": "adaptive"})
        for k, val in got.items():
            schema.lookup("input.touchpad", k).validate(val)


class LockTest(unittest.TestCase):
    def test_options(self):
        values = schema.defaults()
        values["idle"] |= {"lock_background": "wallpaper", "show_failed_attempts": True,
                           "ignore_empty_password": True}
        values["background"]["image"] = "wallpapers/a.jpg"
        cmd = lock_command(Context(Path("/app"), values=values, theme=themes.BUILTIN["nord"]))
        self.assertEqual(cmd[-6:], ["-i", "/app/wallpapers/a.jpg", "-s", "fill", "-F", "-e"])


if __name__ == "__main__":
    unittest.main()

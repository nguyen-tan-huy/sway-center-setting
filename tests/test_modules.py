import unittest

import tempfile
from pathlib import Path

from swayctl_center import schema, swayconfig
from swayctl_center.daemon import diff
from swayctl_center.modules import Context
from swayctl_center.modules.input import InputModule
from swayctl_center.modules.layout import LayoutModule


class FakeIPC:
    def __init__(self, config="", inputs=(), outputs=()):
        self.config, self.inputs, self.outputs = config, list(inputs), list(outputs)

    def get_outputs(self):
        return self.outputs

    def get_config(self):
        return self.config

    def get_inputs(self):
        return self.inputs


CTX = Context(data_dir=Path("/nonexistent"))


class LayoutTest(unittest.TestCase):
    def setUp(self):
        self.values = schema.defaults()["layout"] | {"border": 5, "gaps_inner": 6}

    def test_full_apply_does_not_touch_existing_window_borders(self):
        cmds = LayoutModule().commands("layout", self.values, None)
        self.assertIn("default_border pixel 5", cmds)
        self.assertIn("gaps inner all set 6", cmds)
        self.assertFalse(any(c.startswith("[") for c in cmds))

    def test_changed_border_restyles_existing_windows(self):
        cmds = LayoutModule().commands("layout", self.values, {"border"})
        self.assertIn("[tiling] border pixel 5", cmds)
        self.assertNotIn("[floating] border pixel 2", cmds)

    def test_import_from_config_text(self):
        text = "default_border pixel 5\ngaps inner 3\nsmart_gaps on\nhide_edge_borders --i3 smart\n# gaps outer 9\n"
        cfg = swayconfig.parse(text, Path("/nonexistent"))
        got = LayoutModule().import_current(FakeIPC(), cfg, CTX)["layout"]
        self.assertEqual(got, {"border": 5, "border_style": "pixel", "gaps_inner": 3, "smart_gaps": "on",
                               "hide_edge_borders": "smart"})


class InputTest(unittest.TestCase):
    def test_commands(self):
        values = {"tap": True, "scroll_method": "none", "pointer_accel": 0.2}
        cmds = InputModule().commands("input.touchpad", values, None)
        # sway owns scrolling here (no smooth scrolling): "none" would leave nobody scrolling
        self.assertEqual(cmds, ["input type:touchpad tap enabled",
                                "input type:touchpad pointer_accel 0.2",
                                "input type:touchpad scroll_method two_finger"])
        self.assertEqual(InputModule().commands("input.touchpad", values, {"tap"}),
                         ["input type:touchpad tap enabled"])

    def test_import_skips_virtual_devices(self):
        inputs = [
            {"type": "pointer", "libinput": {"natural_scroll": "enabled"}},
            {"type": "pointer", "libinput": {"accel_profile": "flat", "accel_speed": 0.0, "natural_scroll": "disabled"}},
            {"type": "touchpad", "libinput": {"accel_profile": "adaptive", "accel_speed": 0.0, "tap": "enabled",
                                              "dwt": "enabled", "natural_scroll": "enabled", "scroll_method": "none"}},
        ]
        got = InputModule().import_current(FakeIPC(inputs=inputs), swayconfig.Config(), CTX)
        self.assertEqual(got["input.pointer"], {"natural_scroll": False, "accel_profile": "flat", "pointer_accel": 0.0})
        self.assertTrue(got["input.touchpad"]["tap"])
        self.assertEqual(got["input.touchpad"]["scroll_method"], "none")


class DiffTest(unittest.TestCase):
    def test_diff(self):
        old = {"layout": {"border": 2, "gaps_inner": 0}}
        new = {"layout": {"border": 5, "gaps_inner": 0}, "input.touchpad": {"tap": True}}
        self.assertEqual(diff(old, new), {"layout": {"border"}, "input.touchpad": {"tap"}})


if __name__ == "__main__":
    unittest.main()


class MonitorLayoutTest(unittest.TestCase):
    def test_logical_size(self):
        from swayctl_center.modules.outputs import logical_size
        self.assertEqual(logical_size({"mode": "3072x1920@120.002Hz", "scale": 2.0}), (1536, 960))
        self.assertEqual(logical_size({"mode": "1920x1080", "scale": 1.0, "transform": "flipped-270"}), (1080, 1920))

    def test_dropped_monitor_sticks_to_an_edge(self):
        from swayctl_center.modules.outputs import snap
        laptop = (0, 0, 1536, 960)
        self.assertEqual(snap((1700, 400, 1920, 1080), [laptop], 100), (1536, 400))   # right, left as dropped
        self.assertEqual(snap((1600, 30, 1920, 1080), [laptop], 100), (1536, 0))      # top edges lined up
        self.assertEqual(snap((-100, -1200, 1920, 1080), [laptop], 50), (-100, -1080))  # above

    def test_normalized(self):
        from swayctl_center.modules.outputs import normalized
        self.assertEqual(normalized({"a": (0, 0), "b": (-1920, 10.4)}), {"a": [1920, 0], "b": [0, 10]})

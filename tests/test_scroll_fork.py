import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swayctl_center import schema
from swayctl_center.modules import Context, scrolling


class FakeIPC:
    def __init__(self, features):
        self.features = features

    def get_version(self):
        return {"sway_original_version": "1.12.0", "swayctl_features": self.features}


class CompositorScrollTest(unittest.TestCase):

    def test_plain_sway_keeps_service(self):
        m = scrolling.ScrollingModule()
        m.snapshot(FakeIPC(["ipc-features"]))
        v = schema.defaults()["scrolling"]
        self.assertEqual(m.commands("scrolling", v, None), [])
        self.assertTrue(scrolling.service_config(v)["touchpad"]["enabled"])

    def test_fork_sends_commands_and_stands_service_down(self):
        m = scrolling.ScrollingModule()
        m.snapshot(FakeIPC(["ipc-features", "smooth-scroll"]))
        v = schema.defaults()["scrolling"] | {"mouse_smooth": False}
        cmds = m.commands("scrolling", v, None)
        self.assertIn("input type:touchpad smooth_scroll enabled", cmds)
        self.assertIn("input type:pointer smooth_scroll disabled", cmds)
        self.assertIn("input type:touchpad scroll_friction 0.98", cmds)
        self.assertIn("input type:touchpad scroll_ramp 290 1.9", cmds)
        cfg = scrolling.service_config(v)
        self.assertFalse(cfg["touchpad"]["enabled"] or cfg["mouse"]["enabled"])
        d = Path(tempfile.mkdtemp())
        m.apply_extra("scrolling", v, None, Context(d))
        self.assertFalse(json.loads((d / "generated" / "smoothscroll.json").read_text())["touchpad"]["enabled"])

    def test_sway_keeps_scrolling_under_the_fork(self):
        scrolling._compositor["smooth"] = True
        with mock.patch.object(scrolling, "service_running", return_value=True):
            self.assertEqual(scrolling.sway_scroll_owner(schema.defaults(), "touchpad"), "compositor")

    def test_input_applied_first_still_knows_the_compositor(self):
        # at startup input comes before scrolling: its own snapshot must detect the fork
        from swayctl_center.modules import Context
        from swayctl_center.modules.input import InputModule
        m = InputModule()
        values = schema.defaults()
        with mock.patch.object(scrolling, "service_running", return_value=True):
            live = m.snapshot(FakeIPC(["smooth-scroll"]))
            cmds = m.commands("input.touchpad", values["input.touchpad"], None,
                              Context(Path("/app"), live=live, values=values))
        self.assertNotIn("input type:touchpad scroll_method none", cmds)
        self.assertIn("input type:touchpad scroll_method two_finger", cmds)

    def test_direction_and_speed_flow_into_sway(self):
        from swayctl_center.modules.input import scroll_values
        sc = schema.defaults()["scrolling"] | {"touchpad_natural": True, "touchpad_speed": 2.4, "mouse_speed": 0.9}
        tp = scroll_values("input.touchpad", {"natural_scroll": False, "scroll_method": "none"}, "compositor", sc)
        self.assertEqual(tp, {"natural_scroll": True, "scroll_factor": 2.0, "scroll_method": "two_finger"})
        ptr = scroll_values("input.pointer", {"natural_scroll": True}, "compositor", sc)
        self.assertEqual(ptr, {"natural_scroll": False, "scroll_factor": 2.0})

    def tearDown(self):
        scrolling._compositor.update(smooth=False, features=[])


if __name__ == "__main__":
    unittest.main()

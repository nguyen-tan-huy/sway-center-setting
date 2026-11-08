import unittest

from swayctl_center import wsguard


def W(n, o, v=False, f=False):
    return {"name": n, "output": o, "visible": v, "focused": f}


class WsGuardTest(unittest.TestCase):
    def test_workspace_pushed_to_new_monitor_goes_back(self):
        before = [W("1", "eDP-1", True, True), W("2", "eDP-1")]
        now = [W("1", "DP-2", True), W("2", "eDP-1", True)]
        self.assertEqual(wsguard.plan(before, {"eDP-1"}, now, {"eDP-1", "DP-2"}),
                         ['workspace "1"', 'move workspace to output "eDP-1"', 'workspace "1"'])

    def test_nothing_to_do_without_a_new_monitor(self):
        ws = [W("1", "eDP-1", True, True)]
        self.assertEqual(wsguard.plan(ws, {"eDP-1"}, ws, {"eDP-1"}), [])

    def test_unplugging_is_left_to_sway(self):
        before = [W("1", "DP-2", True, True), W("2", "eDP-1", True)]
        now = [W("1", "eDP-1", True), W("2", "eDP-1")]
        self.assertEqual(wsguard.plan(before, {"eDP-1", "DP-2"}, now, {"eDP-1"}), [])

    def test_name_is_quoted(self):
        self.assertEqual(wsguard._q('a"b'), '"a\\"b"')


if __name__ == "__main__":
    unittest.main()


class SwitchTest(unittest.TestCase):
    def test_workspace_on_the_other_monitor_comes_here(self):
        ws = [dict(W("1", "DP-2"), num=1), dict(W("2", "eDP-1", f=True), num=2)]
        self.assertEqual(wsguard.switch_commands(ws, 1),
                         ["workspace number 1", 'move workspace to output "eDP-1"'])

    def test_new_or_local_workspace_just_switches(self):
        ws = [dict(W("2", "eDP-1", f=True), num=2)]
        self.assertEqual(wsguard.switch_commands(ws, 5), ["workspace number 5"])
        self.assertEqual(wsguard.switch_commands(ws, 2), ["workspace number 2"])


class FreshConfigTest(unittest.TestCase):
    def test_built_in_first_and_side_by_side(self):
        from swayctl_center.modules.outputs import fresh_config
        mode = lambda w, h: {"width": w, "height": h, "refresh": 60000}
        live = [{"name": "DP-2", "make": "A", "model": "B", "serial": "C", "active": True, "scale": 1.0,
                 "rect": {"x": 9, "y": 9}, "current_mode": mode(1920, 1080)},
                {"name": "eDP-1", "active": True, "scale": 2.0, "rect": {"x": 5, "y": 5},
                 "current_mode": mode(3072, 1920)}]
        cfg = fresh_config(live)
        self.assertEqual(list(cfg), ["eDP-1", "A B C"])
        self.assertEqual(cfg["eDP-1"]["position"], [0, 0])
        self.assertEqual(cfg["A B C"]["position"], [1536, 0])


class MainOutputTest(unittest.TestCase):
    def test_choice_then_built_in_then_first(self):
        from swayctl_center.modules.outputs import main_output
        live = [{"name": "DP-2", "make": "A", "model": "B", "serial": "C", "active": True},
                {"name": "eDP-1", "active": True}]
        self.assertEqual(main_output(live, "A B C"), "DP-2")
        self.assertEqual(main_output(live, ""), "eDP-1")
        self.assertEqual(main_output(live, "gone"), "eDP-1")
        self.assertEqual(main_output(live[:1], ""), "DP-2")

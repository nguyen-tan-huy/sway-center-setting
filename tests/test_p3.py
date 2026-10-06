import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swayctl_center import schema, swayconfig, themes, units
from tests.legacy import legacy_defaults
from swayctl_center.modules import Context
from swayctl_center.modules.components import (BarModule, ClipboardModule, IdleModule,
                                               NotificationsModule, lock_command)


def ctx(d="/app", theme="dark", **values):
    v = legacy_defaults()
    v["font"].update(family="Inter", size=12)
    for section, items in values.items():
        v[section].update(items)
    return Context(Path(d), values=v, theme=themes.BUILTIN[theme])


class BarTest(unittest.TestCase):
    def test_config_and_style(self):
        c = ctx()
        v = legacy_defaults()["bar"] | {"position": "bottom", "modules_right": ["clock", "tray"]}
        files = BarModule().files(v, c)
        cfg = json.loads(files["config.json"])
        self.assertEqual(cfg["position"], "bottom")
        self.assertEqual(cfg["modules-right"], ["clock", "tray"])
        self.assertIn("clock", cfg)  # module config included for used modules only
        self.assertNotIn("battery", cfg)
        self.assertIn("window#waybar { background: #1c1c1e; color: #f5f5f7; }", files["style.css"])
        self.assertIn('font-family: "Inter", "Symbols Nerd Font", sans-serif; font-weight: 400; font-size: 16px', files["style.css"])
        self.assertEqual(BarModule().programs(v, c)[""],
                         ["waybar", "-c", "/app/generated/bar/config.json", "-s", "/app/generated/bar/style.css"])

    def test_module_validation(self):
        key = schema.lookup("bar", "modules_left")
        self.assertEqual(key.validate(["clock", "clock", "tray"]), ["clock", "tray"])
        # settings saved for waybar convert; what swayctl-bar can't show drops
        self.assertEqual(key.validate(["sway/workspaces", "pulseaudio", "battery#bat2", "custom/media"]),
                         ["workspaces", "status"])
        self.assertEqual(key.validate(["Sway Workspaces", "clock; rm"]), [])
        with self.assertRaises(ValueError):
            key.validate([5])


class NotificationsTest(unittest.TestCase):
    def test_files(self):
        v = legacy_defaults()["notifications"] | {"program": "swaync", "position_x": "left", "width": 350}
        files = NotificationsModule().files(v, ctx(theme="light"))
        cfg = json.loads(files["config.json"])
        self.assertEqual((cfg["positionX"], cfg["notification-window-width"]), ("left", 350))
        self.assertIn("--noti-bg: 255, 255, 255;", files["style.css"])  # OSD milk
        self.assertIn("--noti-bg-alpha: 0.65;", files["style.css"])
        self.assertIn("--text-color: #1d1d1f;", files["style.css"])


class IdleTest(unittest.TestCase):
    def test_lock_command_uses_theme(self):
        cmd = lock_command(ctx(theme="dark"))
        self.assertEqual(cmd[:4], ["swaylock", "-f", "-c", "1c1c1e"])

    def test_programs(self):
        v = legacy_defaults()["idle"] | {"lock_after": 120, "screen_off_after": 0}
        argv = IdleModule().programs(v, ctx())[""]
        self.assertEqual(argv[:4], ["swayidle", "-w", "timeout", "120"])
        self.assertTrue(argv[4].startswith("swaylock -f -c 1c1c1e"))
        self.assertNotIn("resume", argv)
        self.assertEqual(argv[5], "before-sleep")

    def test_import_timeouts_from_config(self):
        text = ("set $lock swaylock -f -c 000000\n"
                "exec swayidle -w timeout 300 '$lock' timeout 900 'swaymsg \"output * power off\"' "
                "resume 'swaymsg \"output * power on\"' before-sleep '$lock'\n")
        cfg = swayconfig.parse(text, Path("/x"))
        with mock.patch.object(IdleModule, "is_running_elsewhere", return_value=True):
            got = IdleModule().import_current(None, cfg, ctx())["idle"]
        self.assertEqual(got, {"managed": False, "lock_after": 300, "screen_off_after": 900,
                               "lock_before_sleep": True})


class ClipboardTest(unittest.TestCase):
    def test_programs(self):
        v = legacy_defaults()["clipboard"] | {"max_items": 100, "images": False, "persist": False}
        progs = ClipboardModule().programs(v, ctx())
        self.assertEqual(list(progs), ["text"])
        progs = ClipboardModule().programs(v | {"persist": True}, ctx())
        self.assertEqual(progs["persist"], ["wl-clip-persist", "--clipboard", "regular"])
        # someone else's wl-clip-persist mustn't block the history watchers
        self.assertEqual(ClipboardModule().detect_for("persist"), [["-x", "wl-clip-persist"]])
        self.assertIn("wl-paste", ClipboardModule().detect_for("text")[0][1])
        self.assertEqual(progs["text"][-4:], ["cliphist", "-max-items", "100", "store"])
        self.assertEqual(ClipboardModule().unit_name("text"), "swayctl-center-clipboard-text.service")


class UnitsTest(unittest.TestCase):
    def test_zombies_are_ignored(self):
        import os
        self.assertFalse(units._is_zombie(os.getpid()))
        self.assertTrue(units._is_zombie(2 ** 22 + 12345))  # no such process


class ComponentApplyTest(unittest.TestCase):
    """apply_extra with systemd mocked out."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c = ctx(self.tmp.name)
        self.v = legacy_defaults()["bar"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_refuses_to_start_next_to_foreign_process(self):
        with mock.patch.object(units, "state", return_value=units.UnitState(False, "", 0)), \
             mock.patch.object(units, "foreign_pids", return_value=[941]), \
             mock.patch.object(units, "start") as start:
            errors = BarModule().apply_extra("bar", self.v, None, self.c)
        start.assert_not_called()
        self.assertIn("pid 941", errors[0])

    def test_start_then_reload_on_file_change_only(self):
        m = BarModule()
        with mock.patch.object(units, "state", return_value=units.UnitState(False, "", 0)), \
             mock.patch.object(units, "foreign_pids", return_value=[]), \
             mock.patch.object(units, "start", return_value=None) as start:
            self.assertEqual(m.apply_extra("bar", self.v, None, self.c), [])
        start.assert_called_once()
        desc = start.call_args[0][2]
        running = units.UnitState(True, desc, 1234)
        with mock.patch.object(units, "state", return_value=running), \
             mock.patch.object(units, "restart") as restart, \
             mock.patch.object(units, "start") as start2:
            m.apply_extra("bar", self.v, None, self.c)          # nothing changed
            restart.assert_not_called()
            self.c.theme = themes.BUILTIN["light"]                # theme changed -> new CSS
            m.apply_extra("bar", self.v, None, self.c)
            restart.assert_called_once_with("swayctl-center-bar.service")
            start2.assert_not_called()

    def test_unmanaged_stops_units(self):
        with mock.patch.object(units, "state", return_value=units.UnitState(True, "x", 1)), \
             mock.patch.object(units, "stop") as stop:
            BarModule().apply_extra("bar", self.v | {"managed": False}, None, self.c)
        stop.assert_called_once_with("swayctl-center-bar.service")


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swayctl_center import schema, theming, themes
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule, NotificationsModule
from swayctl_center.modules.theming import ThemingModule


def ctx(d, theme="gruvbox-dark"):
    v = schema.defaults()
    v["font"].update(family="Inter", size=12)
    return Context(Path(d), values=v, theme=themes.BUILTIN[theme])


class PlaceholderTest(unittest.TestCase):
    def test_render(self):
        vals = theming.placeholders(themes.BUILTIN["gruvbox-dark"], {"family": "Inter", "size": 12,
                                    "monospace_family": "JetBrains Mono", "monospace_size": 10})
        text = "bg=#@BG@f2 fg=@FG_HEX@ border=@BORDER@ match=@MATCH@ font=@FONT@ @FONT_SIZE_PX@px @VARIANT@ @THEME@ @UNKNOWN@"
        self.assertEqual(theming.render(text, vals),
                         "bg=#282828f2 fg=#ebdbb2 border=fabd2f match=928374 font=Inter 16px dark gruvbox-dark @UNKNOWN@")


class CustomConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "config.jsonc").write_text('{"modules-left": ["custom/notification"]}')
        (self.d / "style.css.template").write_text("window#waybar { background: #@BG@; font-family: @FONT@; }")

    def tearDown(self):
        self.tmp.cleanup()

    def test_bar_base_config_plus_settings_template_and_own_theme(self):
        v = schema.defaults()["bar"] | {"config_file": str(self.d / "config.jsonc"),
                                        "style_template": str(self.d / "style.css.template"),
                                        "theme": "dark", "modules_left": ["custom/notification", "clock"],
                                        "position": "bottom", "height": 0}
        c = ctx(self.d / "app", theme="gruvbox-light")
        self.assertEqual(BarModule().programs(v, c)[""][2], str(self.d / "app/generated/bar/config.json"))
        files = BarModule().files(v, c)
        cfg = json.loads(files["config.json"])
        self.assertEqual(cfg["position"], "bottom")
        self.assertNotIn("height", cfg)  # 0 = fit contents
        self.assertEqual(cfg["modules-left"], ["custom/notification", "clock"])
        self.assertEqual(files["style.css"], "window#waybar { background: #1c1712; font-family: Inter; }")

    def test_missing_template_is_reported(self):
        v = schema.defaults()["bar"] | {"style_template": str(self.d / "nope.template")}
        errors = BarModule().apply_extra("bar", v, None, ctx(self.d / "app"))
        self.assertIn("nope.template", errors[0])

    def test_notifications(self):
        (self.d / "swaync.json").write_text('{"timeout": 5, "layer": "top", "scripts": {"x": {}}, // mine\n}')
        v = schema.defaults()["notifications"] | {"config_file": str(self.d / "swaync.json"),
                                                  "style_template": str(self.d / "style.css.template"),
                                                  "timeout": 12}
        files = NotificationsModule().files(v, ctx(self.d / "app"))
        cfg = json.loads(files["config.json"])
        self.assertEqual(cfg["timeout"], 12)   # our setting wins
        self.assertIn("scripts", cfg)          # the rest of the base is kept
        self.assertIn("#282828", files["style.css"])
        self.assertEqual(NotificationsModule().related_values("notifications", "config_file",
                                                              str(self.d / "swaync.json"), None),
                         {"layer": "top", "timeout": 5})
        on = v | {"dnd_on_start": True}
        self.assertEqual(NotificationsModule().session_start("notifications", on)[0][:12], "exec sh -c '")
        self.assertEqual(NotificationsModule().session_start("notifications", on | {"managed": False}), [])


class DistroUnitTest(unittest.TestCase):
    def test_swaync_distro_unit_masked_only_while_managed(self):
        from swayctl_center import units
        with tempfile.TemporaryDirectory() as d:
            c = ctx(d)
            v = schema.defaults()["notifications"]
            with mock.patch.object(units, "mask_runtime") as mask, \
                 mock.patch.object(units, "unmask_runtime") as unmask, \
                 mock.patch.object(units, "state", return_value=units.UnitState(False, "", 0)), \
                 mock.patch.object(units, "foreign_pids", return_value=[]), \
                 mock.patch.object(units, "start", return_value=None):
                NotificationsModule().apply_extra("notifications", v, None, c)
                mask.assert_called_once_with("swaync.service")
                NotificationsModule().apply_extra("notifications", v | {"managed": False}, None, c)
                unmask.assert_called_once_with("swaync.service")


class ThemingModuleTest(unittest.TestCase):
    def test_writes_changed_outputs_and_reloads(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "k.template").write_text("background #@BG@\nforeground #@FG@\n")
            v = {"templates": [{"template": str(d / "k.template"), "output": str(d / "out/k.conf"),
                                "reload": "true"},
                               {"template": str(d / "missing"), "output": str(d / "x"), "reload": ""}]}
            with mock.patch("subprocess.Popen") as popen:
                errors = ThemingModule().apply_extra("theming", v, None, ctx(d))
                self.assertEqual((d / "out/k.conf").read_text(), "background #282828\nforeground #ebdbb2\n")
                self.assertEqual(popen.call_count, 1)
                self.assertEqual(len(errors), 1)
                ThemingModule().apply_extra("theming", v, None, ctx(d))   # unchanged: no reload
                self.assertEqual(popen.call_count, 1)
                ThemingModule().apply_extra("theming", v, None, ctx(d, "nord"))
                self.assertEqual(popen.call_count, 2)
                self.assertIn("2e3440", (d / "out/k.conf").read_text())


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from swayctl_center import schema, themes
from tests.legacy import legacy_defaults
from swayctl_center.modules import Context
from swayctl_center.modules.appearance import GTK_BEGIN, client_colors, sync_gtk_css
from swayctl_center.modules.components import BarModule, NotificationsModule, lock_command


def ctx(theme="dark", style="classic", **values):
    v = legacy_defaults()
    v["appearance"]["style"] = style
    for section, items in values.items():
        v[section].update(items)
    return Context(Path("/app"), values=v, theme=themes.BUILTIN[theme])


class BarStyleTest(unittest.TestCase):
    def test_classic_keeps_flat_bar(self):
        c = ctx("dark")
        css = BarModule().files(legacy_defaults()["bar"], c)["style.css"]
        self.assertIn("window#waybar { background: #1c1c1e; color: #f5f5f7; }", css)
        cfg = json.loads(BarModule().files(legacy_defaults()["bar"], c)["config.json"])
        self.assertEqual(cfg.get("margin-top", 0), 0)

    def test_modern_is_floating_and_rounded(self):
        c = ctx(style="modern")
        t = c.theme.tokens
        files = BarModule().files(legacy_defaults()["bar"], c)
        cfg = json.loads(files["config.json"])
        self.assertEqual((cfg["margin-top"], cfg["margin-left"], cfg["margin-right"], cfg["margin-bottom"]),
                         (8, 8, 8, 0))
        self.assertIn(f"background: alpha({t['surface']}, 0.88)", files["style.css"])
        self.assertIn("border-radius: 14px", files["style.css"])
        self.assertIn(f"#battery.warning {{ color: {t['warning']}; }}", files["style.css"])

    def test_modern_respects_user_margins(self):
        c = ctx(style="modern")
        v = legacy_defaults()["bar"] | {"position": "bottom", "margin_bottom": 3}
        cfg = json.loads(BarModule().files(v, c)["config.json"])
        self.assertEqual(cfg["margin-bottom"], 3)
        self.assertEqual(cfg["margin-top"], 0)

    def test_modern_edge_follows_position(self):
        v = legacy_defaults()["bar"] | {"position": "left"}
        cfg = json.loads(BarModule().files(v, ctx(style="modern"))["config.json"])
        self.assertEqual((cfg["margin-right"], cfg["margin-left"]), (0, 8))


class OthersTest(unittest.TestCase):
    def test_notifications_tokens(self):
        c = ctx(style="modern")
        css = NotificationsModule().css(c)
        self.assertIn("--border-radius: 14px;", css)
        self.assertIn("--noti-border-color: alpha(white, 0.42);", css)  # OSD milk rim
        self.assertIn("--text-color: #1d1d1f;", css)

    def test_lock_wrong_password_is_error_color(self):
        c = ctx()
        argv = lock_command(c)
        self.assertEqual(argv[argv.index("--ring-wrong-color") + 1], c.theme.tokens["error"].lstrip("#"))

    def test_urgent_window_is_error_color(self):
        t = themes.BUILTIN["dark"]
        self.assertIn(f"client.urgent {t.tokens['error']} ", client_colors(t)[3])


class GtkCssTest(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.target = self.d / "gtk-4.0" / "gtk.css"
        self.theme = themes.BUILTIN["dark"]

    def test_off_and_missing_writes_nothing(self):
        sync_gtk_css(False, self.theme, self.d, self.target)
        self.assertFalse(self.target.exists())

    def test_on_then_off_keeps_user_rules(self):
        self.target.parent.mkdir()
        self.target.write_text("window { font-size: 12px; }\n")
        sync_gtk_css(True, self.theme, self.d, self.target)
        text = self.target.read_text()
        self.assertTrue(text.startswith(GTK_BEGIN))
        self.assertIn(f'@import url("file://{self.d}/generated/gtk-4.0.css");', text)
        self.assertIn("window { font-size: 12px; }", text)
        self.assertIn("--accent-bg-color", (self.d / "generated" / "gtk-4.0.css").read_text())
        sync_gtk_css(True, self.theme, self.d, self.target)  # idempotent
        self.assertEqual(self.target.read_text().count(GTK_BEGIN), 1)
        sync_gtk_css(False, self.theme, self.d, self.target)
        self.assertEqual(self.target.read_text(), "window { font-size: 12px; }\n")


if __name__ == "__main__":
    unittest.main()

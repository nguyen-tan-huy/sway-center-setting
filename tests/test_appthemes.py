import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from swayctl_center import appthemes


def have(*names):
    return lambda n: f"/usr/bin/{n}" if n in names else None


class GtkTest(unittest.TestCase):
    def test_theme_family(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            with mock.patch.object(appthemes, "_themes_dirs", lambda h: [h / "themes"]):
                self.assertEqual(appthemes.gtk3_theme("dark", "Adwaita", home), "Adwaita-dark")
                self.assertEqual(appthemes.gtk3_theme("light", "", home), "Adwaita")
                (home / "themes/adw-gtk3").mkdir(parents=True)
                self.assertEqual(appthemes.gtk3_theme("dark", "Adwaita", home), "adw-gtk3-dark")
                self.assertEqual(appthemes.gtk3_theme("light", "adw-gtk3-dark", home), "adw-gtk3")
                self.assertIsNone(appthemes.gtk3_theme("dark", "Breeze", home))  # the user's own: left alone

    def test_settings_ini_keeps_other_keys(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            ini = home / ".config/gtk-3.0/settings.ini"
            ini.parent.mkdir(parents=True)
            ini.write_text("[Settings]\ngtk-font-name=Inter 11\ngtk-application-prefer-dark-theme=false\n")
            appthemes.gtk3_settings_ini("dark", home)
            text = ini.read_text()
            self.assertIn("gtk-font-name=Inter 11", text)
            self.assertIn("gtk-application-prefer-dark-theme=true", text)
            self.assertEqual(text.count("prefer-dark"), 1)


class TerminalTest(unittest.TestCase):
    def sync(self, home, variant, *installed):
        with mock.patch("shutil.which", have(*installed)), mock.patch("subprocess.run") as run:
            errors = appthemes.sync_terminals(variant, home)
        return errors, run

    def test_foot_switches_live_and_keeps_user_config(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            ini = home / ".config/foot/foot.ini"
            ini.parent.mkdir(parents=True)
            ini.write_text("font=JetBrains Mono:size=11\n")
            errors, run = self.sync(home, "light", "foot")
            self.assertEqual(errors, [])
            text = ini.read_text()
            self.assertTrue(text.startswith("include="))           # ours first: the user's colors still win
            self.assertIn("font=JetBrains Mono:size=11", text)
            colors = (home / ".config/foot/swayctl-colors.ini").read_text()
            self.assertIn("initial-color-theme=light", colors)
            self.assertIn("[colors-dark]", colors)
            self.assertIn("[colors-light]", colors)
            run.assert_called_once_with(["pkill", "-USR2", "-x", "foot"], capture_output=True)
            self.sync(home, "dark", "foot")
            self.assertEqual(ini.read_text().count("include="), 1)  # added once

    def test_kitty_auto_themes(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            self.sync(home, "dark", "kitty")
            self.assertIn("background #f5f5f7", (home / ".config/kitty/light-theme.auto.conf").read_text())
            self.assertIn("background #1c1c1e", (home / ".config/kitty/dark-theme.auto.conf").read_text())
            self.assertFalse((home / ".config/kitty/kitty.conf").exists())  # never touched

    def test_alacritty(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            errors, _ = self.sync(home, "light", "alacritty")
            self.assertEqual(errors, [])
            cfg = tomllib.loads((home / ".config/alacritty/alacritty.toml").read_text())
            self.assertTrue(cfg["general"]["import"][0].endswith("swayctl-colors.toml"))
            colors = tomllib.loads((home / ".config/alacritty/swayctl-colors.toml").read_text())
            self.assertEqual(colors["colors"]["primary"]["foreground"], "#1d1d1f")
            # an alacritty.toml of the user's own without our import: told, not edited
            (home / ".config/alacritty/alacritty.toml").write_text("[font]\nsize = 12\n")
            errors, _ = self.sync(home, "dark", "alacritty")
            self.assertIn("swayctl-colors.toml", errors[0])
            self.assertEqual((home / ".config/alacritty/alacritty.toml").read_text(), "[font]\nsize = 12\n")

    def test_nothing_for_missing_terminals(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            self.sync(home, "dark")
            self.assertFalse((home / ".config").exists())


class QtTest(unittest.TestCase):
    def test_sets_portal_theme_unless_user_chose(self):
        with mock.patch.dict("os.environ", {}, clear=False), mock.patch("subprocess.run") as run:
            import os
            os.environ.pop("QT_QPA_PLATFORMTHEME", None)
            run.return_value.returncode = 0
            self.assertEqual(appthemes.qt_environment(), [])
            self.assertIn("QT_QPA_PLATFORMTHEME=xdgdesktopportal", run.call_args_list[0].args[0])
        with mock.patch.dict("os.environ", {"QT_QPA_PLATFORMTHEME": "qt6ct"}), mock.patch("subprocess.run") as run:
            self.assertEqual(appthemes.qt_environment(), [])
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

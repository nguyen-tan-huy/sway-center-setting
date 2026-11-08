import unittest

from swayctl_center.modules.components import adaptive_css, shell_milk


class GlassUnifiedTest(unittest.TestCase):
    """app Cài đặt, bar và Quick Settings dùng chung một look kính
    (shell_milk cho độ đục sữa, adaptive_css cho chữ theo nền)."""

    def test_shell_milk_is_one_formula(self):
        # compositor's glass on: demo precision lens (x0.20, floor 4%)
        self.assertEqual(shell_milk(50, True), 0.10)
        self.assertEqual(shell_milk(10, True), 0.04)   # 0.02 -> floor
        self.assertAlmostEqual(shell_milk(90, True), 0.18)
        # glass off: exactly the user's thickness
        self.assertEqual(shell_milk(50, False), 0.50)
        self.assertEqual(shell_milk(0, False), 0.04)

    def test_the_settings_window_is_never_glass(self):
        # liquid glass is for the popups (Quick Settings, the volume pill, the launcher, notifications):
        # not an app window, whatever the setting and whatever the compositor can do
        from swayctl_center.ui import SettingsWindow

        class Client:
            def get_all(self):
                return {"effects": {"glass": True, "glass_opacity": 10},
                        "background": {"image": "x.png", "mode": "fill"}}

        for features in (["glass-windows", "glass-ink"], ["glass-windows"], []):
            w = SettingsWindow.__new__(SettingsWindow)
            w.client = Client()
            css = w._glass_css({"tokens": {"accent": "#3584e4", "accent_fg": "#ffffff"}, "bg": "#101014"},
                               {"compositor": {"features": features}})
            self.assertEqual(css, "")
            self.assertFalse(w._ink)
            self.assertIsNone(w._backdrop)

import unittest

from swayctl_center.modules.components import adaptive_css, app_glass_css, shell_milk


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

    def test_app_glass_css_adaptive_is_on(self):
        from swayctl_center.ui import SettingsWindow
        w = SettingsWindow.__new__(SettingsWindow)

        class Client:
            def get_all(self):
                return {"effects": {"glass": True, "glass_opacity": 10},
                        "background": {"image": "", "mode": "fill", "color": "#101014"}}

        w.client = Client()
        theme = {"tokens": {"accent": "#3584e4", "accent_fg": "#ffffff"}, "bg": "#101014"}
        css = w._glass_css(theme, {"compositor": {"features": ["glass-windows"]}})
        # chữ đổi theo nền + độ dày envelope như bar/Quick Settings
        self.assertIn(".on-dark", css)
        self.assertIn(".on-light", css)
        self.assertIn("tint-", css)
        # độ đục sữa = shell_milk (x0.20 khi kính bật), không còn x0.55 riêng
        want = app_glass_css(theme["tokens"], shell_milk(10, True))
        self.assertIn(want, css)

    def test_app_glass_css_off_without_compositor_glass(self):
        from swayctl_center.ui import SettingsWindow
        w = SettingsWindow.__new__(SettingsWindow)

        class Client:
            def get_all(self):
                return {"effects": {"glass": False, "glass_opacity": 10}}

        w.client = Client()
        self.assertEqual(
            w._glass_css({"tokens": {}, "bg": "#000000"},
                         {"compositor": {"features": ["glass-windows"]}}), "")
        self.assertIsNone(w._backdrop)
        # thiếu feature glass-windows: không có kính, tắt cả retag
        self.assertEqual(
            w._glass_css({"tokens": {}, "bg": "#000000"},
                         {"compositor": {"features": []}}), "")
        self.assertIsNone(w._backdrop)

    def test_adaptive_css_covers_shell_selectors(self):
        css = adaptive_css(10, "#3584e4", "#ffffff")
        self.assertIn(".on-dark label", css)
        self.assertIn(".on-dark button", css)
        self.assertIn(".on-light label", css)


    def test_lens_ink_follows_liquid_demo(self):
        css = adaptive_css(10, "#3584e4", "#ffffff", lens=True)
        # pure white / near-black ink, halo steps, smooth switch
        self.assertIn("color: #ffffff", css)
        self.assertIn("color: #111114", css)
        for step in range(5):
            self.assertIn(f".on-dark.halo-{step} label", css)
        self.assertIn("transition: color", css)
        # clear capsules: no smoke/milk thickening while the lens is on
        self.assertNotIn("tint-", css)
        self.assertNotIn("linear-gradient", css)


if __name__ == "__main__":
    unittest.main()

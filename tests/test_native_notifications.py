import unittest
from pathlib import Path

from swayctl_center import schema, themes
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule, NotificationsModule
from swayctl_center.modules.effects import PANEL_NAMESPACES, SHAPED


def ctx(**notif):
    v = schema.defaults()
    v["notifications"] |= notif
    return Context(Path("/app"), values=v, theme=themes.BUILTIN["dark"])


class NativeNotificationsTest(unittest.TestCase):
    def test_swayctl_bar_is_the_default_server(self):
        c = ctx()
        v = c.values["notifications"]
        self.assertEqual(NotificationsModule().programs(v, c), {})  # no swaync unit
        self.assertEqual(NotificationsModule().files(v, c), {})
        self.assertEqual(NotificationsModule().session_start("notifications", v | {"dnd_on_start": True}), [])

    def test_bar_config_carries_settings(self):
        c = ctx(position_x="left", position_y="bottom", timeout=5, max_visible=2, dnd_on_start=True)
        n = BarModule().native_config(c.values["bar"] | {"program": "swayctl-bar"}, c)["notifications"]
        self.assertTrue(n["enabled"])
        self.assertEqual((n["position_x"], n["position_y"], n["timeout"], n["max_visible"], n["dnd_on_start"]),
                         ("left", "bottom", 5, 2, True))

    def test_off_when_unmanaged_or_swaync(self):
        for kw in ({"managed": False}, {"program": "swaync"}):
            c = ctx(**kw)
            self.assertFalse(BarModule().notifications_config(c)["enabled"])
        c = ctx(program="swaync")
        self.assertEqual(NotificationsModule().programs(c.values["notifications"], c)[""][0], "swaync")

    def test_bar_follows_notification_settings(self):
        self.assertIn("notifications", BarModule.depends_on)

    def test_glass_shapes_the_cards(self):
        self.assertIn("swayctl-notifications", PANEL_NAMESPACES)
        self.assertIn("swayctl-notifications", SHAPED)
        css = BarModule().native_css(ctx(), themes.BUILTIN["dark"])
        self.assertIn(".notification-card", css)

    def test_launcher_glass(self):
        from swayctl_center.modules.launcher import LauncherModule
        self.assertIn("walker", SHAPED)
        plain = LauncherModule().theme_css(ctx())
        c = ctx()
        c.values["effects"]["glass"] = True
        glass = LauncherModule().theme_css(c)
        self.assertNotIn("liquid glass", plain)
        self.assertIn("liquid glass", glass)
        self.assertIn("alpha(white", glass)   # OSD milk, not smoked surface
        self.assertIn("#1d1d1f", glass)

    def test_two_themes_and_old_names(self):
        from datetime import datetime
        from swayctl_center import themes as th
        from swayctl_center.modules import appearance
        self.assertEqual(set(th.BUILTIN), {"light", "dark"})
        self.assertEqual(th.BUILTIN["light"].fg, "#1d1d1f")       # black text
        self.assertTrue(th.BUILTIN["dark"].dark)
        v = schema.defaults()
        v["appearance"] |= {"mode": "dark", "dark_theme": "gruvbox-dark"}   # saved by an older version
        r = appearance.resolve(v, th.load_all(None), datetime(2026, 1, 1, 12), None)
        self.assertEqual((r.theme.name, r.missing), ("dark", None))

    def test_glass_follows_the_theme(self):
        from swayctl_center.modules.components import _glass_opacity, _text_shadow
        c = ctx()
        self.assertEqual(_glass_opacity(c, themes.BUILTIN["light"]), 0.1)   # demo lens default (10%)
        c.values["effects"]["glass_opacity"] = 0
        self.assertEqual(_glass_opacity(c, themes.BUILTIN["light"]), 0.02)  # clear, still drawn (8-bit safe)
        self.assertAlmostEqual(_glass_opacity(c, themes.BUILTIN["dark"]), 0.45)  # dark: smoked, never clear
        c.values["effects"]["glass_opacity"] = 100
        self.assertAlmostEqual(_glass_opacity(c, themes.BUILTIN["dark"]), 1.0)
        self.assertIn("white", _text_shadow(themes.BUILTIN["light"].tokens))        # black text, light glow
        self.assertIn("black", _text_shadow(themes.BUILTIN["dark"].tokens))

    def test_no_calendar(self):
        # the clock has no calendar popup: no glass or styles left for it
        self.assertNotIn("swayctl-calendar", SHAPED)
        c = ctx()
        c.values["effects"]["glass"] = True
        self.assertNotIn("calendar-panel", BarModule().native_css(c, themes.BUILTIN["dark"]))

    def test_settings_app_glass_css(self):
        from swayctl_center.modules.components import app_glass_css, milk_fill
        css = app_glass_css(themes.BUILTIN["dark"].tokens, 0.50)
        self.assertIn("background-color: transparent", css)  # the window itself is clear
        self.assertIn(".sidebar-pane", css)
        # direct call (no ctx): milk at 0.50 — not the glass-on thinned path
        self.assertIn("alpha(white, 0.420), alpha(white, 0.260)", css)  # milk, not smoked surface
        self.assertIn("label.title-2", css)                  # headings sit on glass
        self.assertIn("#1d1d1f", css)                        # dark content on milk
        self.assertIn("1px solid alpha(white, 0.48)", css)
        self.assertEqual(milk_fill(0.50).count("alpha(white"), 2)

    def test_bar_backdrop(self):
        c = ctx()
        c.values["background"] |= {"image": "wallpapers/a.png", "mode": "fit", "color": "#102030"}
        b = BarModule().native_config(c.values["bar"] | {"program": "swayctl-bar"}, c)["backdrop"]
        c.values["effects"]["glass"] = True
        b = BarModule().native_config(c.values["bar"] | {"program": "swayctl-bar"}, c)["backdrop"]
        self.assertTrue(b["adaptive"])  # each pane flips its text over what's behind it
        self.assertNotIn(".on-light", BarModule().native_css(c, themes.BUILTIN["dark"]))
        # the adaptive rules ship with style.css (classes would select nothing)
        style = BarModule().files(c.values["bar"] | {"program": "swayctl-bar"}, c)["style.css"]
        self.assertIn(".on-dark.on-dark.on-dark", style)
        self.assertIn(".on-light.on-light.on-light", style)
        self.assertIn("background", BarModule.depends_on)  # new wallpaper: retag

    def test_old_settings_not_shown(self):
        shown = {f"{k.section}.{k.name}" for k in schema.KEYS if not k.hidden}
        for gone in ("appearance.light_theme", "appearance.dark_theme", "bar.theme", "bar.margin_top", "bar.layer", "effects.blur", "effects.shadows", "effects.panels",
                     "notifications.control_center_width", "notifications.grouping"):
            self.assertNotIn(gone, shown)
        for kept in ("bar.position", "effects.glass", "notifications.timeout", "notifications.max_visible"):
            self.assertIn(kept, shown)


if __name__ == "__main__":
    unittest.main()

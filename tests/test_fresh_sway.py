"""A fresh install: sway's stock config, nothing of the user's own."""
import unittest
from pathlib import Path
from unittest import mock

from swayctl_center import schema, swayconfig
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule, PolkitAgentModule
from swayctl_center.modules.keybindings import CLIPBOARD, LAUNCHER, KeybindingsModule

STOCK = "\n".join([
    "set $mod Mod4", "set $term foot", "set $menu wmenu-run",
    "bindsym $mod+Return exec $term", "bindsym $mod+d exec $menu", "bindsym $mod+v splitv",
    "bar {", "    position top", "}",
])


def import_bindings(text: str, main: Path) -> dict[str, dict]:
    with mock.patch.object(swayconfig, "main_config_path", return_value=main):
        got = KeybindingsModule().import_current(None, swayconfig.parse(text, Path("/x")), None)
    return {b["keys"]: b for b in got["keybindings"]["bindings"]}


class StockKeybindingsTest(unittest.TestCase):
    def test_stock_menu_becomes_our_launcher(self):
        b = import_bindings(STOCK, swayconfig.SYSTEM_CONFIG)
        self.assertEqual(b["$mod+d"]["command"], LAUNCHER)
        self.assertEqual(b["$mod+Return"]["command"], "exec foot")

    def test_older_stock_menus_too(self):
        for menu in ("dmenu_path | dmenu | xargs swaymsg exec --", "dmenu_path | wmenu | xargs swaymsg exec --"):
            text = STOCK.replace("set $menu wmenu-run", f"set $menu {menu}")
            self.assertEqual(import_bindings(text, Path("/home/u/.config/sway/config"))["$mod+d"]["command"],
                             LAUNCHER)

    def test_own_menu_is_kept(self):
        text = STOCK.replace("set $menu wmenu-run", "set $menu rofi -show drun")
        self.assertEqual(import_bindings(text, swayconfig.SYSTEM_CONFIG)["$mod+d"]["command"],
                         "exec rofi -show drun")

    def test_clipboard_shortcut_only_on_the_stock_config(self):
        self.assertEqual(import_bindings(STOCK, swayconfig.SYSTEM_CONFIG)["$mod+Shift+v"]["command"], CLIPBOARD)
        self.assertNotIn("$mod+Shift+v", import_bindings(STOCK, Path("/home/u/.config/sway/config")))

    def test_clipboard_shortcut_never_takes_a_used_key(self):
        text = STOCK + "\nbindsym $mod+Shift+v exec pavucontrol"
        self.assertEqual(import_bindings(text, swayconfig.SYSTEM_CONFIG)["$mod+Shift+v"]["command"],
                         "exec pavucontrol")


class SwayBarTest(unittest.TestCase):
    def ctx(self, live):
        return Context(Path("/app"), live=live, values=schema.defaults())

    def test_hidden_while_managed_and_restored_after(self):
        m, v = BarModule(), schema.defaults()["bar"]
        self.assertEqual(m.commands("bar", v, None, self.ctx({"bar-0": "dock"})), ["bar bar-0 mode invisible"])
        self.assertEqual(m.commands("bar", v, None, self.ctx({"bar-0": "invisible"})), [])
        self.assertEqual(m.commands("bar", v | {"managed": False}, {"managed"}, self.ctx({"bar-0": "invisible"})),
                         ["bar bar-0 mode dock"])
        self.assertEqual(m.commands("bar", v | {"managed": False}, None, self.ctx({"bar-0": "invisible"})), [])

    def test_bars_hidden_by_the_user_stay_hidden(self):
        m, v = BarModule(), schema.defaults()["bar"] | {"managed": False}
        self.assertEqual(m.commands("bar", v, None, self.ctx({"bar-0": "invisible"})), [])

    def test_no_sway_bars(self):
        self.assertEqual(BarModule().commands("bar", schema.defaults()["bar"], None, self.ctx(None)), [])


class PolkitAgentTest(unittest.TestCase):
    def test_left_alone_when_the_user_runs_one(self):
        with mock.patch("swayctl_center.units.foreign_pids", return_value=[42]):
            self.assertEqual(PolkitAgentModule().import_current(None, None, None),
                             {"polkit_agent": {"managed": False}})


class FontWeightTest(unittest.TestCase):
    def test_bold_everywhere(self):
        from swayctl_center import theming, themes
        from swayctl_center.modules.font import FontModule
        v = schema.defaults()["font"] | {"family": "Inter", "weight": "bold", "size": 11}
        self.assertEqual(FontModule().commands("font", v, None), ["font pango:Inter Bold 11"])
        self.assertEqual(FontModule().gsettings_values(v)["font-name"], "Inter Bold 11")
        self.assertEqual(theming.placeholders(themes.BUILTIN["gruvbox-dark"], v)["@FONT_WEIGHT@"], "700")
        values = schema.defaults()
        values["font"] = v
        css = BarModule().files(values["bar"], Context(Path("/app"), values=values,
                                                        theme=themes.BUILTIN["gruvbox-dark"]))["style.css"]
        self.assertIn("font-weight: 700", css)

    def test_import_splits_the_weight_off(self):
        from swayctl_center.modules.font import split_weight
        self.assertEqual(split_weight("Inter SemiBold"), ("Inter", "semibold"))
        self.assertEqual(split_weight("Noto Sans"), ("Noto Sans", "regular"))


if __name__ == "__main__":
    unittest.main()

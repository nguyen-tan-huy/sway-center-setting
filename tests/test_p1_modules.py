import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swayctl_center import schema, swayconfig
from swayctl_center.modules import Context
from swayctl_center.modules.autostart import AutostartModule
from swayctl_center.modules.background import BackgroundModule
from swayctl_center.modules.font import FontModule
from swayctl_center.modules.keybindings import KeybindingsModule
from swayctl_center.modules.outputs import OutputsModule, from_live, identifier

LIVE = {
    "name": "eDP-1", "make": "Lenovo Group Limited", "model": "0x8AB1", "serial": "Unknown",
    "active": True, "scale": 2.0, "transform": "normal", "adaptive_sync_status": "disabled",
    "current_mode": {"width": 3072, "height": 1920, "refresh": 120002},
    "rect": {"x": 0, "y": 0, "width": 1536, "height": 960},
}
ID = "Lenovo Group Limited 0x8AB1 Unknown"


class OutputsTest(unittest.TestCase):
    def cmds(self, config, live=(LIVE,)):
        return OutputsModule().commands("outputs", {"config": config}, None,
                                        Context(Path("/x"), live=list(live)))

    def test_identity_and_import(self):
        self.assertEqual(identifier(LIVE), ID)
        self.assertEqual(identifier({"name": "HDMI-A-1", "make": "Unknown", "model": "Unknown", "serial": "Unknown"}),
                         "HDMI-A-1")
        cfg = from_live(LIVE)
        self.assertEqual(cfg["mode"], "3072x1920@120.002Hz")
        self.assertEqual(schema.lookup("outputs", "config").validate({ID: cfg})[ID]["scale"], 2.0)

    def test_no_command_when_live_matches(self):
        cfg = schema.lookup("outputs", "config").validate({ID: from_live(LIVE)})
        self.assertEqual(self.cmds(cfg), [])
        # a rate written by hand, rounded, still matches
        cfg[ID]["mode"] = "3072x1920@120Hz"
        self.assertEqual(self.cmds(cfg), [])

    def test_command_when_different_or_unknown(self):
        cfg = schema.lookup("outputs", "config").validate({ID: from_live(LIVE) | {"scale": 1.5}})
        self.assertEqual(self.cmds(cfg), [
            f'output "{ID}" enable mode 3072x1920@120.002Hz position 0 0 scale 1.5 '
            "transform normal adaptive_sync off"])
        other = schema.lookup("outputs", "config").validate({"Dell U2720Q ABC": {"enabled": False}})
        # live state unknown: send it so sway keeps it for when the monitor shows up
        self.assertEqual(self.cmds(other, live=()), ['output "Dell U2720Q ABC" disable'])
        # known to be unplugged: nothing (a command would make sway emit output events,
        # which the daemon answers by re-applying - an endless loop)
        self.assertEqual(self.cmds(other), [])

    def test_new_outputs(self):
        self.assertEqual(list(OutputsModule().new_outputs({}, [LIVE])), [ID])
        self.assertEqual(OutputsModule().new_outputs({ID: {}}, [LIVE]), {})


class BackgroundTest(unittest.TestCase):
    def test_copy_into_app_folder_and_command(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            img = d / "src" / 'my "pic".jpg'
            img.parent.mkdir()
            img.write_bytes(b"jpeg")
            ctx = Context(d / "app")
            stored = BackgroundModule().before_set("background", "image", str(img), ctx)
            self.assertTrue(stored.startswith("wallpapers/"))
            self.assertTrue((d / "app" / stored).is_file())
            # setting the stored value again is accepted as-is
            self.assertEqual(BackgroundModule().before_set("background", "image", stored, ctx), stored)
            cmd = BackgroundModule().commands("background", {"image": stored, "mode": "fill", "color": "#112233"},
                                              None, ctx)[0]
            self.assertIn('\\"pic\\".jpg" fill #112233', cmd)
            with self.assertRaises(ValueError):
                BackgroundModule().before_set("background", "image", str(d / "missing.png"), ctx)

    def test_solid_color_and_import(self):
        v = {"image": "", "mode": "fill", "color": "#f5f5f7"}
        self.assertEqual(BackgroundModule().commands("background", v, None, Context(Path("/x"))),
                         ["output * bg #f5f5f7 solid_color"])
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "w.jpg").write_bytes(b"x")
            cfg = swayconfig.parse(f'set $bg #f5f5f7\noutput * bg "{d}/w.jpg" fill $bg', d)
            got = BackgroundModule().import_current(None, cfg, Context(d / "app"))["background"]
        self.assertEqual(got["mode"], "fill")
        self.assertNotIn("color", got)  # came from a variable: keeps following the theme
        self.assertTrue(got["image"].endswith("-w.jpg"))
        cfg = swayconfig.parse("output * bg #123456 solid_color", Path("/x"))
        got = BackgroundModule().import_current(None, cfg, Context(Path("/x")))["background"]
        self.assertEqual(got, {"image": "", "color": "#123456"})

    def test_follows_theme_color(self):
        from swayctl_center import themes
        v = {"image": "", "mode": "fill", "color": ""}
        ctx = Context(Path("/x"), theme=themes.BUILTIN["dark"])
        self.assertEqual(BackgroundModule().commands("background", v, None, ctx),
                         ["output * bg #1c1c1e solid_color"])


class FontTest(unittest.TestCase):
    def test_commands(self):
        v = {"family": "Inter SemiBold", "size": 12, "monospace_family": "JetBrains Mono", "monospace_size": 10}
        self.assertEqual(FontModule().commands("font", v, None), ["font pango:Inter SemiBold 12"])
        self.assertEqual(FontModule().gsettings_values(v),
                         {"font-name": "Inter SemiBold 12", "monospace-font-name": "JetBrains Mono 10"})


class KeybindingsTest(unittest.TestCase):
    def test_import_uses_mod_and_skips_modes(self):
        text = "\n".join([
            "set $mod Mod4", "set $term kitty",
            "bindsym $mod+Return exec $term",
            "bindsym --to-code $mod+Shift+q kill",
            "bindsym --locked XF86AudioMute exec pactl set-sink-mute @DEFAULT_SINK@ toggle",
            "bindsym $mod+Return exec foot",  # later wins, like sway
            "bindsym --release {", "    Print exec grim", "}",
            'mode "resize" {', "    bindsym Left resize shrink width 10px", "}",
        ])
        with mock.patch.object(swayconfig, "main_config_path", return_value=Path("/home/u/.config/sway/config")):
            got = KeybindingsModule().import_current(None, swayconfig.parse(text, Path("/x")), None)["keybindings"]
        self.assertEqual(got["modifier"], "Mod4")
        b = {x["keys"]: x for x in got["bindings"]}
        self.assertEqual(b["$mod+Return"]["command"], "exec foot")
        self.assertEqual(b["$mod+Shift+q"]["flags"], ["--to-code"])
        self.assertEqual(b["Print"]["flags"], ["--release"])
        self.assertNotIn("Left", b)
        self.assertEqual(len(got["bindings"]), 4)

    def test_diff_commands(self):
        old = {"modifier": "Mod4", "bindings": [
            {"keys": "$mod+Return", "command": "exec kitty", "flags": []},
            {"keys": "$mod+d", "command": "exec fuzzel", "flags": []}]}
        new = {"modifier": "Mod4", "bindings": [
            {"keys": "$mod+Return", "command": "exec foot", "flags": []},
            {"keys": "$mod+e", "command": "exec nautilus", "flags": []}]}
        cmds = KeybindingsModule().commands("keybindings", new, {"bindings"}, Context(Path("/x"), old=old))
        self.assertEqual(cmds, ["floating_modifier Mod4 normal",
                                "unbindsym Mod4+d",
                                "bindsym --no-warn Mod4+Return exec foot",
                                "bindsym --no-warn Mod4+e exec nautilus"])

    def test_modifier_change_rebinds(self):
        b = [{"keys": "$mod+Return", "command": "exec foot", "flags": []}]
        cmds = KeybindingsModule().commands("keybindings", {"modifier": "Mod1", "bindings": b}, {"modifier"},
                                            Context(Path("/x"), old={"modifier": "Mod4", "bindings": b}))
        self.assertEqual(cmds, ["floating_modifier Mod1 normal", "unbindsym Mod4+Return",
                                "bindsym --no-warn Mod1+Return exec foot"])


class AutostartTest(unittest.TestCase):
    def test_session_start(self):
        v = schema.lookup("autostart", "commands").validate([
            {"command": "fcitx5 -d"}, {"command": "warpd", "enabled": False}])
        m = AutostartModule()
        self.assertEqual(m.commands("autostart", {"commands": v}, None), [])
        self.assertEqual(m.session_start("autostart", {"commands": v}), ["exec fcitx5 -d"])


if __name__ == "__main__":
    unittest.main()

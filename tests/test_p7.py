import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swayctl_center import owned, schema, themes
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule
from swayctl_center.modules.theming import ThemingModule


class AdoptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.patch = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        self.patch.start()
        self.user = self.home / ".config/waybar"
        (self.user / "scripts").mkdir(parents=True)
        (self.user / "scripts/notify.sh").write_text("#!/bin/sh\necho hi\n")
        (self.user / "scripts/notify.sh").chmod(0o755)
        (self.user / "config.jsonc").write_text(
            '{"custom/n": {"exec": "~/.config/waybar/scripts/notify.sh"},\n'
            ' "custom/m": {"exec": "$HOME/.config/waybar/missing.py"},\n'
            ' "modules-left": ["custom/n"]}')
        self.data = self.home / ".config/swayctl-center"

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_copies_config_and_the_scripts_it_uses(self):
        new = owned.adopt("~/.config/waybar/config.jsonc", self.data, "bar", "base.jsonc", with_references=True)
        copy = Path(new)
        self.assertEqual(copy, self.data / "bar/base.jsonc")
        text = copy.read_text()
        script = self.data / "bar/files/scripts/notify.sh"
        self.assertIn(str(script), text)
        self.assertTrue(os.access(script, os.X_OK))            # still executable
        self.assertIn("$HOME/.config/waybar/missing.py", text)  # missing files left as they were
        # already ours: unchanged
        self.assertEqual(owned.adopt(new, self.data, "bar", "base.jsonc"), new)
        with self.assertRaises(ValueError):
            owned.adopt("~/nope.jsonc", self.data, "bar", "base.jsonc")

    def test_bar_before_set_owns_the_file(self):
        c = Context(self.data, values=schema.defaults(), theme=themes.BUILTIN["dark"])
        value = BarModule().before_set("bar", "config_file", "~/.config/waybar/config.jsonc", c)
        self.assertTrue(value.startswith(str(self.data)))
        related = BarModule().related_values("bar", "config_file", value, c)
        self.assertEqual(related["modules_left"], ["custom/n"])

    def test_templates_are_owned_and_can_be_switched_off(self):
        (self.home / "k.template").write_text("bg #@BG@\n")
        (self.home / "other").mkdir()
        (self.home / "other/k.template").write_text("fg #@FG@\n")
        c = Context(self.data, values=schema.defaults(), theme=themes.BUILTIN["dark"])
        items = ThemingModule().before_set("theming", "templates", [
            {"template": str(self.home / "k.template"), "output": str(self.home / "out/a.conf"), "reload": ""},
            {"template": str(self.home / "other/k.template"), "output": str(self.home / "out2/b.conf"),
             "reload": ""},
        ], c)
        self.assertEqual(items[0]["template"], str(self.data / "templates/k.template"))
        self.assertEqual(items[1]["template"], str(self.data / "templates/out2-k.template"))
        items = schema.lookup("theming", "templates").validate(items)
        items[1]["enabled"] = False
        ThemingModule().apply_extra("theming", {"templates": items}, None, c)
        self.assertTrue((self.home / "out/a.conf").exists())
        self.assertFalse((self.home / "out2/b.conf").exists())


class HiddenKeysTest(unittest.TestCase):
    def test_file_settings_are_hidden(self):
        for path in ("bar.config_file", "bar.style_template", "notifications.config_file",
                     "notifications.style_template"):
            self.assertTrue(schema.BY_PATH[path].to_json().get("hidden"), path)


if __name__ == "__main__":
    unittest.main()


class MissingHelperTest(unittest.TestCase):
    def test_missing_optional_program_doesnt_stop_the_rest(self):
        from swayctl_center import units
        from swayctl_center.modules.components import ClipboardModule
        with tempfile.TemporaryDirectory() as d:
            c = Context(Path(d), values=schema.defaults(), theme=themes.BUILTIN["dark"])
            v = schema.defaults()["clipboard"] | {"persist": True}
            with mock.patch.object(units, "installed", side_effect=lambda p: p != "wl-clip-persist"), \
                 mock.patch.object(units, "state", return_value=units.UnitState(False, "", 0)), \
                 mock.patch.object(units, "foreign_pids", return_value=[]), \
                 mock.patch.object(units, "start", return_value=None) as start:
                errors = ClipboardModule().apply_extra("clipboard", v, None, c)
                self.assertEqual(errors, ["wl-clip-persist is not installed"])
                started = [call.args[0] for call in start.call_args_list]
                self.assertEqual(started, ["swayctl-center-clipboard-text.service",
                                           "swayctl-center-clipboard-image.service"])
            with mock.patch.object(units, "installed", side_effect=lambda p: p != "wl-clip-persist"), \
                 mock.patch.object(units, "state", return_value=units.UnitState(True, "x", 1)), \
                 mock.patch.object(units, "foreign_pids", return_value=[]):
                s = ClipboardModule().status(v, c)
            self.assertTrue(s["running"])                  # cliphist runs; only the helper is missing
            self.assertEqual(s["missing"], ["wl-clip-persist"])


class QuotedBindingTest(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"SWAYCTL_CENTER_BIN": "/opt/scc/bin/swayctl-center"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_own_commands_use_an_absolute_path(self):
        from swayctl_center.modules.keybindings import bind
        self.assertEqual(bind({"keys": "$mod+Shift+t", "flags": [], "command": "exec swayctl-center action theme.toggle"},
                              "Mod4"),
                         "bindsym --no-warn Mod4+Shift+t exec /opt/scc/bin/swayctl-center action theme.toggle")
        self.assertEqual(bind({"keys": "x", "flags": [], "command": "exec swayctl-centerx"}, "Mod4"),
                         "bindsym --no-warn x exec swayctl-centerx")

    def test_quoted_exec_goes_through_the_runner(self):
        from swayctl_center.modules.keybindings import bind, binding_id, needs_runner, shell_command
        b = {"keys": "$mod+Shift+v", "flags": [],
             "command": "exec sh -c 'cliphist list | fuzzel --dmenu --prompt \"x \" | cliphist decode | wl-copy'"}
        cmd = bind(b, "Mod4")
        self.assertEqual(cmd, f"bindsym --no-warn Mod4+Shift+v exec /opt/scc/bin/swayctl-center binding {binding_id(b)}")
        self.assertNotIn("'", cmd)
        self.assertEqual(shell_command(b["command"]),
                         "sh -c 'cliphist list | fuzzel --dmenu --prompt \"x \" | cliphist decode | wl-copy'")
        # plain commands are still bound directly
        self.assertEqual(bind({"keys": "$mod+Return", "flags": [], "command": "exec kitty"}, "Mod4"),
                         "bindsym --no-warn Mod4+Return exec kitty")
        self.assertFalse(needs_runner('mode "resize"'))
        self.assertNotEqual(binding_id(b), binding_id(b | {"flags": ["--release"]}))


class ClipboardPickerTest(unittest.TestCase):
    def test_pipelines_ignore_an_empty_choice_with_either_menu(self):
        from swayctl_center import clipboard
        for running, menu in ((False, "fuzzel --dmenu"), (True, "walker --dmenu")):
            with mock.patch.object(clipboard, "walker_running", return_value=running), \
                    mock.patch.object(clipboard, "bar_running", return_value=False):
                for what in ("history", "delete"):
                    cmd = clipboard.pipeline(what)
                    self.assertIn(menu, cmd)
                    self.assertIn('[ -n "$sel" ]', cmd)
                    self.assertNotIn("'", cmd)  # safe as one sh -c argument
                self.assertEqual(clipboard.pipeline("launcher"), "walker" if running else "fuzzel")
        # no Walker, swayctl-bar running: its Spotlight opens (":" = clipboard)
        with mock.patch.object(clipboard, "walker_running", return_value=False), \
                mock.patch.object(clipboard, "bar_running", return_value=True):
            self.assertEqual(clipboard.pipeline("launcher"), "swayctl-bar launcher")
            self.assertEqual(clipboard.pipeline("history"), "swayctl-bar launcher :")
            self.assertEqual(clipboard.pipeline("delete"), "swayctl-bar launcher :")
            self.assertEqual(clipboard.pipeline("clear"), "cliphist wipe")


class StaleSessionUnitTest(unittest.TestCase):
    """A unit still running from the last login is restarted, not reused."""

    def test_other_session_is_detected_from_the_main_process_env(self):
        from swayctl_center import units
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / "environ"
            env.write_bytes(b"PATH=/usr/bin\0SWAYSOCK=/run/user/1000/sway-ipc.1000.111.sock\0")
            real_path = Path
            with mock.patch.dict(os.environ, {"SWAYSOCK": "/run/user/1000/sway-ipc.1000.222.sock"}), \
                    mock.patch.object(units, "_systemctl", return_value=mock.Mock(stdout="4242\n")), \
                    mock.patch.object(units, "Path", side_effect=lambda p: env if "environ" in str(p) else real_path(p)):
                self.assertTrue(units.from_other_session("x.service"))
            with mock.patch.dict(os.environ, {"SWAYSOCK": "/run/user/1000/sway-ipc.1000.111.sock"}), \
                    mock.patch.object(units, "_systemctl", return_value=mock.Mock(stdout="4242\n")), \
                    mock.patch.object(units, "Path", side_effect=lambda p: env if "environ" in str(p) else real_path(p)):
                self.assertFalse(units.from_other_session("x.service"))
            # not running: nothing to say
            with mock.patch.dict(os.environ, {"SWAYSOCK": "/x"}), \
                    mock.patch.object(units, "_systemctl", return_value=mock.Mock(stdout="0\n")):
                self.assertFalse(units.from_other_session("x.service"))


class NativeLauncherTest(unittest.TestCase):
    """swayctl-bar's Spotlight over elephant (launcher.program = swayctl-bar)."""

    def ctx(self, bar_program="swayctl-bar", launcher_program="swayctl-bar", **launcher):
        v = schema.defaults()
        v["bar"]["program"] = bar_program
        v["launcher"] |= {"program": launcher_program} | launcher
        return Context(Path("/tmp/x"), values=v, theme=themes.BUILTIN["dark"]), v

    def test_bar_launcher_runs_elephant_without_walker(self):
        from swayctl_center.modules.launcher import LauncherModule
        c, v = self.ctx()
        self.assertEqual(set(LauncherModule().programs(v["launcher"], c)), {"elephant"})
        # Walker chosen, or the bar is waybar: Walker as before
        for bar, prog in (("swayctl-bar", "walker"), ("waybar", "swayctl-bar")):
            c, v = self.ctx(bar, prog)
            self.assertEqual(set(LauncherModule().programs(v["launcher"], c)), {"elephant", "walker"})

    def test_bar_config_carries_providers_and_prefixes(self):
        from swayctl_center.modules.components import BarModule
        c, v = self.ctx(runner=True, files_in_results=True)
        cfg = BarModule().native_config(v["bar"], c)["launcher"]
        self.assertEqual(cfg["providers"], ["desktopapplications", "menus", "calc", "websearch", "files"])
        pre = {p["prefix"]: p["provider"] for p in cfg["prefixes"]}
        self.assertEqual(pre, {"=": "calc", "/": "files", "@": "websearch", ".": "symbols",
                               "$": "windows", ">": "runner", ":": "clipboard", ";": "providerlist"})
        # clipboard not managed by swayctl-center: no ":" (no cliphist history)
        c.values["clipboard"]["managed"] = False
        pre = {p["prefix"] for p in BarModule().native_config(v["bar"], c)["launcher"]["prefixes"]}
        self.assertNotIn(":", pre)
        # a provider switched off loses its prefix too
        c, v = self.ctx(symbols=False)
        pre = {p["prefix"] for p in BarModule().native_config(v["bar"], c)["launcher"]["prefixes"]}
        self.assertNotIn(".", pre)
        self.assertIn("launcher", BarModule.depends_on)


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c = Context(Path(self.tmp.name), values=schema.defaults(), theme=themes.BUILTIN["dark"])
        self.env = mock.patch.dict(os.environ, {"SWAYCTL_CENTER_BIN": "/usr/bin/swayctl-center"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_generated_config_is_valid_toml_and_follows_settings(self):
        import tomllib
        from swayctl_center.modules.launcher import LauncherModule
        v = schema.defaults()["launcher"] | {"files_in_results": True, "runner": True, "websearch": False,
                                             "search_engine": "duckduckgo", "file_folders": ["~", "/data"],
                                             "file_excluded": ["~/Videos"], "file_watch": False}
        files = LauncherModule().files(v, self.c)
        for name, text in files.items():
            if name.endswith(".toml"):
                tomllib.loads(text)
        walker = tomllib.loads(files["walker/config.toml"])
        self.assertEqual(walker["theme"], "swayctl-center")
        self.assertIn("files", walker["providers"]["default"])          # files without typing /
        self.assertNotIn("websearch", walker["providers"]["default"])
        prefixes = {p["prefix"]: p["provider"] for p in walker["providers"]["prefixes"]}
        self.assertEqual(prefixes[">"], "runner")
        self.assertNotIn("@", prefixes)
        fcfg = tomllib.loads(files["elephant/files.toml"])
        self.assertEqual(fcfg["search_dirs"], [str(Path.home()), "/data"])
        self.assertEqual(fcfg["ignored_dirs"], [str(Path.home() / "Videos")])
        self.assertFalse(fcfg["watch"])
        self.assertIn("duckduckgo.com", files["elephant/websearch.toml"])
        menu = tomllib.loads(files["elephant/menus/swayctl-center.toml"])
        self.assertTrue(all(e["actions"]["open"].startswith("/usr/bin/swayctl-center ") for e in menu["entries"]))
        self.assertIn("@define-color window_bg_color #1c1c1e;", files["walker/themes/swayctl-center/style.css"])

    def test_units_and_missing_packages(self):
        from swayctl_center.modules import launcher
        m = launcher.LauncherModule()
        v = schema.defaults()["launcher"]
        progs = m.programs(v, self.c)
        self.assertEqual(progs["elephant"][:2], ["elephant", "--config"])
        self.assertEqual(m.program_env("walker", v, self.c)["XDG_CONFIG_HOME"], str(m.root(self.c)))
        with mock.patch.object(launcher, "installed_plugins", return_value={"desktopapplications", "calc"}), \
             mock.patch.object(launcher.units, "installed", return_value=True):
            missing = m.missing_packages(v)
        self.assertNotIn("elephant-calc-bin", missing)
        self.assertIn("elephant-files-bin", missing)
        self.assertIn("elephant-providerlist-bin", missing)

    def test_folders_validated(self):
        key = schema.lookup("launcher", "file_folders")
        self.assertEqual(key.validate(["~", "~", "/data"]), ["~", "/data"])
        with self.assertRaises(ValueError):
            key.validate(["relative/dir"])


class SmoothScrollingTest(unittest.TestCase):
    def test_sway_leaves_scrolling_to_the_service(self):
        from swayctl_center.modules import scrolling
        from swayctl_center.modules.input import InputModule
        values = schema.defaults()
        values["input.touchpad"] |= {"natural_scroll": True, "scroll_factor": 2.0, "scroll_method": "two_finger"}
        values["input.pointer"] |= {"natural_scroll": True, "scroll_factor": 3.0}
        c = Context(Path("/x"), values=values)
        with mock.patch.object(scrolling, "service_running", return_value=True):
            tp = InputModule().commands("input.touchpad", values["input.touchpad"], None, c)
            ptr = InputModule().commands("input.pointer", values["input.pointer"], None, c)
        self.assertIn("input type:touchpad scroll_method none", tp)
        self.assertFalse(any("natural_scroll" in x or "scroll_factor" in x for x in tp))
        self.assertIn("input type:pointer natural_scroll disabled", ptr)
        self.assertIn("input type:pointer scroll_factor 1.0", ptr)
        # smooth scrolling switched off: sway scrolls with the user's settings again
        values["scrolling"]["touchpad_smooth"] = values["scrolling"]["mouse_smooth"] = False
        with mock.patch.object(scrolling, "service_running", return_value=True):
            tp = InputModule().commands("input.touchpad", values["input.touchpad"], None, c)
            ptr = InputModule().commands("input.pointer", values["input.pointer"], None, c)
        self.assertIn("input type:touchpad scroll_method two_finger", tp)
        self.assertIn("input type:touchpad natural_scroll enabled", tp)
        self.assertIn("input type:pointer scroll_factor 3.0", ptr)

    def test_service_config_and_old_script_adoption(self):
        from swayctl_center.modules import scrolling
        v = schema.defaults()["scrolling"] | {"mouse_smooth": False, "touchpad_speed": 2.0}
        cfg = scrolling.service_config(v)
        self.assertEqual(cfg["touchpad"]["speed"], 2.0)
        self.assertFalse(cfg["mouse"]["enabled"])
        self.assertEqual(cfg["mouse"]["ramp_floor"], v["mouse_ramp_floor"])
        with tempfile.TemporaryDirectory() as d:
            old = Path(d) / "touchpad-inertia.py"
            old.write_text("FRICTION = 0.97   # x\nGAIN = 1.5\nNATURAL_SCROLL = False\nMOUSE_RAMP_POWER = 0.7999999999999997\n")
            with mock.patch.object(scrolling, "OLD_SCRIPTS", (old,)):
                got = scrolling.adopt_old_script()
        self.assertEqual(got, {"touchpad_glide": 0.97, "touchpad_speed": 1.5, "touchpad_natural": False,
                               "mouse_ramp_power": 0.8})
        for k, x in got.items():
            schema.lookup("scrolling", k).validate(x)
        script = scrolling.install_script(Path("/home/u/.config/swayctl-center"))
        self.assertIn("SMOOTH_SCROLL_CONFIG=/home/u/.config/swayctl-center/generated/smoothscroll.json", script)
        self.assertIn("disable --now touchpad-inertia.service", script)

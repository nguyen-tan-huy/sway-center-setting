import tempfile
import unittest
from pathlib import Path

from swayctl_center import swayconfig


class ParseTest(unittest.TestCase):
    def test_variables_includes_blocks_continuations(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "conf.d").mkdir()
            (d / "conf.d/10-font.conf").write_text("font pango:Inter 11\n")
            (d / "theme.conf").write_text("set $bg #fbf1c7\nset $bg_bare fbf1c7\n")
            text = "\n".join([
                "set $mod Mod4",
                "include theme.conf",
                "include conf.d/*",
                "# bindsym $mod+x commented",
                "output * bg $bg solid_color",
                "exec swayidle -w \\",
                "    timeout 300 'lock'",
                "bindsym $mod+Return exec kitty",
                'mode "resize" {',
                "    bindsym Left resize shrink width 10px",
                "}",
                "set $bgx $bg_bare",
                "exec echo $bgx",
            ])
            cfg = swayconfig.parse(text, d)
        top = cfg.top_level()
        self.assertIn("font pango:Inter 11", top)
        self.assertIn("output * bg #fbf1c7 solid_color", top)
        self.assertIn("exec swayidle -w timeout 300 'lock'", top)
        self.assertIn("bindsym Mod4+Return exec kitty", top)
        self.assertIn("exec echo fbf1c7", top)  # longest variable name wins
        self.assertNotIn("bindsym Left resize shrink width 10px", top)
        nested = [l for l in cfg.lines if l.blocks]
        self.assertEqual(nested[0].blocks, ('mode "resize"',))

    def test_include_cycle(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "a").write_text("include b\ngaps inner 1\n")
            (d / "b").write_text("include a\n")
            cfg = swayconfig.parse("include a", d)
        self.assertEqual(cfg.top_level(), ["gaps inner 1"])


if __name__ == "__main__":
    unittest.main()

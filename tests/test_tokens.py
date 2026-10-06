import json
import tempfile
import unittest
from pathlib import Path

from swayctl_center import theming, themes


class ColorMathTest(unittest.TestCase):
    def test_oklab_round_trip(self):
        for c in ("#000000", "#ffffff", "#3584e4", "#0a84ff", "#1c1c1e", "#ff0000"):
            self.assertEqual(themes.from_oklab(*themes.to_oklab(c)), c)

    def test_mix_endpoints_and_midpoint(self):
        self.assertEqual(themes.mix("#000000", "#ffffff", 0), "#000000")
        self.assertEqual(themes.mix("#000000", "#ffffff", 1), "#ffffff")
        mid = themes.mix("#000000", "#ffffff", 0.5)
        self.assertTrue(themes.luminance("#000000") < themes.luminance(mid) < themes.luminance("#ffffff"))

    def test_oklch_stays_in_gamut(self):
        # a chroma far outside sRGB is reduced instead of clipped per channel
        c = themes.oklch(0.7, 0.5, 150)
        self.assertRegex(c, r"^#[0-9a-f]{6}$")
        self.assertLess(abs(themes.hue(c) - 150), 8)

    def test_contrast(self):
        self.assertAlmostEqual(themes.contrast("#000000", "#ffffff"), 21, places=1)
        self.assertEqual(themes.contrast("#3584e4", "#3584e4"), 1)


class TokensTest(unittest.TestCase):
    def test_every_builtin_has_all_tokens(self):
        for t in themes.BUILTIN.values():
            tok = t.tokens
            for k in themes.COLOR_TOKENS:
                self.assertRegex(tok[k], r"^#[0-9a-f]{6}$", f"{t.name}.{k}")
            for k in themes.SHAPE:
                self.assertIn(k, tok)

    def test_readability(self):
        for t in themes.BUILTIN.values():
            tok = t.tokens
            self.assertGreaterEqual(themes.contrast(tok["text"], tok["surface"]), 4.5, t.name)  # WCAG AA; solarized is 4.7
            self.assertGreaterEqual(themes.contrast(tok["text_secondary"], tok["surface"]), 3.5, t.name)
            self.assertGreaterEqual(themes.contrast(tok["accent_fg"], tok["accent"]), 3, t.name)
            for k in ("success", "warning", "error"):
                self.assertGreaterEqual(themes.contrast(tok[k], tok["surface"]), 2.5, f"{t.name}.{k}")

    def test_surfaces_step_toward_text(self):
        for t in themes.BUILTIN.values():
            tok = t.tokens
            d = [themes.contrast(tok[k], tok["surface"])
                 for k in ("surface", "surface_raised", "surface_overlay")]
            self.assertEqual(d, sorted(d), t.name)

    def test_from_accent(self):
        dark = themes.from_accent("x", "#3584e4", dark=True)
        light = themes.from_accent("y", "#3584e4", dark=False)
        self.assertTrue(dark.dark)
        self.assertFalse(light.dark)
        self.assertEqual(dark.accent, "#3584e4")
        # neutrals are tinted toward the accent's hue
        self.assertLess(abs(themes.hue(dark.bg) - themes.hue("#3584e4")), 20)

    def test_overrides(self):
        t = themes.Theme("x", "#1c1c1e", "#f5f5f7", "#0a84ff", "#636366", {"radius_md": 4, "error": "#ff0000"})
        self.assertEqual(t.tokens["radius_md"], 4)
        self.assertEqual(t.tokens["error"], "#ff0000")
        self.assertEqual(t, themes.Theme("x", "#1c1c1e", "#f5f5f7", "#0a84ff", "#636366"))
        hash(t)  # still usable as a key

    def test_to_json_carries_tokens(self):
        j = themes.BUILTIN["dark"].to_json()
        self.assertEqual(j["tokens"]["surface"], "#1c1c1e")
        json.dumps(j)


class UserThemeTest(unittest.TestCase):
    def load(self, **files):
        d = Path(tempfile.mkdtemp())
        (d / "themes").mkdir()
        for name, raw in files.items():
            (d / "themes" / f"{name}.json").write_text(json.dumps(raw))
        return themes.load_all(d)

    def test_accent_only(self):
        t = self.load(mine={"accent": "#e66100", "variant": "light"})["mine"]
        self.assertFalse(t.dark)
        self.assertEqual(t.accent, "#e66100")

    def test_four_colors_with_tokens(self):
        t = self.load(mine={"bg": "#101010", "fg": "#eeeeee", "accent": "#00aaff", "muted": "#666666",
                            "tokens": {"radius_lg": 20}})["mine"]
        self.assertEqual(t.tokens["radius_lg"], 20)

    def test_bad_files_ignored(self):
        with self.assertLogs("swayctl_center.themes", "WARNING"):
            loaded = self.load(a={"accent": "blue"}, b={"accent": "#e66100", "variant": "dim"},
                               c={"accent": "#e66100", "tokens": {"nope": 1}},
                               d={"accent": "#e66100", "tokens": {"radius_md": -1}},
                               e={"accent": "#e66100", "tokens": {"error": "red"}})
        self.assertFalse({"a", "b", "c", "d", "e"} & loaded.keys())


class PlaceholderTest(unittest.TestCase):
    def test_old_placeholders_unchanged(self):
        p = theming.placeholders(themes.BUILTIN["dark"], None)
        self.assertEqual(p["@BORDER@"], "0a84ff")   # paper compat: accent, not the outline token
        self.assertEqual(p["@BG_HEX@"], "#1c1c1e")
        self.assertEqual(p["@MATCH@"], "636366")

    def test_token_placeholders(self):
        t = themes.BUILTIN["dark"]
        p = theming.placeholders(t, None)
        self.assertEqual(p["@SURFACE_RAISED_HEX@"], t.tokens["surface_raised"])
        self.assertEqual(p["@OUTLINE@"], t.tokens["outline"].lstrip("#"))
        self.assertEqual(p["@RADIUS_MD@"], "10")
        self.assertEqual(p["@PANEL_OPACITY@"], "0.88")
        self.assertEqual(p["@PANEL_ALPHA@"], "e0")
        self.assertEqual(theming.render("a:@ACCENT_FG_HEX@ r:@RADIUS_LG@px", p),
                         f"a:{t.tokens['accent_fg']} r:14px")

    def test_adwaita_css(self):
        t = themes.BUILTIN["dark"]
        css = theming.adwaita_css(t)
        self.assertIn(f"@define-color accent_bg_color {t.accent};", css)
        self.assertIn(f"--window-bg-color: {t.tokens['surface']};", css)
        self.assertIn(f"--popover-bg-color: {t.tokens['surface_overlay']};", css)
        self.assertIn("--window-radius: 14px;", css)


if __name__ == "__main__":
    unittest.main()

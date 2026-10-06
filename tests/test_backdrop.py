import tempfile
import unittest
from pathlib import Path

from swayctl_center import backdrop


class BackdropTest(unittest.TestCase):
    def test_text_choice(self):
        self.assertTrue(backdrop.wants_dark_text(0.9, 0.0, 0.0))    # white wallpaper: dark text
        self.assertFalse(backdrop.wants_dark_text(0.02, 0.0, 0.0))  # black: light text
        # thick smoked glass makes light text fine even on a light wallpaper
        self.assertFalse(backdrop.wants_dark_text(0.4, 0.9, 0.0))  # 9.6:1 vs 7.3:1

    def test_grid_follows_fill_layout(self):
        import cairo
        with tempfile.TemporaryDirectory() as d:
            img = str(Path(d) / "half.png")
            s = cairo.ImageSurface(cairo.FORMAT_RGB24, 200, 100)
            c = cairo.Context(s)
            c.set_source_rgb(1, 1, 1); c.rectangle(0, 0, 100, 100); c.fill()   # left white
            c.set_source_rgb(0, 0, 0); c.rectangle(100, 0, 100, 100); c.fill()  # right black
            s.write_to_png(img)
            g = backdrop.grid(img, "fill", "#808080", 1920, 1080)
            self.assertGreater(backdrop.mean(g, 1920, 1080, 100, 400, 200, 100), 0.9)
            self.assertLess(backdrop.mean(g, 1920, 1080, 1600, 400, 200, 100), 0.05)
            # fit: bars of the background color above and below a 2:1 image on 16:9
            g = backdrop.grid(img, "fit", "#ff0000", 1920, 1080)
            self.assertAlmostEqual(backdrop.mean(g, 1920, 1080, 900, 0, 100, 40), backdrop.color_luminance("#ff0000"), 3)

    def test_window_on_output(self):
        tree = {"nodes": [{"nodes": [{"app_id": "x", "rect": {"x": 2000, "y": 50, "width": 800, "height": 600}}]}]}
        outputs = [{"rect": {"x": 0, "y": 0, "width": 1920, "height": 1080}},
                   {"rect": {"x": 1920, "y": 0, "width": 1920, "height": 1080}}]
        rect, out = backdrop.window_on_output(tree, "x", outputs)
        self.assertEqual((rect["x"], out["x"]), (2000, 1920))
        self.assertIsNone(backdrop.window_on_output(tree, "y", outputs))

    def test_readable_over_every_color_and_detail(self):
        """4.5:1 holds for every color/envelope: the CSS gradient's weakest
        row is alpha x 0.9 over the region's true floor/peak."""
        def worst(dark, step, lo, hi):
            a = 0.9 * step / 10
            if dark:
                under = a * 0.913 + (1 - a) * lo
                return (under + 0.05) / (0.012 + 0.05)
            under = a * 0.0116 + (1 - a) * hi
            return (0.913 + 0.05) / (under + 0.05)

        pal = [0.0, 0.0116, 0.0722, 0.1, 0.184, 0.2126, 0.3, 0.5,
               0.7152, 0.8, 0.913, 1.0]
        for m in pal:
            for lo in pal:
                for hi in pal:
                    if lo > m or hi < m:
                        continue  # the envelope contains the mean
                    for td, tl in ((0.0, 0.0), (0.5, 0.1), (0.9, 0.02)):
                        dark, step = backdrop.choose((m, lo, hi), td, tl)
                        self.assertLessEqual(step, 10)
                        c = worst(dark, step, lo, hi)
                        self.assertGreaterEqual(
                            c, 4.5 - 1e-3,
                            f"mean={m} lo={lo} hi={hi} tints=({td},{tl}): "
                            f"dark={dark} step={step} contrast={c:.2}")


if __name__ == "__main__":
    unittest.main()

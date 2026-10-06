"""What's behind a window: the wallpaper (sway tiles windows side by side, so a
tiled window has the wallpaper behind it). A small luminance grid of it, laid
out on the output like `output * bg <image> <mode>`, tells each pane of glass
in the settings window whether light or dark text stands out over it -- the
same choice swayctl-bar makes for its modules (ui/backdrop.rs).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

GW, GH = 96, 54
SMOKE, MILK = 0.0116, 0.913  # luminance of #1c1c1e and #f5f5f7


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(r: int, g: int, b: int) -> float:
    return 0.2126 * _linear(r / 255) + 0.7152 * _linear(g / 255) + 0.0722 * _linear(b / 255)


def color_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    try:
        return luminance(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except (ValueError, IndexError):
        return 0.0


def wants_dark_text(lum: float, tint_dark: float, tint_light: float) -> bool:
    """Milky glass with dark text easier to read here than smoked glass with
    light text? Each tint mixes into what's behind before the text sees it."""
    under_light = lum * (1 - tint_dark) + SMOKE * tint_dark
    under_dark = lum * (1 - tint_light) + MILK * tint_light
    return (under_dark + 0.05) / (0.012 + 0.05) > (MILK + 0.05) / (under_light + 0.05)


def _map(mode: str, mx: float, my: float, w: float, h: float, iw: float, ih: float) -> tuple[float, float]:
    """Output point -> point in the original image, as sway lays it out."""
    if mode == "stretch":
        return mx * iw / w, my * ih / h
    if mode == "fit":
        s = min(w / iw, h / ih)
        return (mx - (w - iw * s) / 2) / s, (my - (h - ih * s) / 2) / s
    if mode == "center":
        return mx - (w - iw) / 2, my - (h - ih) / 2
    if mode == "tile":
        return mx % iw, my % ih
    s = max(w / iw, h / ih)  # fill
    return (mx - (w - iw * s) / 2) / s, (my - (h - ih * s) / 2) / s


@lru_cache(maxsize=4)
def grid(image: str, mode: str, color: str, width: int, height: int):
    """(mean, min, max) luminance grids of an output of width x height.
    2x2 samples per cell: the mean picks the side, the min/max keep the
    envelope a mean would hide (bright glyph on dark, hole in light)."""
    fill = color_luminance(color)
    lum = [fill] * (GW * GH)
    lmin = [fill] * (GW * GH)
    lmax = [fill] * (GW * GH)
    if not image:
        return tuple(lum), tuple(lmin), tuple(lmax)
    try:
        from gi.repository import GdkPixbuf
        _fmt, iw, ih = GdkPixbuf.Pixbuf.get_file_info(image)
        px = GdkPixbuf.Pixbuf.new_from_file_at_scale(image, 320, 320, True)
    except Exception:  # unreadable or gone: just the color
        return tuple(lum), tuple(lmin), tuple(lmax)
    if not iw or not ih:
        return tuple(lum), tuple(lmin), tuple(lmax)
    data, stride, n = px.get_pixels(), px.get_rowstride(), px.get_n_channels()
    pw, ph = px.get_width(), px.get_height()
    for gy in range(GH):
        for gx in range(GW):
            got = []
            for oy in (0.25, 0.75):
                for ox in (0.25, 0.75):
                    ix, iy = _map(mode, (gx + ox) * width / GW, (gy + oy) * height / GH,
                                  width, height, iw, ih)
                    if not (0 <= ix < iw and 0 <= iy < ih):
                        continue
                    sx, sy = min(int(ix / iw * pw), pw - 1), min(int(iy / ih * ph), ph - 1)
                    o = sy * stride + sx * n
                    got.append(luminance(data[o], data[o + 1], data[o + 2]))
            if got:
                k = gy * GW + gx
                lum[k] = sum(got) / len(got)
                lmin[k] = min(got)
                lmax[k] = max(got)
    return tuple(lum), tuple(lmin), tuple(lmax)


def stats(g, width: int, height: int, x: float, y: float, w: float, h: float):
    """(mean, darkest, brightest) luminance under a rectangle: the floor/peak
    come from the per-cell envelope, not from cell averages."""
    lum, lmin, lmax = g
    def cell(v: float, size: int, n: int) -> int:
        return max(0, min(n - 1, int(v / size * n)))
    x0, x1 = cell(x, width, GW), cell(x + w, width, GW)
    y0, y1 = cell(y, height, GH), cell(y + h, height, GH)
    ks = [gy * GW + gx for gy in range(y0, y1 + 1) for gx in range(x0, x1 + 1)] or [0]
    return (sum(lum[k] for k in ks) / len(ks), min(lmin[k] for k in ks),
            max(lmax[k] for k in ks))


def choose(lum: tuple[float, float, float], tint_dark: float, tint_light: float) -> tuple[bool, int]:
    """(dark text?, tint step 0-10): the text by the mean, and glass thick
    enough that it reads (4.5:1) even over the hardest pixel behind the pane
    -- any color, any detail, because lo/hi are the true envelope. The tint-N
    gradient's bottom is alpha x 0.9, so the needed alpha divides by 0.9."""
    mean_l, lo, hi = lum
    dark = wants_dark_text(mean_l, tint_dark, tint_light)
    if dark:   # milky: lift the darkest pixel to >= 0.229
        need = (0.229 - lo) / max(MILK - lo, 1e-3) / 0.9
        tint = max(tint_light, need)
    else:      # smoked: bring the brightest pixel down to <= 0.164
        need = (hi - 0.164) / max(hi - SMOKE, 1e-3) / 0.9
        tint = max(tint_dark, need)
    return dark, max(0, min(10, int(tint * 10 + 0.999)))


def mean(g, width: int, height: int, x: float, y: float, w: float, h: float) -> float:
    """Mean luminance under a rectangle of the output (logical px)."""
    lum = g[0]
    def cell(v: float, size: int, n: int) -> int:
        return max(0, min(n - 1, int(v / size * n)))
    x0, x1 = cell(x, width, GW), cell(x + w, width, GW)
    y0, y1 = cell(y, height, GH), cell(y + h, height, GH)
    vals = [lum[gy * GW + gx] for gy in range(y0, y1 + 1) for gx in range(x0, x1 + 1)]
    return sum(vals) / len(vals) if vals else 0.0


def window_on_output(tree: dict[str, Any], app_id: str, outputs: list[dict[str, Any]]):
    """(window rect, output rect) of the first window with `app_id`, both in
    layout coordinates; None when it isn't mapped."""
    stack = [tree]
    while stack:
        node = stack.pop()
        if node.get("app_id") == app_id and node.get("visible", True):
            r = node["rect"]
            cx, cy = r["x"] + r["width"] / 2, r["y"] + r["height"] / 2
            for o in outputs:
                orc = o.get("rect") or {}
                if orc and orc["x"] <= cx < orc["x"] + orc["width"] and orc["y"] <= cy < orc["y"] + orc["height"]:
                    return r, orc
            return None
        stack.extend(node.get("nodes", []) + node.get("floating_nodes", []))
    return None

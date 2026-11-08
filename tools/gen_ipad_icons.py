#!/usr/bin/env python3
"""Draw the bar's iPadOS-style icon set (fills only: GTK recolours a symbolic icon by its fill) and write
  swayctl-bar/data/icons/*.svg        the set, one file each (also viewable on their own)
  swayctl-bar/src/ui/ipad_icons.rs    the same, embedded in the binary (written to a private icon path at start)
  tools/out/ipad-icons.html           a sheet of all of them, enlarged
Original drawings in the manner of the iPadOS status bar: rounded, even weight, a fan for Wi-Fi, a filled
level in the battery. Run:  python3 tools/gen_ipad_icons.py"""
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">{}</svg>\n'


def pt(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def sector(cx, cy, r1, r2, a0, a1, opacity=1.0):
    """An arc band between radii r1 < r2, from angle a0 to a1 (degrees, 0 = east, clockwise on screen)."""
    (x0, y0), (x1, y1) = pt(cx, cy, r2, a0), pt(cx, cy, r2, a1)
    (x2, y2), (x3, y3) = pt(cx, cy, r1, a1), pt(cx, cy, r1, a0)
    big = 1 if abs(a1 - a0) > 180 else 0
    d = f"M{x0:.2f} {y0:.2f}A{r2} {r2} 0 {big} 1 {x1:.2f} {y1:.2f}L{x2:.2f} {y2:.2f}A{r1} {r1} 0 {big} 0 {x3:.2f} {y3:.2f}Z"
    return f'<path d="{d}"{_op(opacity)}/>'


def _op(o):
    return "" if o >= 1 else f' opacity="{o}"'


def circle(cx, cy, r, opacity=1.0):
    return f'<circle cx="{cx}" cy="{cy}" r="{r}"{_op(opacity)}/>'


def line(x1, y1, x2, y2, w, opacity=1.0):
    """A thick line with round ends, as fills (a rotated bar and two discs)."""
    dx, dy = x2 - x1, y2 - y1
    n = math.hypot(dx, dy) or 1
    nx, ny = -dy / n * w / 2, dx / n * w / 2
    d = f"M{x1 + nx:.2f} {y1 + ny:.2f}L{x2 + nx:.2f} {y2 + ny:.2f}L{x2 - nx:.2f} {y2 - ny:.2f}L{x1 - nx:.2f} {y1 - ny:.2f}Z"
    return f'<path d="{d}"{_op(opacity)}/>' + circle(x1, y1, w / 2, opacity) + circle(x2, y2, w / 2, opacity)


def rrect_d(x, y, w, h, r):
    return (f"M{x + r} {y}H{x + w - r}A{r} {r} 0 0 1 {x + w} {y + r}V{y + h - r}A{r} {r} 0 0 1 {x + w - r} {y + h}"
            f"H{x + r}A{r} {r} 0 0 1 {x} {y + h - r}V{y + r}A{r} {r} 0 0 1 {x + r} {y}Z")


icons: dict[str, str] = {}

# ---- Wi-Fi: a dot and three bands in a fan, the ones not reached dimmed
for level in range(4):
    parts = [circle(8, 12.6, 1.35, 1 if level else 0.3)]
    for i, (r1, r2) in enumerate(((3.3, 5.0), (6.0, 7.7), (8.7, 10.4))):
        parts.append(sector(8, 12.6, r1, r2, -133, -47, 1 if i < level else 0.3))
    icons[f"swayctl-wifi-{level}"] = SVG.format("".join(parts))
off = [circle(8, 12.6, 1.35, 0.3)] + [sector(8, 12.6, a, b, -133, -47, 0.3) for a, b in ((3.3, 5.0), (6.0, 7.7), (8.7, 10.4))]
icons["swayctl-wifi-off"] = SVG.format("".join(off) + line(2.6, 2.6, 13.4, 13.4, 1.4))

# ---- sound: a speaker and up to three waves; muted is struck through
speaker = '<path d="M1.6 6.1H4.2L7.6 3.1C8 2.8 8.5 3 8.5 3.5V12.5C8.5 13 8 13.2 7.6 12.9L4.2 9.9H1.6C1.2 9.9 1 9.7 1 9.3V6.7C1 6.3 1.2 6.1 1.6 6.1Z"/>'
for n in range(4):
    waves = "".join(sector(7.6, 8, r1, r2, -42, 42, 1 if i < n else 0.0) for i, (r1, r2) in enumerate(((2.9, 4.1), (5.0, 6.2), (7.1, 8.3))) if i < n)
    icons[f"swayctl-volume-{n}"] = SVG.format(speaker + waves)
icons["swayctl-volume-muted"] = SVG.format(speaker + line(10.2, 6.2, 14.2, 9.8, 1.3) + line(14.2, 6.2, 10.2, 9.8, 1.3))

# ---- battery: an outline, a level bar, a nub; the bolt is a cut-out of the bar
BOLT = "M8.9 4.4L5.6 8.5H7.7L7 11.6L10.4 7.4H8.3Z"
for level in range(0, 101, 10):
    outline = rrect_d(0.6, 4.0, 13.4, 8.0, 2.4) + rrect_d(1.6, 5.0, 11.4, 6.0, 1.5)
    width = max(0.0, 9.4 * level / 100) if level else 0
    fill = rrect_d(2.6, 6.0, width, 4.0, 0.9) if width >= 1.0 else ""
    nub = rrect_d(14.5, 6.6, 1.0, 2.8, 0.5)
    base = f'<path fill-rule="evenodd" d="{outline}"/>' + (f'<path d="{fill}"/>' if fill else "") + f'<path d="{nub}"/>'
    icons[f"swayctl-battery-{level}"] = SVG.format(base)
    # charging: the bolt over the middle - solid where the level bar isn't, a hole where it is
    chg_fill = (fill or "") + BOLT
    icons[f"swayctl-battery-{level}-charging"] = SVG.format(
        f'<path fill-rule="evenodd" d="{outline}"/>' + f'<path fill-rule="evenodd" d="{chg_fill}"/>' + f'<path d="{nub}"/>')

# ---- Bluetooth: the rune, as one stroked outline
pts = [(4.7, 4.9), (11.3, 11.1), (8.2, 14.0), (8.2, 2.0), (11.3, 4.9), (4.7, 11.1)]
icons["swayctl-bluetooth"] = SVG.format("".join(line(*a, *b, 1.3) for a, b in zip(pts, pts[1:])))

# ---- brightness: a disc and eight rays
rays = "".join(line(*pt(8, 8, 4.6, a), *pt(8, 8, 6.4, a), 1.3) for a in range(0, 360, 45))
icons["swayctl-sun"] = SVG.format(circle(8, 8, 2.7) + rays)

# ---- Ethernet: a socket with its pins
icons["swayctl-ethernet"] = SVG.format(
    f'<path fill-rule="evenodd" d="{rrect_d(1.6, 3.2, 12.8, 8.4, 2.2)}{rrect_d(2.8, 4.4, 10.4, 6.0, 1.2)}"/>'
    + "".join(f'<path d="{rrect_d(4.2 + 2.2 * i, 7.2, 1.2, 3.2, 0.4)}"/>' for i in range(4))
    + f'<path d="{rrect_d(5.6, 11.6, 4.8, 1.6, 0.6)}"/>')

(ROOT / "swayctl-bar/data/icons").mkdir(parents=True, exist_ok=True)
for name, svg in icons.items():
    (ROOT / f"swayctl-bar/data/icons/{name}-symbolic.svg").write_text(svg)

rs = ["//! Generated by tools/gen_ipad_icons.py - do not edit. The iPadOS-style icon set, embedded.\n",
      "pub const ICONS: &[(&str, &str)] = &[\n"]
for name, svg in icons.items():
    rs.append(f'    ("{name}-symbolic", r#"{svg.strip()}"#),\n')
rs.append("];\n")
(ROOT / "swayctl-bar/src/ui/ipad_icons.rs").write_text("".join(rs))

cells = "".join(f'<figure><div class="i" style="color:#e8eaee">{svg}</div><figcaption>{name}</figcaption></figure>' for name, svg in icons.items())
out = ROOT / "tools/out"
out.mkdir(exist_ok=True)
(out / "ipad-icons.html").write_text(
    "<!doctype html><meta charset=utf-8><style>body{background:#1b1c1f;margin:16px;font:11px sans-serif;color:#8b93a1;display:flex;flex-wrap:wrap;gap:10px}"
    "figure{margin:0;width:118px;text-align:center}.i{width:96px;height:96px;margin:0 auto;background:#26282d;border-radius:10px;padding:16px;box-sizing:border-box}"
    ".i svg{width:64px;height:64px;fill:currentColor}.i svg *{fill:currentColor}</style>" + cells)
print(len(icons), "icons")

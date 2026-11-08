#!/bin/sh
# Are the corners of windows that sit in a corner of the screen square (and the others still round)?
#   tools/sandbox.sh --fx /home/repo/tools/screen_corners_check.sh [top|bottom]   (where a bar would be; here a strut)
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
swaymsg 'output * bg #ff00ff solid_color; corner_radius 24; default_border pixel 0; gaps inner 0; gaps outer 0' >/dev/null
foot --app-id a -e sh -c 'sleep 30' >/dev/null 2>&1 &
sleep 1.5
foot --app-id b -e sh -c 'sleep 30' >/dev/null 2>&1 &
sleep 2.5
grim /tmp/out/corners.png
python3 - <<'PY'
from PIL import Image
im = Image.open("/tmp/out/corners.png").convert("RGB"); w, h = im.size
def kind(x, y):
    r, g, b = im.getpixel((x, y))
    return "wallpaper" if (r > 200 and g < 60 and b > 200) else "window"
print("output", w, "x", h)
mid = w // 2
for name, (x, y) in {"screen top-left": (0, 0), "screen top-right": (w - 1, 0),
                     "screen bottom-left": (0, h - 1), "screen bottom-right": (w - 1, h - 1),
                     "left window, top-right (middle of the top edge)": (mid - 1, 0),
                     "right window, top-left (middle of the top edge)": (mid, 0),
                     "left window, bottom-right (middle of the bottom edge)": (mid - 1, h - 1)}.items():
    print(f"{name:55s} {kind(x, y)}")
PY

#!/bin/sh
# A window that is already open must follow a corner radius set afterwards (the way the settings app sets it:
# a plain command, with a window focused).   tools/sandbox.sh --fx /home/repo/tools/corner_radius_global_check.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
swaymsg 'output * bg #ff00ff solid_color; corner_radius 0; default_border pixel 2; gaps inner 10; gaps outer 10; shadows disable' >/dev/null
foot -e sleep 30 >/dev/null 2>&1 &
sleep 2
swaymsg 'floating enable, resize set 600 400, move position 300 200' >/dev/null   # away from the screen's corners
sleep 1
measure() {
  grim /tmp/out/crg-$1.png
  python3 - $1 <<'PY'
import sys, json, subprocess
from PIL import Image
im = Image.open(f"/tmp/out/crg-{sys.argv[1]}.png").convert("RGB")
tree = json.loads(subprocess.check_output(["swaymsg", "-t", "get_tree"]))
def wp(p): return p[0] > 235 and p[1] < 40 and p[2] > 235
def walk(n):
    if n.get("pid") and n.get("app_id"):
        r = n["rect"]; k = 0
        while k < 30 and wp(im.getpixel((r["x"] + k, r["y"]))): k += 1
        print(f"{sys.argv[1]:20s} notch at the window's top-left: {k} px")
    for c in n.get("nodes", []) + n.get("floating_nodes", []): walk(c)
walk(tree)
PY
}
measure radius0
swaymsg 'corner_radius 12' >/dev/null          # a plain command, the focused window is the foot above
sleep 1
measure then12_open_window

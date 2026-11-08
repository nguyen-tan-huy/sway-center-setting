#!/bin/sh
# Who rounds an app's window corners? Opens each app floating with the compositor's corner radius and
# measures the notch at the four corners (pixels of the wallpaper along the top row, from the corner in).
# Rounded by the compositor alone, radius 12: about 8-9 px. Much more: the app rounds too. 0: nobody does.
#   tools/sandbox.sh --fx /home/repo/tools/app_corners_check.sh
set -u
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)" 2>/dev/null
swaymsg 'output HEADLESS-1 resolution 4400x1300' >/dev/null
python3 -m swayctl_center daemon >/tmp/out/ac-daemon.log 2>&1 &
sleep 2.5
# the settings the daemon owns, set through it (it would undo them otherwise)
python3 -m swayctl_center set effects.corner_radius 12 >/dev/null
python3 -m swayctl_center set effects.shadows false >/dev/null
sleep 1.5
swaymsg 'output * bg #ff00ff solid_color' >/dev/null
APPS=${APPS:-"foot kitty settings chosua ide chrome"}
for a in $APPS; do
  case $a in
    foot) foot --app-id t-foot -e sleep 40 >/dev/null 2>&1 & ;;
    kitty) kitty --class t-kitty sleep 40 >/dev/null 2>&1 & ;;
    settings) python3 -m swayctl_center ui --page desktop >/tmp/out/ac-ui.log 2>&1 & ;;
    chosua) ${CHOSUA_BIN:-/usr/bin/chosua} >/tmp/out/ac-chosua.log 2>&1 & ;;
    ide) /usr/sbin/chodilamide-ide >/tmp/out/ac-ide.log 2>&1 & ;;
    chrome) google-chrome-stable --user-data-dir=/tmp/chrome-test --ozone-platform=wayland --no-first-run --no-default-browser-check about:blank >/tmp/out/ac-chrome.log 2>&1 & ;;
  esac
  sleep 0.7
done
sleep 14
echo "daemon: corner_radius=$(python3 -m swayctl_center get effects.corner_radius) ui_style=$(python3 -m swayctl_center get appearance.ui_style) border=$(python3 -m swayctl_center get layout.border) gaps=$(python3 -m swayctl_center get layout.gaps_inner)"
python3 - <<'PY'
import json, subprocess
tree = json.loads(subprocess.check_output(["swaymsg", "-t", "get_tree"]))
wins = []
def walk(n):
    if n.get("pid") and (n.get("app_id") or n.get("window_properties")):
        wins.append(n)
    for c in n.get("nodes", []) + n.get("floating_nodes", []):
        walk(c)
walk(tree)
names = [w.get("app_id") for w in wins]
print("windows found:", names)
import os
# float them apart, side by side at their real widths, so that none covers a corner of another
# (TILED=1: leave them tiled, as on the desktop: a floating GTK app or Chrome has no compositor border)
for w in ([] if os.environ.get("TILED") else wins):
    subprocess.run(["swaymsg", f'[con_id={w["id"]}] floating enable, resize set 560 420'], capture_output=True)
import time
time.sleep(1.5)
tree = json.loads(subprocess.check_output(["swaymsg", "-t", "get_tree"]))
wins = []
walk(tree)
x = 20
for w in ([] if os.environ.get("TILED") else wins):
    subprocess.run(["swaymsg", f'[con_id={w["id"]}] move position {x} 20'], capture_output=True)
    x += w["rect"]["width"] + 25
PY
sleep 1
# shadows would tint the pixels round the corners: measure without them
swaymsg '[app_id=".*"] shadows disable' >/dev/null
swaymsg '[class=".*"] shadows disable' >/dev/null 2>&1
sleep 1.5
grim /tmp/out/ac.png
python3 - <<'PY'
import json, subprocess
from PIL import Image
im = Image.open("/tmp/out/ac.png").convert("RGB")
tree = json.loads(subprocess.check_output(["swaymsg", "-t", "get_tree"]))
def wp(p): return p[0] > 235 and p[1] < 40 and p[2] > 235
def notch(x, y, dx, dy):
    # wallpaper pixels along the edge row/column going inward from the corner
    n = 0
    for i in range(40):
        px = (x + dx * i, y)
        if 0 <= px[0] < im.width and 0 <= px[1] < im.height and wp(im.getpixel(px)): n += 1
        else: break
    return n
def walk(n):
    if n.get("pid") and (n.get("app_id") or n.get("window_properties")):
        r = n["rect"]; b = n.get("current_border_width", 0)
        # rect is the whole container, border included
        x0, y0, x1, y1 = r["x"], r["y"], r["x"] + r["width"] - 1, r["y"] + r["height"] - 1
        name = n.get("app_id") or n["window_properties"].get("class")
        print(f"   rect {r['x']},{r['y']} {r['width']}x{r['height']} border {b}")
        print(f"{name:45s} top-left {notch(x0, y0, 1, 0):2d}  top-right {notch(x1, y0, -1, 0):2d}"
              f"  bottom-left {notch(x0, y1, 1, 0):2d}  bottom-right {notch(x1, y1, -1, 0):2d}")
    for c in n.get("nodes", []) + n.get("floating_nodes", []): walk(c)
walk(tree)
PY
python3 - <<'PY'
# the shape of each top-left corner: for the first rows, how many wallpaper pixels before the window starts
import json, subprocess
from PIL import Image
im = Image.open("/tmp/out/ac.png").convert("RGB")
tree = json.loads(subprocess.check_output(["swaymsg", "-t", "get_tree"]))
def wp(p): return p[0] > 235 and p[1] < 40 and p[2] > 235
def walk(n):
    if n.get("pid") and (n.get("app_id") or n.get("window_properties")):
        r = n["rect"]; name = n.get("app_id") or n["window_properties"].get("class")
        prof = []
        for dy in range(0, 14):
            k = 0
            while k < 30 and wp(im.getpixel((r["x"] + k, r["y"] + dy))): k += 1
            prof.append(k)
        print(f"{name[:28]:28s} rows 0..13: {prof}")
    for c in n.get("nodes", []) + n.get("floating_nodes", []): walk(c)
walk(tree)
PY
python3 - <<'PY'
# a zoomed look at each top-left corner (tools/out/corner-<app>.png)
import json, subprocess
from PIL import Image
im = Image.open("/tmp/out/ac.png").convert("RGB")
tree = json.loads(subprocess.check_output(["swaymsg", "-t", "get_tree"]))
tiles = []
def walk(n):
    if n.get("pid") and (n.get("app_id") or n.get("window_properties")):
        r = n["rect"]
        tiles.append(im.crop((r["x"] - 4, r["y"] - 4, r["x"] + 28, r["y"] + 28)).resize((256, 256), Image.NEAREST))
    for c in n.get("nodes", []) + n.get("floating_nodes", []): walk(c)
walk(tree)
S = Image.new("RGB", (266 * len(tiles), 256), (255, 255, 255))
for i, t in enumerate(tiles): S.paste(t, (i * 266, 0))
S.save("/tmp/out/corners-zoom.png")
PY


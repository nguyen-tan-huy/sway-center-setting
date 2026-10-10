#!/bin/sh
# Key ink on the settings window: after each thing that might lose it (reopen,
# workspace switch, a setting change, glass off/on, resize) count the pixels
# still in the key colour #FF00FE (= text the compositor didn't ink).
#   tools/sandbox.sh --fx /home/repo/tools/ink_repro.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/ink-daemon.log 2>&1 &
sleep 2.5
python3 -m swayctl_center set effects.glass true >/dev/null
python3 -m swayctl_center set appearance.mode dark >/dev/null
[ -f /tmp/out/wall-text.png ] && python3 -m swayctl_center set background.image /tmp/out/wall-text.png >/dev/null
sleep 1
swaymsg -t get_version | python3 -c "import json,sys; print('features:', ' '.join(json.load(sys.stdin).get('swayctl_features',[])))"
count() { # <label>: key-coloured pixels in a fresh screenshot
    grim -t ppm /tmp/out/ink-$1.ppm
    grim /tmp/out/ink-$1.png
    python3 - "$1" <<'PY'
import sys
data = open(f"/tmp/out/ink-{sys.argv[1]}.ppm", "rb").read()
parts = data.split(b"\n", 3)           # P6 / w h / 255 / pixels
px = parts[3]
n = sum(1 for i in range(0, len(px) - 2, 3) if px[i] > 235 and px[i + 1] < 40 and px[i + 2] > 225)
print(f"{sys.argv[1]:<22} key pixels: {n}")
PY
    rm -f /tmp/out/ink-$1.ppm
}
python3 -m swayctl_center ui --page network > /tmp/out/ink-ui.log 2>&1 &
ui=$!
sleep 3
[ "${TILED:-0}" = 1 ] || swaymsg 'floating enable, resize set 1300 860, move position center' >/dev/null 2>&1 || true
sleep 1
count 1-open
swaymsg workspace 2 >/dev/null; sleep 1; swaymsg workspace 1 >/dev/null; sleep 1.2
count 2-ws-switch
for i in 1 2 3 4 5 6; do swaymsg workspace 2 >/dev/null; sleep 0.15; swaymsg workspace 1 >/dev/null; sleep 0.15; done
sleep 1.2
count 3-ws-fast
python3 -m swayctl_center set effects.glass_opacity 40 >/dev/null; sleep 1.5
count 4-setting-change
python3 -m swayctl_center set effects.glass false >/dev/null; sleep 1.5
python3 -m swayctl_center set effects.glass true >/dev/null; sleep 2
count 5-glass-off-on
[ "${TILED:-0}" = 1 ] || { swaymsg 'resize set 1100 700' >/dev/null; sleep 1; swaymsg 'resize set 1300 860' >/dev/null; sleep 1.2; }
count 6-resize
swaymsg 'floating toggle' >/dev/null; sleep 1.2
count 7-float-toggle
swaymsg 'floating toggle' >/dev/null; sleep 1.2
count 7b-float-toggle-back
kill $ui 2>/dev/null || true; sleep 0.8
python3 -m swayctl_center ui --page sound > /tmp/out/ink-ui2.log 2>&1 &
ui=$!
sleep 3
count 8-reopen
kill $ui 2>/dev/null || true

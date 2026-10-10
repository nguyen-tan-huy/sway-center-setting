#!/bin/sh
# The compositor holds a stale for_window rule (key ink off) when the daemon
# starts: does the settings window still get inked? Then after `reload`.
#   tools/sandbox.sh --fx /home/repo/tools/ink_stale_rules.sh
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
# sway now holds a newer rule that switches key ink off (what a window opening
# without the right rules sees): the app still draws key-coloured text
swaymsg 'for_window [app_id="io.github.huyhappy.SwayctlCenter.Settings"] "glass enable, glass text none"' >/dev/null
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
swaymsg 'floating enable, resize set 1300 860, move position center' >/dev/null 2>&1 || true
sleep 1
count A-opened-under-a-stale-rule
swaymsg reload >/dev/null; sleep 2
count B-after-reload
kill $ui 2>/dev/null || true

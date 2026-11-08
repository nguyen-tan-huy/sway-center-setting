#!/bin/sh
# flat Quick Settings, main page and the Power sub-page (rows, header, buttons):
#   FRAME=#ff2900 tools/sandbox.sh --fx /home/repo/tools/quick_flat_pages_shot.sh
# Shots: tools/out/qf-main.png, qf-power.png
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/qf-daemon.log 2>&1 &
sleep 2.5
python3 -m swayctl_center set appearance.ui_style frame >/dev/null
[ -n "${FRAME:-}" ] && python3 -m swayctl_center set appearance.frame_color "$FRAME" >/dev/null
sleep 2.5
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
python3 tools/fake_mpris.py 2>/dev/null &
$bin --config-dir "$HOME/.config/swayctl-center/generated/bar" 2>/tmp/out/qf-bar.log &
sleep 2
swaymsg exec "foot -o colors-dark.background=1b1c1f sleep 600" >/dev/null; sleep 2
size() { swaymsg -t get_outputs | python3 -c "
import json,sys
for l in json.load(sys.stdin)[0].get('layer_shell_surfaces',[]):
    if l['namespace']=='swayctl-quick': print(l['extent']['width'], 'x', l['extent']['height'], '@', l['extent']['x'], l['extent']['y'])"; }
v=/home/repo/tools/vptr/vptr
$bin quick >/dev/null 2>&1 & sleep 1.5
grim -g "1300,0 620x520" /tmp/out/qf-main.png
set -- $(size); w=$1; h=$3; x=${5}; y=${6}
PAD=32; $v click $((x + w - PAD - 30)) $((y + h - PAD - 30)) 272 & sleep 1.5
grim -g "1300,0 620x520" /tmp/out/qf-power.png
grep -i "panic" /tmp/out/qf-bar.log | head -2

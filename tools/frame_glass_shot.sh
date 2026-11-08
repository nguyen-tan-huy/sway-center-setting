#!/bin/sh
# the frame style with a glass frame: bar, edges and gaps are one pane of liquid glass over the wallpaper
#   GAP=12 tools/sandbox.sh --fx /home/repo/tools/frame_glass_shot.sh
# Shots: tools/out/fglass-desktop.png (and fglass-solid.png for the solid frame, to compare)
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/fg-daemon.log 2>&1 &
sleep 2.5
sw() { python3 -m swayctl_center set "$1" "$2" >/dev/null; }
sw background.image /tmp/out/${WALL:-bgs/bg0.jpg}
sw appearance.ui_style frame
[ -n "${GAP:-}" ] && { sw layout.gaps_inner "$GAP"; sw layout.gaps_outer "$GAP"; }
sw appearance.frame_surface glass
sleep 3
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir "$HOME/.config/swayctl-center/generated/bar" 2>/tmp/out/fg-bar.log &
sleep 2
swaymsg exec "foot -o colors-dark.background=11141a sleep 600" >/dev/null; sleep 1.2
swaymsg exec "foot -o colors-dark.background=1d2a44 sleep 600" >/dev/null; sleep 3
grim /tmp/out/fglass-desktop.png
echo "layers: $(swaymsg -t get_outputs | python3 -c "
import json,sys
for l in json.load(sys.stdin)[0].get('layer_shell_surfaces',[]): print(l['namespace'], l['layer'], l['extent']['width'], 'x', l['extent']['height'], end='; ')")"
grep -i "panic\|rejected" /tmp/out/fg-daemon.log /tmp/out/fg-bar.log | head -3
sw appearance.frame_surface solid; sleep 3
grim /tmp/out/fglass-solid.png

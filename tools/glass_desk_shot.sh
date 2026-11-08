#!/bin/sh
# The glass desk: bar, edges and gaps are one sheet of liquid glass; two windows sit in it.
#   tools/sandbox.sh --fx /home/repo/tools/glass_desk_shot.sh      (WALL=poster|video)
# Shot: tools/out/glassdesk.png. The sandbox has no mp4 demuxer, so the wallpaper is a still of the video.
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/gd-daemon.log 2>&1 &
sleep 2.5
sw() { python3 -m swayctl_center set "$1" "$2" >/dev/null; }
sw appearance.ui_style glass
sleep 3
[ "${WALL:-poster}" = poster ] && swaymsg "output * bg /tmp/out/mesh_poster.png fill" >/dev/null
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir "$HOME/.config/swayctl-center/generated/bar" 2>/tmp/out/gd-bar.log &
sleep 2
swaymsg exec "foot -o colors-dark.background=11141a sleep 600" >/dev/null; sleep 1.2
swaymsg exec "foot -o colors-dark.background=1d2a44 sleep 600" >/dev/null; sleep 3
grim /tmp/out/glassdesk.png
python3 -c "import json;d=json.load(open('$HOME/.config/swayctl-center/generated/bar/config.json'));print('frame',d['frame'],'wallpaper',d['wallpaper'])"
grep -i "panic\|rejected\|error" /tmp/out/gd-daemon.log /tmp/out/gd-bar.log | head -5

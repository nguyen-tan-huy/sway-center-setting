#!/bin/sh
# interface style "frame": solid bar and background around the windows; Quick Settings flat
#   FRAME=#0b1014 tools/sandbox.sh --fx /home/repo/tools/frame_shot.sh
# Shots: tools/out/frame-desktop.png, frame-quick.png
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/fr-daemon.log 2>&1 &
sleep 2.5
python3 -m swayctl_center set appearance.ui_style frame >/dev/null
[ -n "${FRAME:-}" ] && python3 -m swayctl_center set appearance.frame_color "$FRAME" >/dev/null
sleep 2.5
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
gen="$HOME/.config/swayctl-center/generated/bar"
$bin --config-dir "$gen" 2>/tmp/out/fr-bar.log &
sleep 2
swaymsg exec "foot -o colors-dark.background=11141a sleep 600" >/dev/null; sleep 1.2
swaymsg exec "foot -o colors-dark.background=1d2a44 sleep 600" >/dev/null; sleep 2.5
grim /tmp/out/frame-desktop.png
$bin quick >/dev/null 2>&1 || true; sleep 1.5
grim /tmp/out/frame-quick.png
grep -i "panic\|rejected" /tmp/out/fr-daemon.log /tmp/out/fr-bar.log | head -3

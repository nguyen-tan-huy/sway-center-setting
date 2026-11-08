#!/bin/sh
# the frame style's flat OSD and launcher (and the gap setting):
#   GAP=16 FRAME=#eef0f4 tools/sandbox.sh --fx /home/repo/tools/frame_popups_shot.sh
# Shots: tools/out/fp-osd.png, fp-launcher.png, fp-desktop.png
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/fp-daemon.log 2>&1 &
sleep 2.5
python3 -m swayctl_center set appearance.ui_style frame >/dev/null
[ -n "${FRAME:-}" ] && python3 -m swayctl_center set appearance.frame_color "$FRAME" >/dev/null
if [ -n "${GAP:-}" ]; then
  python3 -m swayctl_center set layout.gaps_inner "$GAP" >/dev/null
  python3 -m swayctl_center set layout.gaps_outer "$GAP" >/dev/null
fi
sleep 2.5
elephant >/tmp/out/fp-elephant.log 2>&1 &
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
gen="$HOME/.config/swayctl-center/generated/bar"
$bin --config-dir "$gen" 2>/tmp/out/fp-bar.log &
sleep 2
swaymsg exec "foot -o colors-dark.background=11141a sleep 600" >/dev/null; sleep 1.2
swaymsg exec "foot -o colors-dark.background=1d2a44 sleep 600" >/dev/null; sleep 2.5
grim /tmp/out/fp-desktop.png
$bin osd volume-up >/dev/null 2>&1 || true; sleep 0.8
grim /tmp/out/fp-osd.png
sleep 2.5
$bin launcher foot >/dev/null 2>&1 || true; sleep 2.5
grim /tmp/out/fp-launcher.png
grep -i "panic\|rejected" /tmp/out/fp-daemon.log /tmp/out/fp-bar.log | head -3

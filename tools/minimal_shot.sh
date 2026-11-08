#!/bin/sh
# the Modern Minimal style: bar, Quick Settings, OSD, notification, launcher, settings window
#   tools/sandbox.sh --sway /home/repo/tools/minimal_shot.sh
# Shots: tools/out/mm-*.png
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --sway" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/mm-daemon.log 2>&1 &
sleep 2.5
python3 -m swayctl_center set appearance.mode light >/dev/null
python3 -m swayctl_center set appearance.ui_style minimal >/dev/null
python3 -m swayctl_center set bar.position ${BAR_POS:-bottom} >/dev/null
sleep 2.5
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
gen="$HOME/.config/swayctl-center/generated/bar"
$bin --config-dir "$gen" 2>/tmp/out/mm-bar.log &
sleep 2
swaymsg exec "foot -o colors-light.background=dcdce0 sleep 600" >/dev/null; sleep 2
grim /tmp/out/mm-desktop.png
$bin quick >/dev/null 2>&1 || true; sleep 2
grim /tmp/out/mm-quick.png
$bin quick >/dev/null 2>&1 || true; sleep 1
$bin osd volume-up >/dev/null 2>&1 || true; sleep 0.8
grim /tmp/out/mm-osd.png
sleep 2.5
$bin launcher foot >/dev/null 2>&1 || true; sleep 2.5
grim /tmp/out/mm-launcher.png
sleep 1
$bin launcher foot >/dev/null 2>&1 || true; sleep 1
swaymsg kill >/dev/null 2>&1 || true
python3 -m swayctl_center ui > /tmp/out/mm-ui.log 2>&1 &
sleep 5
grim /tmp/out/mm-settings.png

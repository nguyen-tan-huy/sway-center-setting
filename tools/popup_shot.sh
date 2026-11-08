#!/bin/sh
# Quick Settings and a tray menu over a busy window (blur / position check):
#   SHAPE=single MODE=light GLASS=false tools/sandbox.sh --fx /home/repo/tools/popup_shot.sh
# Shots: tools/out/popup-quick.png, popup-tray.png
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/pp-daemon.log 2>&1 &
sleep 2.5
[ -f /tmp/out/lockwall.jpg ] && python3 -m swayctl_center set background.image /tmp/out/lockwall.jpg >/dev/null
python3 -m swayctl_center set bar.shape "${SHAPE:-single}" >/dev/null
python3 -m swayctl_center set appearance.mode "${MODE:-light}" >/dev/null
python3 -m swayctl_center set effects.glass "${GLASS:-false}" >/dev/null
python3 -m swayctl_center set effects.blur true >/dev/null
sleep 2
python3 tools/fake_tray.py >/tmp/out/pp-tray.log 2>&1 &
python3 -m swayctl_center ui --page desktop > /tmp/out/pp-ui.log 2>&1 &
sleep 3
swaymsg 'floating enable, resize set 1300 860, move position 600 0' >/dev/null 2>&1 || true
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
gen="$HOME/.config/swayctl-center/generated/bar"
$bin --config-dir "$gen" 2>/tmp/out/pp-bar.log &
sleep 2.5
$bin quick >/dev/null 2>&1 || true; sleep 1.5
grim -g "960,0 960x500" /tmp/out/popup-quick.png
$bin quick >/dev/null 2>&1 || true; sleep 0.8
$bin tray-menu 1 >/dev/null 2>&1 || true; sleep 1.5
grim -g "960,0 960x400" /tmp/out/popup-tray.png

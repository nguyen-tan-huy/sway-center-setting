#!/bin/sh
# Liquid glass only where it belongs: with glass on, the popups (Quick Settings, the volume pill, the launcher, notifications)
# are glass; the bar, a tray menu and every app window are not.
#   tools/sandbox.sh --fx /home/repo/tools/glass_scope_check.sh
set -u
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)" 2>/dev/null
python3 -m swayctl_center daemon >/tmp/out/gs-daemon.log 2>&1 &
sleep 2.5
python3 -m swayctl_center set effects.glass true >/dev/null
python3 -m swayctl_center set appearance.mode light >/dev/null 2>&1
sleep 2
swaymsg 'output * bg #6a4c93 solid_color' >/dev/null
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
GEN=$HOME/.config/swayctl-center/generated/bar
$bin --config-dir "$GEN" 2>/tmp/out/gs-bar.log & sleep 3
python3 -m swayctl_center ui --page desktop >/dev/null 2>&1 &
sleep 4
swaymsg 'floating enable, resize set 1000 700, move position 100 200' >/dev/null
sleep 1
notify-send -a Test "Notification" "A glass card" 2>/dev/null
$bin quick; sleep 1.5
grim /tmp/out/gs.png
swaymsg -t get_outputs | python3 -c "
import json,sys
for o in json.load(sys.stdin):
    for l in o.get('layer_shell_surfaces',[]):
        print('layer', l['namespace'])
" | sort -u

#!/bin/sh
# Walker in the Modern Minimal style: tools/sandbox.sh --sway /home/repo/tools/minimal_walker_shot.sh  (-> tools/out/mm-walker.png)
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --sway" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/mw-daemon.log 2>&1 &
sleep 2.5
python3 -m swayctl_center set appearance.mode light >/dev/null
python3 -m swayctl_center set appearance.ui_style minimal >/dev/null
sleep 2.5
gen="$HOME/.config/swayctl-center/generated/launcher"
swaymsg exec "foot -o colors-light.background=dcdce0 sleep 600" >/dev/null; sleep 1
elephant --config "$gen/elephant" >/tmp/out/mw-elephant.log 2>&1 &
sleep 2
XDG_CONFIG_HOME="$gen" walker --gapplication-service >/tmp/out/mw-walker.log 2>&1 &
sleep 3
XDG_CONFIG_HOME="$gen" walker >/dev/null 2>&1 &
sleep 2
wtype chr 2>/dev/null || true
sleep 2
grim /tmp/out/mm-walker.png

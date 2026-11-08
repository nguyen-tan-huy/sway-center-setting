#!/bin/sh
# `swayctl-bar launcher` started with no bar running (a key binding) must come up with the real settings
# (the right side, the clock format), not the built-in defaults:
#   tools/sandbox.sh --fx sh /home/repo/tools/bar_stray_test.sh      Shot: tools/out/stray-bar.png
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon >/tmp/out/st-daemon.log 2>&1 &
sleep 2.5
python3 -m swayctl_center set appearance.ui_style frame >/dev/null
python3 -m swayctl_center set appearance.frame_color '#ff2900' >/dev/null
sleep 2.5
/home/repo/swayctl-bar/target/release/swayctl-bar launcher >/dev/null 2>/tmp/out/st-bar.log &   # no --config-dir
sleep 3
grim -g "0,0 1920x60" /tmp/out/stray-bar.png

#!/bin/sh
# the Animations part of the Desktop page:   tools/sandbox.sh --fx /home/repo/tools/anim_ui_shot.sh
# Shot: tools/out/anim-ui.png
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon >/tmp/out/au-daemon.log 2>&1 &
sleep 2.5
python3 -m swayctl_center set appearance.ui_style frame >/dev/null; sleep 2
python3 -m swayctl_center ui --page desktop >/tmp/out/au-ui.log 2>&1 &
sleep 3.5
swaymsg 'floating enable, resize set 1100 1000, move position 400 40' >/dev/null 2>&1
sleep 1
grim /tmp/out/anim-ui.png

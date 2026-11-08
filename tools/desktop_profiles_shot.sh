#!/bin/sh
# The whole Desktop page, with its profile choices:   tools/sandbox.sh --fx /home/repo/tools/desktop_profiles_shot.sh
# Shot: tools/out/desktop-profiles.png
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
swaymsg 'output HEADLESS-1 resolution 1920x2400' >/dev/null
python3 -m swayctl_center daemon >/tmp/out/dp-daemon.log 2>&1 &
sleep 2.5
python3 -m swayctl_center set appearance.ui_style rounded >/dev/null; sleep 2
python3 -m swayctl_center ui --page desktop >/tmp/out/dp-ui.log 2>&1 &
sleep 3.5
swaymsg 'floating enable, resize set 1100 2300, move position 400 40' >/dev/null 2>&1
sleep 1
grim /tmp/out/desktop-profiles.png

#!/bin/sh
# bar.icon_style: iPadOS set and the system's, switched live
#   tools/sandbox.sh --fx sh /home/repo/tools/icon_style_test.sh      Shots: tools/out/icons-ipados.png, icons-system.png
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon >/tmp/out/is-daemon.log 2>&1 &
sleep 2.5
python3 -m swayctl_center set appearance.ui_style frame >/dev/null; sleep 2.5
/home/repo/swayctl-bar/target/release/swayctl-bar --config-dir "$HOME/.config/swayctl-center/generated/bar" 2>/tmp/out/is-bar.log &
sleep 2.5
grim -g "1700,0 220x36" /tmp/out/icons-ipados.png
python3 -m swayctl_center set bar.icon_style system >/dev/null; sleep 3
grim -g "1700,0 220x36" /tmp/out/icons-system.png
ls /run/sandbox | grep -c swayctl-bar-icons | sed 's/^/icon dirs written: /'

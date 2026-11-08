#!/bin/sh
# The tray menu next to its icon for a bar on every edge:
#   tools/sandbox.sh --fx sh /home/repo/tools/tray_position_shot.sh  -> tools/out/tp-<position>.png
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon >/tmp/out/tp-daemon.log 2>&1 &
sleep 2.5
[ -f /tmp/out/lockwall.jpg ] && python3 -m swayctl_center set background.image /tmp/out/lockwall.jpg >/dev/null
python3 tools/fake_tray.py >/tmp/out/tp-tray.log 2>&1 &
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir "$HOME/.config/swayctl-center/generated/bar" 2>/tmp/out/tp-bar.log &
sleep 2.5
for pos in ${POSITIONS:-top bottom left right}; do
  python3 -m swayctl_center set bar.position $pos >/dev/null
  sleep 3
  $bin ${CMD:-tray-menu 1} >/dev/null 2>&1; sleep 1.5
  grim -s 0.5 /tmp/out/tp-$pos.png
done

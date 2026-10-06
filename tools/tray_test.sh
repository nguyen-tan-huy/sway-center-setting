#!/bin/sh
# swayctl-bar's tray against a fake item: icon shows, left click activates,
# right click opens the dbusmenu, picking an entry sends Event.
#   tools/sandbox.sh --fx /home/repo/tools/tray_test.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh" >&2; exit 1 ;; esac
cd /tmp
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
mkdir -p bar
cat > bar/config.json <<'JSON'
{"modules_left": ["workspaces"], "modules_center": ["clock"], "modules_right": ["tray", "status"]}
JSON
$bin --config-dir /tmp/bar 2>/tmp/out/tray-bar.log &
sleep 2
: > /tmp/out/tray.log
python3 /home/repo/tools/fake_tray_item.py /tmp/out/tray.log &
sleep 1.5
grim -g "1500,0 420x40" /tmp/out/tray-bar.png
# the tray icon is the first thing in modules-right; find it from the screenshot run
x=${TRAY_X:-1795} y=17
/home/repo/tools/vptr/vptr click $x $y 272 &
sleep 1
/home/repo/tools/vptr/vptr click $x $y 273 &
sleep 1.2
grim -g "1500,0 420x200" /tmp/out/tray-menu.png
/home/repo/tools/vptr/vptr click ${QUIT_X:-1796} ${QUIT_Y:-137} 272 &
sleep 1.2
cat /tmp/out/tray.log

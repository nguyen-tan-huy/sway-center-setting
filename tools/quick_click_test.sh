#!/bin/sh
# Click the bar's status button with a window focused; Quick Settings must stay open.
#   tools/sandbox.sh --fx /home/repo/tools/quick_click_test.sh
set -eu
cd /tmp
mkdir -p bar
printf '{"modules_left":["workspaces"],"modules_center":["clock"],"modules_right":["status"],"margins":[8,8,0,8],"height":38}' > bar/config.json
: > bar/style.css
foot >/dev/null 2>&1 &
python3 /home/repo/tools/fake_mpris.py 2>/dev/null &
sleep 1
/home/repo/swayctl-bar/target/release/swayctl-bar --config-dir /tmp/bar 2>/tmp/out/qc.log &
sleep 2
layers() { swaymsg -t get_outputs | python3 -c "
import json,sys
print(' '.join(s.get('namespace') for s in json.load(sys.stdin)[0].get('layer_shell_surfaces',[])))"; }
v=/home/repo/tools/vptr/vptr
$v click ${X:-1880} 27 272 &
sleep 1
# focus_follows_mouse: crossing the window under the popup must not close it
$v move 1500 300 &
sleep 1
$v move 1600 100 &
sleep 1
echo "after moving over a window: $(layers)"
swaymsg -t get_outputs | python3 -c "
import json,sys
for l in json.load(sys.stdin)[0].get('layer_shell_surfaces',[]):
    if l['namespace']=='swayctl-quick': print('popup surface:', l['extent']['width'], 'x', l['extent']['height'])"
grim -g "1100,0 820x400" /tmp/out/quick-click.png
$v click 500 600 272 &
sleep 1
echo "after clicking outside:     $(layers)"
swaymsg -t get_outputs | python3 -c "import json,sys; [print(s) for s in json.load(sys.stdin)[0].get(\"layer_shell_surfaces\",[])]"

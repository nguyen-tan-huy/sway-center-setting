#!/bin/sh
# Quick Settings open: crossing and scrolling a window keeps it open (the
# window scrolls); a click on the window closes it once the scrolling is over.
#   tools/sandbox.sh --fx /home/repo/tools/quick_scroll_test.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp
mkdir -p bar
printf '{"modules_left":["workspaces"],"modules_center":["clock"],"modules_right":["status"],"height":38}' > bar/config.json
: > bar/style.css
swaymsg 'focus_follows_mouse always' >/dev/null
python3 /home/repo/tools/scroll_probe.py /tmp/probe.log > /dev/null 2>&1 &
sleep 1.5
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir /tmp/bar 2>/tmp/out/qs.log &
sleep 2
v=/home/repo/tools/vptr/vptr
layers() { swaymsg -t get_outputs | python3 -c "
import json,sys
print(' '.join(s.get('namespace') for s in json.load(sys.stdin)[0].get('layer_shell_surfaces',[])))"; }
$bin quick; sleep 1; swaymsg -t get_outputs | python3 -c "import json,sys; [print(l[\"namespace\"], l[\"layer\"], l[\"extent\"]) for l in json.load(sys.stdin)[0].get(\"layer_shell_surfaces\",[])]"
echo "open:              $(layers)"
$v move 1700 200 & sleep 0.5   # over the popup
$v move 600 600 & sleep 0.5    # across the window
echo "after crossing:    $(layers)"
: > /tmp/probe.log
$v wheel 3 80; sleep 1.5
echo "after scrolling:   $(layers)   (window got $(grep -c '"dy"' /tmp/probe.log) scroll events)"
sleep 2; $v move 650 600 & sleep 0.3; $v finger 30 6 10; sleep 1.5
echo "after touchpad:    $(layers)   (window got $(grep -c '"dy"' /tmp/probe.log) scroll events in all)"
sleep 2; $v click 650 600 272 & sleep 1
echo "after click:       $(layers)"
swaymsg -t get_tree | python3 -c "
import json,sys
def w(n):
    if n.get('pid'): print('win', n.get('app_id'), n['rect'], 'fs', n.get('fullscreen_mode'))
    for k in ('nodes','floating_nodes'): [w(c) for c in n.get(k,[])]
w(json.load(sys.stdin))"
swaymsg -t get_outputs | python3 -c "
import json,sys
for l in json.load(sys.stdin)[0].get('layer_shell_surfaces',[]): print(l['namespace'], l['layer'], l['extent'])"

#!/bin/sh
# Settings from the first frame: the daemon writes generated/startup.conf (pulled
# in by swayctl-fx.conf); a fresh swayctl-fx with no daemon starts with them.
#   tools/sandbox.sh --fx /home/repo/tools/startup_config_test.sh
set -eu
cd /home/repo
python3 -m swayctl_center daemon > /tmp/out/sc-daemon.log 2>&1 &
d=$!
sleep 2.5
python3 -m swayctl_center set layout.gaps_inner 17 >/dev/null
python3 -m swayctl_center set layout.border 5 >/dev/null
sleep 1.5
kill $d; sleep 0.5
echo "bar bar-0 mode invisible" >> $XDG_CONFIG_HOME/swayctl-center/generated/startup.conf  # what a managed bar writes (the first compositor has no stock bar to list)
g=$XDG_CONFIG_HOME/swayctl-center/generated
echo "startup.conf: $(wc -l < $g/startup.conf) lines"; grep -E "^(gaps|default_border)" $g/startup.conf; head -3 $g/swayctl-fx.conf
printf "\nbar {\n  position top\n}\n" >> /tmp/sway.conf
WLR_BACKENDS=headless WLR_RENDERER=gles2 WLR_LIBINPUT_NO_DEVICES=1 $SWAY_BIN -c /tmp/sway.conf >/tmp/out/sc-sway2.log 2>&1 &
sleep 1.5
s2=$(ls -t $XDG_RUNTIME_DIR/sway-ipc.* | head -1)
SWAYSOCK=$s2 swaymsg -t get_tree | python3 -c "
import json,sys
t=json.load(sys.stdin)
def walk(n):
    if n.get('type')=='workspace': print('workspace gaps:', n.get('gaps'))
    for c in n.get('nodes',[]): walk(c)
walk(t)"
grep -iE "error|invalid|unknown" /tmp/out/sc-sway2.log | head -5 || true
# the stock config's own bar (swaybar) comes up invisible, not for the daemon to hide
SWAYSOCK=$s2 swaymsg -t get_bar_config | head -3
for b in $(SWAYSOCK=$s2 swaymsg -t get_bar_config | python3 -c "import json,sys;print(*json.load(sys.stdin))"); do
  echo "$b mode: $(SWAYSOCK=$s2 swaymsg -t get_bar_config $b | python3 -c "import json,sys;print(json.load(sys.stdin)['mode'])")"
done

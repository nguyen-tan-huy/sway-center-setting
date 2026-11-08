#!/bin/sh
# scroll_page_keys: the compositor takes the command, the daemon sends the rule
# (the keys themselves need a real keyboard: try Page Down in Chrome)
#   tools/sandbox.sh --fx sh /home/repo/tools/page_keys_test.sh
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon >/tmp/out/pk-daemon.log 2>&1 &
sleep 2.5
echo "feature: $(swaymsg -t get_version | python3 -c "import json,sys;print('scroll-page-keys' in json.load(sys.stdin).get('swayctl_features',[]))")"
python3 -m swayctl_center ui --page pointing >/tmp/out/pk-ui.log 2>&1 &
sleep 3
echo "enable: $(swaymsg '[app_id="io.github.huyhappy.SwayctlCenter.Settings"] scroll_page_keys enable' | tr -d '\n ')"
echo "bad: $(swaymsg '[app_id="io.github.huyhappy.SwayctlCenter.Settings"] scroll_page_keys maybe' | tr -d '\n ')"
python3 -m swayctl_center set scrolling.page_keys false >/dev/null; sleep 1
grep -i "rejected\|error" /tmp/out/pk-daemon.log | head -3
echo "daemon rules ok"

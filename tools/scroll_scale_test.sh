#!/bin/sh
# scroll_scale: the daemon sends a rule for Chromium-based apps, the compositor takes it
#   tools/sandbox.sh --fx sh /home/repo/tools/scroll_scale_test.sh
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon >/tmp/out/ss2-daemon.log 2>&1 &
sleep 2.5
echo "feature: $(swaymsg -t get_version | python3 -c "import json,sys;print('scroll-scale' in json.load(sys.stdin).get('swayctl_features',[]))")"
python3 -m swayctl_center set scrolling.browser_scale 0.4 >/dev/null; sleep 1
python3 -m swayctl_center ui --page pointing >/tmp/out/ss2-ui.log 2>&1 &
sleep 3
echo "existing window: $(swaymsg '[app_id="io.github.huyhappy.SwayctlCenter.Settings"] scroll_scale 0.5' | tr -d '\n ')"
echo "bad value: $(swaymsg 'scroll_scale 0' | tr -d '\n ')"
grep -ci "scroll_scale" /tmp/out/ss2-daemon.log | sed 's/^/daemon log lines mentioning it: /'
grep -i "scroll_scale\|sway rejected" /tmp/out/ss2-daemon.log | head -3

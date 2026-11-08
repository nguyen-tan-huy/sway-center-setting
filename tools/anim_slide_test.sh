#!/bin/sh
# workspace switch: fade (upstream) against slide (animations workspace_slide enable)
#   tools/sandbox.sh --fx sh /home/repo/tools/anim_slide_test.sh
cd /home/repo
ok() { swaymsg "$1" | python3 -c "import json,sys;print(json.load(sys.stdin)[0].get('success'))"; }
echo "feature: $(swaymsg -t get_version | python3 -c "import json,sys;print('animation-slide' in json.load(sys.stdin).get('swayctl_features',[]))")"
echo "slide command accepted: $(ok 'animations workspace_slide enable')"
swaymsg animations workspace_slide disable >/dev/null
swaymsg animation_duration_ms 200 >/dev/null; swaymsg animation_curve spring >/dev/null; swaymsg animation_spring 340 0.1 >/dev/null
swaymsg gaps inner 0 >/dev/null; swaymsg gaps outer 0 >/dev/null; swaymsg default_border none >/dev/null; swaymsg corner_radius 0 >/dev/null
swaymsg workspace 1 >/dev/null
swaymsg exec "foot -o colors-dark.background=ff0000 sleep 600" >/dev/null; sleep 2
swaymsg workspace 2 >/dev/null; sleep 0.5
swaymsg exec "foot -o colors-dark.background=0000ff sleep 600" >/dev/null; sleep 2
swaymsg workspace 1 >/dev/null; sleep 1.5
run() {
  swaymsg "animations workspace_slide $1" >/dev/null
  swaymsg workspace 1 >/dev/null; sleep 1.2
  python3 tools/anim_probe_ws.py 1.2 >/tmp/out/slide-$1.txt &
  pp=$!
  sleep 0.12; swaymsg workspace 2 >/dev/null
  wait $pp
  echo "--- slide $1"; tail -1 /tmp/out/slide-$1.txt
}
run disable
run enable
echo "alive: $(swaymsg -t get_version >/dev/null 2>&1 && echo yes || echo NO)"

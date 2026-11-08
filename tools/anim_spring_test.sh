#!/bin/sh
# spring animations in the fork: commands, feature flag, and a pixel probe of a
# window shrinking while another opens (ease = no undershoot, spring+bounce = some)
#   tools/sandbox.sh --fx sh /home/repo/tools/anim_spring_test.sh
cd /home/repo
echo "feature: $(swaymsg -t get_version | python3 -c "import json,sys;print('animation-spring' in json.load(sys.stdin).get('swayctl_features',[]))")"
ok() { swaymsg "$1" | python3 -c "import json,sys;print(json.load(sys.stdin)[0].get('success'))"; }
rej() { [ "$(ok "$1")" = False ] && echo yes || echo NO; }
echo "curve bogus rejected:    $(rej 'animation_curve bogus')"
echo "response 10 rejected:    $(rej 'animation_spring 10')"
echo "bounce 2 rejected:       $(rej 'animation_spring 300 2')"
echo "spring 300 0.3 accepted: $(ok 'animation_spring 300 0.3')"
swaymsg animation_duration_ms 200 >/dev/null
swaymsg gaps inner 0 >/dev/null; swaymsg gaps outer 0 >/dev/null
swaymsg default_border none >/dev/null; swaymsg corner_radius 0 >/dev/null
swaymsg focus_follows_mouse no >/dev/null

run() {
  swaymsg "animation_curve $1" >/dev/null
  swaymsg '[app_id=foot] kill' >/dev/null 2>&1; sleep 1
  swaymsg exec "foot -o colors-dark.background=ff0000 sleep 600" >/dev/null; sleep 2
  python3 tools/anim_probe.py 1.2 >/tmp/out/anim-$1.txt &
  sleep 0.15
  swaymsg exec "foot -o colors-dark.background=0000ff sleep 600" >/dev/null
  wait
  echo "--- $1"; tail -1 /tmp/out/anim-$1.txt
}
run ease
run spring

# churn: open/close fast, the compositor must stay up and answer
swaymsg animation_curve spring >/dev/null
for i in 1 2 3 4 5 6; do
  swaymsg exec "foot sleep 600" >/dev/null; sleep 0.12
  swaymsg '[app_id=foot] focus; kill' >/dev/null 2>&1; sleep 0.08
done
sleep 1
echo "alive after churn: $(swaymsg -t get_version >/dev/null 2>&1 && echo yes || echo NO)"

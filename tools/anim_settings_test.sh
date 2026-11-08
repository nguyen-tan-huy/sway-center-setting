#!/bin/sh
# the daemon sends animation_curve / animation_spring to the fork, and the setting decides the motion
#   tools/sandbox.sh --fx sh /home/repo/tools/anim_settings_test.sh
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon >/tmp/out/as-daemon.log 2>&1 &
sleep 2.5
swaymsg gaps inner 0 >/dev/null; swaymsg gaps outer 0 >/dev/null; swaymsg default_border none >/dev/null; swaymsg corner_radius 0 >/dev/null
python3 -m swayctl_center set effects.animations true >/dev/null
probe() {
  python3 -m swayctl_center set effects.anim_curve "$1" >/dev/null; sleep 1
  swaymsg '[app_id=foot] kill' >/dev/null 2>&1; sleep 1
  swaymsg exec "foot -o colors-dark.background=ff0000 sleep 600" >/dev/null; sleep 2
  python3 tools/anim_probe.py 1.2 >/tmp/out/as-$1.txt &
  pp=$!
  sleep 0.15; swaymsg exec "foot -o colors-dark.background=0000ff sleep 600" >/dev/null; wait $pp
  echo "$1: $(tail -1 /tmp/out/as-$1.txt)"
}
probe ease
python3 -m swayctl_center set effects.anim_bounce 25 >/dev/null
probe spring
echo "daemon rejections: $(grep -ci 'sway rejected' /tmp/out/as-daemon.log)"
grep -i "sway rejected" /tmp/out/as-daemon.log | head -3

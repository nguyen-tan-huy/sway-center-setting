#!/bin/sh
# each animation has its own switch: windows opening/closing+moving, workspaces, Quick Settings
#   tools/sandbox.sh --fx sh /home/repo/tools/anim_switch_test.sh
# Windows: the red window's edge while another opens: with moving on it passes through the
# values in between, with it off it jumps. Shots for Quick Settings: tools/out/as2-*.png
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon >/tmp/out/as2-daemon.log 2>&1 &
sleep 2.5
sw() { python3 -m swayctl_center set "$1" "$2" >/dev/null; }
sw appearance.ui_style frame; sleep 1.5
swaymsg gaps inner 0 >/dev/null; swaymsg gaps outer 0 >/dev/null; swaymsg default_border none >/dev/null; swaymsg corner_radius 0 >/dev/null
for k in anim_open_close anim_move anim_workspace anim_quick; do sw effects.$k false; done
sleep 1

windows() {  # label: blue closes, the red window grows back; its right edge is what moves
  swaymsg '[app_id=foot] kill' >/dev/null 2>&1; sleep 1
  swaymsg exec "foot -o colors-dark.background=ff0000 sleep 600" >/dev/null; sleep 1.5
  swaymsg exec "foot -o colors-dark.background=0000ff sleep 600" >/dev/null; sleep 2.5
  python3 tools/anim_probe.py 1.2 >/tmp/out/as2-$1.txt &
  pp=$!
  sleep 0.2; swaymsg kill >/dev/null; wait $pp
  mid=$(awk '$2>970 && $2<1900 {n++} END {print n+0}' /tmp/out/as2-$1.txt)
  echo "windows $1: in-between samples = $mid"
}
workspaces() {  # label: ws 1 has red, ws 2 has blue; switch and watch the edges
  swaymsg '[app_id=foot] kill' >/dev/null 2>&1; sleep 1
  swaymsg workspace 1 >/dev/null; swaymsg exec "foot -o colors-dark.background=ff0000 sleep 600" >/dev/null; sleep 2
  swaymsg workspace 2 >/dev/null; sleep 0.5; swaymsg exec "foot -o colors-dark.background=0000ff sleep 600" >/dev/null; sleep 2
  swaymsg workspace 1 >/dev/null; sleep 1.5
  python3 tools/anim_probe_ws.py 1.2 >/tmp/out/as2-ws-$1.txt &
  pp=$!
  sleep 0.15; swaymsg workspace 2 >/dev/null; wait $pp
  mid=$(awk '{ if ($3+0>100 && $3+0<1800) n++ } END {print n+0}' /tmp/out/as2-ws-$1.txt)
  echo "workspace $1: in-between samples = $mid"
  swaymsg workspace 1 >/dev/null; sleep 1
}
quick() {  # label
  swaymsg '[app_id=foot] kill' >/dev/null 2>&1; sleep 1
  swaymsg exec "foot -o colors-dark.background=11141a sleep 600" >/dev/null; sleep 2
  grim -g "960,40 960x480" -t ppm /tmp/out/as2-qbase.ppm
  /home/repo/swayctl-bar/target/release/swayctl-bar quick >/dev/null 2>&1 &
  python3 tools/anim_probe_quick.py /tmp/out/as2-qbase.ppm 1.0 >/tmp/out/as2-q-$1.txt
  echo "quick $1: $(tail -1 /tmp/out/as2-q-$1.txt)"
  /home/repo/swayctl-bar/target/release/swayctl-bar quick >/dev/null 2>&1; sleep 1.5
}
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir "$HOME/.config/swayctl-center/generated/bar" 2>/tmp/out/as2-bar.log &
sleep 2

echo "== windows =="
windows all-off
sw effects.anim_move true; sleep 1.5; windows move-only
sw effects.anim_move false; sw effects.anim_open_close true; sleep 1.5; windows open_close-only
sw effects.anim_open_close false; sleep 1
echo "== workspaces =="
workspaces off
sw effects.anim_workspace true; sleep 1.5; workspaces on
sw effects.anim_workspace false; sleep 1
echo "== quick settings (the other three stay off) =="
quick off
sw effects.anim_quick true; sleep 2; quick on
echo "alive: $(swaymsg -t get_version >/dev/null 2>&1 && echo yes || echo NO)"

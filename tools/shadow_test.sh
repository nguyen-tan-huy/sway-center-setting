#!/bin/sh
# the window shadow switch: a strip of the frame colour next to a window is darker with it on
#   tools/sandbox.sh --fx sh /home/repo/tools/shadow_test.sh
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon >/tmp/out/sh-daemon.log 2>&1 &
sleep 2.5
sw() { python3 -m swayctl_center set "$1" "$2" >/dev/null; }
sw appearance.ui_style frame; sw appearance.frame_color '#e8ecf2'; sw layout.gaps_inner 28; sw layout.gaps_outer 28
sleep 2.5
swaymsg exec "foot -o colors-dark.background=11141a sleep 600" >/dev/null; sleep 2.5
strip() {  # darkness of the frame colour in the 2-8 px just outside the window's left edge
  grim -g "0,540 90x1" -t ppm /tmp/out/sh-$1.ppm
  python3 - "$1" <<'P'
import sys
d = open(f"/tmp/out/sh-{sys.argv[1]}.ppm", "rb").read().split(b"\n", 3)[3]
g = [round(sum(d[i:i + 3]) / 3) for i in range(0, len(d), 3)]
edge = next(i for i, v in enumerate(g) if v < 100)   # the window starts here
near = g[edge - 8:edge - 2]
print(f"{sys.argv[1]}: window edge x={edge}, frame beside it averages {sum(near) / len(near):.1f} (plain frame colour 236.7)")
P
}
sw effects.shadows false; sleep 1.5; strip off
sw effects.shadows true; sleep 1.5; strip on
sw effects.shadow_blur_radius 70; sleep 1.5; strip very-soft
sw effects.shadow_blur_radius 8; sleep 1.5; strip tight

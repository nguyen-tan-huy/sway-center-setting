#!/bin/sh
# GPU cost of the glass desk with a real video playing under the frame (an MJPEG copy: the sandbox has no mp4
# demuxer), two windows covering most of the screen. Phases change only the glass knobs.
#   tools/sandbox.sh --fx /home/repo/tools/video_glass_cost_probe.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
swaymsg 'output HEADLESS-1 mode 3072x1920; output HEADLESS-1 scale 2' >/dev/null
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/vg-daemon.log 2>&1 &
sleep 2.5
sw() { python3 -m swayctl_center set "$1" "$2" >/dev/null; }
sw effects.glass true
sw appearance.ui_style glass; sleep 3
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
python3 - <<'PY'
import json, os
p = os.path.expanduser("~/.config/swayctl-center/generated/bar/config.json")
d = json.load(open(p)); d["wallpaper"] = {"video": "/tmp/out/mesh.avi"}; json.dump(d, open(p, "w"))
PY
$bin --config-dir "$HOME/.config/swayctl-center/generated/bar" 2>/dev/null &
barpid=$!
sleep 2
foot sleep 600 >/dev/null 2>&1 & sleep 0.6; foot sleep 600 >/dev/null 2>&1 & sleep 2
gpu() { cat /sys/class/drm/card1/device/gpu_busy_percent 2>/dev/null || echo 0; }
measure() {
  s=0; n=0
  for i in 1 2 3 4 5 6 7 8; do s=$((s+$(gpu))); n=$((n+1)); sleep 0.75; done
  python3 - "$1" "$((s/n))" <<'PY'
import subprocess, sys, time, statistics
ts = []
for _ in range(12):
    t = time.perf_counter(); subprocess.run(["grim", "-t", "ppm", "-"], stdout=subprocess.DEVNULL); ts.append((time.perf_counter() - t) * 1000)
ts = ts[2:]
print(f"{sys.argv[1]:<44} GPU {sys.argv[2]:>3}%   grim median {statistics.median(ts):5.1f} ms")
PY
}
knobs() { for kv in "$@"; do sw "effects.${kv%%=*}" "${kv#*=}"; done; sleep 3; }
for round in 1 2; do
knobs glass_refraction=140 glass_blur=25 glass_edge=180 glass_thickness=0 glass_chroma=0.0 glass_highlight=0.9
measure "user's glass: refr 140 edge 180 (round $round)"
knobs glass_refraction=40 glass_edge=60
measure "refr 40 edge 60 (round $round)"
knobs glass_refraction=15 glass_edge=20
measure "refr 15 edge 20 (round $round)"
knobs glass_refraction=0 glass_highlight=0
measure "no glass (round $round)"
done

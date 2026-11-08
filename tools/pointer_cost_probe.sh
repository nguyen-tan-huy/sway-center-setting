#!/bin/sh
# What does a pointer-sized change cost a frame, with the bar/frame as glass? (sandbox, the real mode)
# A tiny window repaints ~120x/s (what a software cursor or a blinking caret does); grim round-trips wait
# for a fresh frame, so their duration tracks frame time - an A/B proxy, as in fps_probe.sh.
#   tools/sandbox.sh --fx /home/repo/tools/pointer_cost_probe.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
trap 'cp /tmp/sway.log /tmp/out/pc-sway.log 2>/dev/null || true' EXIT
swaymsg 'output HEADLESS-1 mode 3072x1920; output HEADLESS-1 scale 2' >/dev/null
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/pc-daemon.log 2>&1 &
sleep 2.5
sw() { python3 -m swayctl_center set "$1" "$2" >/dev/null; }
swaymsg 'output * bg /tmp/out/mesh_t4.png fill' >/dev/null
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
# the user's own glass knobs
sw effects.glass true
for kv in glass_refraction=${REFR:-140} glass_blur=${BLUR:-25} glass_edge=${EDGE:-180} glass_thickness=0 glass_chroma=0.0 glass_highlight=0.9; do sw "effects.${kv%%=*}" "${kv#*=}"; done
# a tiny repainting window (~ a cursor): 12x2 cells
swaymsg 'for_window [app_id="tick"] floating enable' >/dev/null || true
foot -a tick -W 14x1 -e sh -c 'while :; do printf "\r%s" "$(date +%N)"; sleep 0.004; done' >/dev/null 2>&1 &
sleep 1
measure() {
  python3 - "$1" <<'PY'
import subprocess, sys, time, statistics
ts = []
for _ in range(25):
    t = time.perf_counter()
    subprocess.run(["grim", "-t", "ppm", "-"], stdout=subprocess.DEVNULL)
    ts.append((time.perf_counter() - t) * 1000)
ts = ts[3:]
print(f"{sys.argv[1]:<46} grim round trip: median {statistics.median(ts):6.1f} ms  min {min(ts):6.1f}  max {max(ts):6.1f}")
PY
}
phase() { # name style
  sw appearance.ui_style "$2"; sleep 3
  pkill -f "swayctl-bar --config-dir" 2>/dev/null || true; sleep 0.5
  $bin --config-dir "$HOME/.config/swayctl-center/generated/bar" 2>/dev/null &
  sleep 3
  measure "$1"
}
phase "liquid (bar is glass, no full-screen pane)" liquid
phase "glass desk (full-screen glass frame)" glass
sw effects.glass_blur 0; sleep 3
measure "glass desk, blur 0 (clear glass)"
sw effects.glass_refraction 0; sw effects.glass_highlight 0; sleep 3
measure "glass desk, blur 0 refraction 0 highlight 0"
sw effects.glass_blur 25; sw effects.glass_refraction 140; sw effects.glass_highlight 0.9; sleep 3
sw appearance.ui_style frame; sleep 3
pkill -f "swayctl-bar --config-dir" 2>/dev/null || true; sleep 0.5
$bin --config-dir "$HOME/.config/swayctl-center/generated/bar" 2>/dev/null &
sleep 3
measure "frame (solid, no glass at all)"

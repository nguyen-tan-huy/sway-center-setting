#!/bin/sh
# Which parts of the screen are redrawn when only a tiny window repaints? (WLR_SCENE_DEBUG_DAMAGE=highlight tints
# every region the compositor re-rendered for a frame; run through the sandbox with that variable set.)
#   WLR_SCENE_DEBUG_DAMAGE=highlight tools/sandbox.sh --fx /home/repo/tools/damage_debug_shot.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
swaymsg 'output HEADLESS-1 mode 3072x1920; output HEADLESS-1 scale 2' >/dev/null
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/dd-daemon.log 2>&1 &
sleep 2.5
sw() { python3 -m swayctl_center set "$1" "$2" >/dev/null; }
swaymsg 'output * bg /tmp/out/mesh_t4.png fill' >/dev/null
sw effects.glass true
for kv in glass_refraction=${REFR:-140} glass_blur=${BLUR:-25} glass_edge=${EDGE:-180} glass_thickness=0 glass_chroma=0.0 glass_highlight=0.9; do sw "effects.${kv%%=*}" "${kv#*=}"; done
sw appearance.ui_style "${STYLE:-glass}"; sleep 3
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
if [ -n "${NOVIDEO:-}" ]; then   # the same glass desk without the video window
  python3 - <<'PY'
import json, os
p = os.path.expanduser("~/.config/swayctl-center/generated/bar/config.json")
d = json.load(open(p)); d["wallpaper"] = {"video": ""}; json.dump(d, open(p, "w"))
PY
fi
$bin --config-dir "$HOME/.config/swayctl-center/generated/bar" 2>/dev/null &
sleep 3
swaymsg 'for_window [app_id="tick"] floating enable' >/dev/null || true
foot -a tick -W 14x1 -e sh -c 'while :; do printf "\r%s" "$(date +%N)"; sleep 0.004; done' >/dev/null 2>&1 &
sleep 2
grim /tmp/out/dd-${TAG:-${STYLE:-glass}}.png

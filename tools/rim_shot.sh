#!/bin/sh
# Quick Settings over stripes and text: how does the glass bend its rims?   tools/sandbox.sh --fx /home/repo/tools/rim_shot.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
swaymsg 'output HEADLESS-1 mode 3072x1920; output HEADLESS-1 scale 2' >/dev/null
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/rim-daemon.log 2>&1 &
sleep 2.5
sw() { python3 -m swayctl_center set "$1" "$2" >/dev/null; }
sw background.image /tmp/out/${WALL:-rim_wall.png}
sw effects.glass true; sw appearance.ui_style liquid
for kv in glass_refraction=${REFR:-140} glass_blur=${BLUR:-0} glass_edge=${EDGE:-180} glass_thickness=${THICK:-0} glass_chroma=0.0 glass_highlight=${HIGHLIGHT:-0.9}; do sw "effects.${kv%%=*}" "${kv#*=}"; done
[ -n "${NOSHADOW:-}" ] && sw effects.shadows false
sleep 4
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir "$HOME/.config/swayctl-center/generated/bar" 2>/dev/null &
sleep 2
swaymsg 'for_window [app_id="bgchurn"] floating enable' >/dev/null || true
$bin quick; sleep 2.5
grim -g "1100,30 430x420" /tmp/out/rim-${TAG:-user}.png

#!/bin/sh
# Streaks / colour bleeding at the rim of glass panes over a backdrop that changes every frame.
#   [CACHE=0] tools/sandbox.sh --fx /home/repo/tools/glass_motion_check.sh   -> tools/out/gm-<cache>.png
set -u
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo
swaymsg 'output HEADLESS-1 mode 3072x1920@120Hz; output HEADLESS-1 scale 2' >/dev/null   # the real panel: 3K, scale 2
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)" 2>/dev/null
python3 -m swayctl_center daemon >/tmp/out/gm-daemon.log 2>&1 &
sleep 2.5
python3 -m swayctl_center set effects.glass true >/dev/null
for kv in ${GLASS_SETTINGS:-"glass_refraction=140 glass_edge=180 glass_blur=25 glass_chroma=0 glass_thickness=0 glass_highlight=0.9 panels=true blur=true"}; do
  python3 -m swayctl_center set effects.${kv%%=*} ${kv#*=} >/dev/null
done
sleep 2
python3 /home/repo/tools/glass_motion_backdrop.py ${BLOCKS:-60} ${BLOCK_SIZE:-0.2} ${STOP:-0} >/dev/null 2>&1 &
sleep 2.5
swaymsg '[app_id=local.motion] floating enable, resize set 1536 900, move position 0 30' >/dev/null
sleep 1
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir $HOME/.config/swayctl-center/generated/bar 2>/dev/null & sleep 3
$bin quick; sleep ${SETTLE:-1.5}
grim -g "1100,0 436x340" /tmp/out/gm-${CACHE:-1}.png

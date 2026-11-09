#!/bin/sh
# The alpha of Quick Settings' surface: with its glass off, shoot it over white and over black;
# alpha = 1 - (white - black) / 255. Anything that is not 0 outside the capsules is read by the glass as a pane.
#   tools/sandbox.sh --fx /home/repo/tools/quick_alpha_shot.sh   -> tools/out/qa-white.png, qa-black.png
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
swaymsg 'output HEADLESS-1 mode 3072x1920; output HEADLESS-1 scale 2' >/dev/null
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/qa-daemon.log 2>&1 &
sleep 2.5
sw() { python3 -m swayctl_center set "$1" "$2" >/dev/null; }
sw effects.glass true; sw appearance.ui_style liquid
for kv in glass_refraction=50 glass_blur=0 glass_edge=100 glass_thickness=90 glass_chroma=0.35 glass_highlight=0.9; do sw "effects.${kv%%=*}" "${kv#*=}"; done
sw background.color "#ffffff"; sleep 4
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir "$HOME/.config/swayctl-center/generated/bar" 2>/dev/null &
sleep 2
$bin quick; sleep 2.5
for ns in swayctl-quick swayctl-quick-catcher; do swaymsg layer_effects "$ns" "glass disable" >/dev/null || true; swaymsg layer_effects "$ns" "blur disable" >/dev/null || true; swaymsg layer_effects "$ns" "shadows disable" >/dev/null || true; done
sleep 1
grim -g "1090,20 450x440" /tmp/out/qa-white.png
sw background.color "#000000"; sleep 2.5
grim -g "1090,20 450x440" /tmp/out/qa-black.png

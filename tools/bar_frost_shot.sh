#!/bin/sh
# Liquid glass bar + Quick Settings at frost 0 / 80 (effects.glass_blur), tint 0:
#   tools/sandbox.sh --fx /home/repo/tools/bar_frost_shot.sh   -> tools/out/frost-<n>-quick.png
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/fr-daemon.log 2>&1 &
sleep 2.5
[ -f /tmp/out/lockwall.jpg ] && python3 -m swayctl_center set background.image /tmp/out/lockwall.jpg >/dev/null
python3 tools/fake_tray.py >/tmp/out/fr-tray.log 2>&1 &
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
gen="$HOME/.config/swayctl-center/generated/bar"
python3 -m swayctl_center set effects.glass true >/dev/null
python3 -m swayctl_center set effects.glass_opacity 0 >/dev/null
for n in 0 80; do
  python3 -m swayctl_center set effects.glass_blur $n >/dev/null
  sleep 2
  $bin --config-dir "$gen" 2>/tmp/out/fr-bar.log &
  b=$!; sleep 2.5
  $bin quick >/dev/null 2>&1 || true; sleep 1.5
  grim -g "960,0 960x300" "/tmp/out/frost-$n-quick.png"
  kill $b; sleep 0.6
done
swaymsg -t get_outputs >/dev/null

#!/bin/sh
# bar.padding at a few values (SHAPE=pieces|single): tools/out/bar-<shape>-<n>.png
#   tools/sandbox.sh --fx /home/repo/tools/bar_padding_shot.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/bp-daemon.log 2>&1 &
sleep 2.5
python3 -m swayctl_center set effects.glass true >/dev/null
[ -f /tmp/out/lockwall.jpg ] && python3 -m swayctl_center set background.image /tmp/out/lockwall.jpg >/dev/null
python3 -m swayctl_center set bar.shape "${SHAPE:-pieces}" >/dev/null
python3 tools/fake_tray.py >/tmp/out/bp-tray.log 2>&1 &
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
gen="$HOME/.config/swayctl-center/generated/bar"
for n in ${PADS:-2 10 18}; do
  python3 -m swayctl_center set bar.padding "$n" >/dev/null
  sleep 1
  $bin --config-dir "$gen" 2>/tmp/out/bp-bar.log &
  b=$!
  sleep 2.5
  grim -g "0,0 1920x60" "/tmp/out/bar-${SHAPE:-pieces}-$n.png"
  kill $b; sleep 0.5
done

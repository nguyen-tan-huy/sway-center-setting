#!/bin/sh
# Quick Settings opening as frames (the drop spreading out of the status button), then closing
# part-way through the opening (it must carry on from where it is):
#   tools/sandbox.sh --fx /home/repo/tools/quick_open_frames.sh
# Shots: tools/out/qo-open-N.png, qo-interrupt-N.png (tools/sheet.py makes a contact sheet; PIL is on the host, not in the sandbox)
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/qo-daemon.log 2>&1 &
sleep 2.5
[ -f /tmp/out/lockwall.jpg ] && python3 -m swayctl_center set background.image /tmp/out/lockwall.jpg >/dev/null
python3 -m swayctl_center set appearance.mode light >/dev/null
sleep 2
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
gen="$HOME/.config/swayctl-center/generated/bar"
$bin --config-dir "$gen" 2>/tmp/out/qo-bar.log &
sleep 2.5
frames() {  # name count
  i=0; while [ $i -lt "$2" ]; do grim -g "960,0 960x520" "/tmp/out/qo-$1-$i.png"; i=$((i+1)); done
}
$bin quick >/dev/null 2>&1 &
frames open 10
sleep 1
$bin quick >/dev/null 2>&1; sleep 1.2   # close it
$bin quick >/dev/null 2>&1 &            # open, and close again 120 ms in
sleep 0.12; $bin quick >/dev/null 2>&1 &
frames interrupt 8
sleep 1
grim -g "960,0 960x520" /tmp/out/qo-after.png
grep -i "panic\|error" /tmp/out/qo-bar.log | head -3

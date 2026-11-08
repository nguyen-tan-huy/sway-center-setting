#!/bin/sh
# Every interface style (flat / floating / rounded): bar, two tiled windows,
# Quick Settings, OSD, tray menu. MODE=light|dark GLASS=false|true
#   MODE=light GLASS=false tools/sandbox.sh --fx /home/repo/tools/ui_style_shot.sh
# Shots: tools/out/uis-<style>-{screen,quick,osd,tray}.png
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/uis-daemon.log 2>&1 &
sleep 2.5
[ -f "${WALLFILE:-/tmp/out/lockwall.jpg}" ] && python3 -m swayctl_center set background.image "${WALLFILE:-/tmp/out/lockwall.jpg}" >/dev/null
python3 -m swayctl_center set appearance.mode "${MODE:-light}" >/dev/null
python3 -m swayctl_center set effects.glass "${GLASS:-false}" >/dev/null
python3 -m swayctl_center set effects.blur true >/dev/null
python3 tools/fake_tray.py >/tmp/out/uis-tray.log 2>&1 &
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
gen="$HOME/.config/swayctl-center/generated/bar"
python3 -m swayctl_center ui --page desktop > /tmp/out/uis-ui1.log 2>&1 &
sleep 2
python3 -m swayctl_center ui --page notifications > /tmp/out/uis-ui2.log 2>&1 &
sleep 2
$bin --config-dir "$gen" 2>/tmp/out/uis-bar.log &
b=$!
sleep 2.5
for st in ${STYLES:-flat rounded liquid}; do
  python3 -m swayctl_center set appearance.ui_style $st >/dev/null
  sleep 3
  grim -s 0.5 /tmp/out/uis-$st-screen.png
  echo "$st: $(swaymsg -t get_outputs | python3 -c "import json,sys;print([l['extent'] for o in json.load(sys.stdin) for l in o.get('layer_shell_surfaces',[]) if l['namespace']=='swayctl-bar'])")" >> /tmp/out/uis-extent.log
  $bin quick >/dev/null 2>&1 || true; sleep 1.5
  grim -g "960,0 960x420" /tmp/out/uis-$st-quick.png
  $bin quick >/dev/null 2>&1 || true; sleep 0.8
  $bin osd volume-up >/dev/null 2>&1 || true; sleep 0.9
  grim -g "700,910 520x110" /tmp/out/uis-$st-osd.png
done
# tray menus last (a menu stays open until clicked away: it would ghost into the other shots)
for st in ${STYLES:-flat rounded liquid}; do
  python3 -m swayctl_center set appearance.ui_style $st >/dev/null
  sleep 3
  $bin tray-menu 1 >/dev/null 2>&1 || true; sleep 1.2
  grim -g "960,0 960x330" /tmp/out/uis-$st-tray.png
done
kill $b 2>/dev/null || true

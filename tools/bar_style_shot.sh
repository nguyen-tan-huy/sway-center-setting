#!/bin/sh
# The bar and Quick Settings in light/dark, with and without glass:
#   tools/sandbox.sh --fx /home/repo/tools/bar_style_shot.sh
# Shots: tools/out/style-<light|dark>-<plain|glass>-{bar,quick}.png
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/ss-daemon.log 2>&1 &
sleep 2.5
[ -f "${WALLFILE:-/tmp/out/lockwall.jpg}" ] && python3 -m swayctl_center set background.image "${WALLFILE:-/tmp/out/lockwall.jpg}" >/dev/null
python3 -m swayctl_center set bar.shape "${SHAPE:-pieces}" >/dev/null
python3 -m swayctl_center set effects.glass_opacity "${TINT:-10}" >/dev/null
python3 tools/fake_tray.py >/tmp/out/ss-tray.log 2>&1 &
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
gen="$HOME/.config/swayctl-center/generated/bar"
for mode in light dark; do
  for glass in false true; do
    python3 -m swayctl_center set appearance.mode $mode >/dev/null
    python3 -m swayctl_center set effects.glass $glass >/dev/null
    sleep 2.5; grep -m1 -c "" "$gen/style.css" >/dev/null; echo "$mode $glass: $(grep -m3 -o "\-\-[a-z-]*bg[a-z-]*: [^;]*" $gen/style.css | head -2 | tr "\n" " ")" >> /tmp/out/ss-theme.log
    $bin --config-dir "$gen" 2>/tmp/out/ss-bar.log &
    b=$!
    sleep 2.5
    tag=$mode-$([ $glass = true ] && echo glass || echo plain)
    grim -g "0,0 1920x60" "/tmp/out/style-$tag-bar.png"
    $bin quick >/dev/null 2>&1 || true
    sleep 1.5
    grim -g "960,0 960x720" "/tmp/out/style-$tag-quick.png"
    $bin quick >/dev/null 2>&1 || true; sleep 0.8
    $bin launcher >/dev/null 2>&1 || true; sleep 1.5
    grim -g "560,150 800x520" "/tmp/out/style-$tag-launcher.png"
    $bin launcher >/dev/null 2>&1 || true; sleep 0.5
    $bin osd volume-up >/dev/null 2>&1 || true; sleep 1
    grim "/tmp/out/style-$tag-osd.png"
    kill $b; sleep 0.6
  done
done

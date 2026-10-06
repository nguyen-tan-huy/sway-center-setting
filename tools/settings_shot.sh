#!/bin/sh
# Screenshots of settings pages with the real daemon (swayctl-fx):
#   tools/sandbox.sh --fx /home/repo/tools/settings_shot.sh notifications desktop pointing
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/settings-daemon.log 2>&1 &
sleep 2.5
if [ "${GLASS:-0}" = 1 ]; then
  python3 -m swayctl_center set effects.glass true >/dev/null
  python3 -m swayctl_center set appearance.mode "${THEME:-dark}" >/dev/null
  [ "${SHADOWS:-0}" = 1 ] && python3 -m swayctl_center set effects.shadows true >/dev/null
  [ -n "${TINT:-}" ] && python3 -m swayctl_center set effects.glass_opacity "$TINT" >/dev/null
  [ -n "${FROST:-}" ] && python3 -m swayctl_center set effects.glass_blur "$FROST" >/dev/null
  [ -n "${REFR:-}" ] && python3 -m swayctl_center set effects.glass_refraction "$REFR" >/dev/null
  wall=/tmp/out/${WALL:-wall-text}.png
  # through the daemon, so the app knows what's behind it too
  [ -f "$wall" ] && python3 -m swayctl_center set background.image "$wall" >/dev/null
  sleep 1
fi
for page in "$@"; do
  python3 -m swayctl_center ui --page "$page" > "/tmp/out/settings-$page.log" 2>&1 &
  ui=$!
  sleep 3
  # floating over the wallpaper: the glass needs something behind it
  swaymsg 'floating enable, resize set 1300 860, move position center' > /dev/null 2>&1 || true
  sleep 0.8
  grim "/tmp/out/settings-$page${GLASS:+-glass}-${THEME:-dark}.png"
  kill $ui; sleep 0.5
done

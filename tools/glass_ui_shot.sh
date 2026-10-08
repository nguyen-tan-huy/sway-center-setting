#!/bin/sh
# The launcher and swayctl-center's settings window with the user's own
# liquid glass config (a copy of ~/.config/swayctl-center/generated), over a
# busy wallpaper:
#   rm -rf tools/out/gen; cp -r ~/.config/swayctl-center/generated tools/out/gen
#   tools/sandbox.sh --fx /home/repo/tools/glass_ui_shot.sh
# Shots: tools/out/ui-launcher.png, ui-traymenu.png, ui-traymenu-sub.png, ui-settings.png
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
trap 'cp /tmp/sway.log /tmp/out/ui-sway.log 2>/dev/null || true' EXIT
cd /tmp
swaymsg 'output HEADLESS-1 mode 3072x1920; output HEADLESS-1 scale 2' >/dev/null
python3 - <<'PY'
import cairo, math
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 3072, 1920)
c = cairo.Context(s)
g = cairo.LinearGradient(0, 0, 3072, 1920)
g.add_color_stop_rgb(0, 0.93, 0.16, 0.42); g.add_color_stop_rgb(0.5, 0.98, 0.70, 0.15); g.add_color_stop_rgb(1, 0.10, 0.45, 0.95)
c.set_source(g); c.paint()
import os
if os.environ.get("WALL") == "dark":
    c.set_source_rgb(0.07, 0.08, 0.16); c.paint()
s.write_to_png("/tmp/wall.png")
PY
swaymsg 'output * bg /tmp/wall.png fill' >/dev/null
# the user's effects, one command per line
# (the tray menu takes Quick Settings' glass, as a regenerated config gives it)
{ cat /tmp/out/gen/swayctl-fx.conf; grep '"swayctl-quick"' /tmp/out/gen/swayctl-fx.conf | sed 's/"swayctl-quick"/"swayctl-traymenu"/'; echo 'layer_effects "swayctl-launcher" "glass_text auto"'; } \
  | grep -v '^\s*#' | grep -v '^\s*$' | while IFS= read -r l; do swaymsg -- "$l" >/dev/null 2>&1 || true; done
mkdir -p "$HOME/.config/swayctl-center"
cp /tmp/out/settings.json "$HOME/.config/swayctl-center/settings.json" 2>/dev/null || true
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir /tmp/out/gen/bar 2>/tmp/out/ui-bar.log &
sleep 2
python3 /home/repo/tools/fake_tray.py >/tmp/out/ui-tray.log 2>&1 &
sleep 2
$bin tray-menu 1
sleep 1.5
grim /tmp/out/ui-traymenu.png
$bin tray-menu 1   # opens again (a new one replaces it)
sleep 1
$bin launcher
sleep 2.5
grim /tmp/out/ui-launcher.png
$bin launcher   # toggles it away
sleep 1
cd /home/repo && python3 -m swayctl_center >/tmp/out/ui-settings.log 2>&1 &
sleep 6
grim /tmp/out/ui-settings.png
echo done

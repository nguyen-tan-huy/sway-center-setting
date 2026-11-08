#!/bin/sh
# The OSD with the user's own liquid glass config over a busy backdrop: the glass must show what is
# behind it, never the OSD's own bar (compositor culling bug: tools/out/osd-glass.png).
#   rm -rf tools/out/gen; cp -r ~/.config/swayctl-center/generated tools/out/gen
#   tools/sandbox.sh --fx /home/repo/tools/osd_glass_check.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp
swaymsg 'output HEADLESS-1 mode 3072x1920; output HEADLESS-1 scale 2' >/dev/null
python3 - <<'PY'
import cairo
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 3072, 1920)
c = cairo.Context(s)
g = cairo.LinearGradient(0, 0, 3072, 1920)
g.add_color_stop_rgb(0, 0.93, 0.16, 0.42); g.add_color_stop_rgb(0.5, 0.98, 0.70, 0.15); g.add_color_stop_rgb(1, 0.10, 0.45, 0.95)
c.set_source(g); c.paint(); s.write_to_png("/tmp/wall.png")
PY
swaymsg 'output * bg /tmp/wall.png fill' >/dev/null
grep -v '^\s*#' /tmp/out/gen/swayctl-fx.conf | grep -v '^\s*$' | while IFS= read -r l; do swaymsg -- "$l" >/dev/null 2>&1 || true; done
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir /tmp/out/gen/bar 2>/tmp/out/osd-bar.log &
sleep 2
$bin osd volume-up; sleep 0.8
grim /tmp/out/osd-glass.png
$bin osd brightness-up; sleep 0.8
grim /tmp/out/osd-glass-brightness.png
echo done

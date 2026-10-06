#!/bin/sh
# OSD (volume/brightness) over a busy wallpaper, glass off and on, to judge
# the macOS-style milky pill + accent bar.
#   tools/sandbox.sh --fx /home/repo/tools/osd_shot.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp
python3 - <<'PY'
import cairo, math
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 1920, 1080)
c = cairo.Context(s)
g = cairo.LinearGradient(0, 0, 1920, 1080)
g.add_color_stop_rgb(0, 0.10, 0.20, 0.55); g.add_color_stop_rgb(0.5, 0.75, 0.25, 0.55); g.add_color_stop_rgb(1, 0.98, 0.65, 0.20)
c.set_source(g); c.paint()
for i in range(40):
    c.set_source_rgba(1, 1, 1, 0.18 if i % 2 else 0.05)
    c.rectangle(i * 48, 0, 20, 1080); c.fill()
for x, y, r, col in ((1650, 160, 140, (0.2, 0.9, 0.6)), (300, 60, 90, (1, 0.9, 0.2)), (1200, 330, 110, (0.3, 0.6, 1))):
    c.set_source_rgb(*col); c.arc(x, y, r, 0, 2 * math.pi); c.fill()
c.select_font_face("Sans", 0, 1); c.set_font_size(54); c.set_source_rgb(1, 1, 1)
c.move_to(400, 200); c.show_text("brightness / volume OSD")
s.write_to_png("/tmp/wall.png")
PY
swaymsg 'output * bg /tmp/wall.png fill' >/dev/null
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
mkdir -p bar
printf '%s\n' '{"modules_left": ["workspaces"], "modules_center": ["clock"], "modules_right": ["status"], "margins": [8, 8, 0, 8], "height": 38}' > bar/config.json
# generated CSS: milky OSD pill (glass on/off both go through style.css)
python3 - <<'PY'
import sys; sys.path.insert(0, "/home/repo")
from pathlib import Path
from swayctl_center import schema, themes
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule
for glass in (False, True):
    v = schema.defaults(); v["appearance"]["style"] = "modern"; v["effects"]["glass"] = glass
    v["effects"]["glass_opacity"] = 50
    ctx = Context(Path("/tmp/app"), values=v, theme=themes.BUILTIN["dark"])
    css = BarModule().native_css(ctx, ctx.theme)
    Path(f"/tmp/style-{'glass' if glass else 'plain'}.css").write_text(css)
PY
for mode in plain glass; do
  cp /tmp/style-$mode.css bar/style.css
  $bin --config-dir /tmp/bar >/tmp/out/osd-bar.log 2>&1 &
  pid=$!
  sleep 1.2
  if [ $mode = glass ]; then
    swaymsg 'blur_saturation 1.4; blur_brightness 1.08; blur_passes 2; blur_radius 2' >/dev/null
    swaymsg layer_effects swayctl-osd "blur enable" "blur_ignore_transparent disable" "shadows enable" \
      "corner_radius 999" "glass enable" "glass_refraction 48" "glass_blur 40" >/dev/null
  else
    swaymsg layer_effects swayctl-osd "reset" >/dev/null
  fi
  $bin osd brightness-up
  sleep 0.45
  grim -g "480,860 960x160" /tmp/out/osd-$mode.png
  $bin osd volume-up
  sleep 0.45
  grim -g "480,860 960x160" /tmp/out/osd-$mode-volume.png
  kill $pid; sleep 0.4
done
echo done

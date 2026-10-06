#!/bin/sh
# Bar + calendar (click the clock) + Quick Settings, glass on, light and dark.
#   tools/sandbox.sh --fx /home/repo/tools/calendar_shot.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
v=/home/repo/tools/vptr/vptr
for theme in light dark; do
python3 - "$theme" <<'PY'
import sys, json, pathlib, cairo, math
sys.path.insert(0, "/home/repo")
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 1920, 1080); c = cairo.Context(s)
g = cairo.LinearGradient(0, 0, 1920, 1080)
g.add_color_stop_rgb(0, 0.10, 0.20, 0.55); g.add_color_stop_rgb(0.5, 0.75, 0.25, 0.55); g.add_color_stop_rgb(1, 0.98, 0.65, 0.20)
c.set_source(g); c.paint()
for i in range(40):
    c.set_source_rgba(1, 1, 1, 0.18 if i % 2 else 0.05); c.rectangle(i * 48, 0, 20, 1080); c.fill()
for x, y, r, col in ((900, 200, 120, (0.2, 0.9, 0.6)), (1650, 260, 130, (1, 0.85, 0.2))):
    c.set_source_rgb(*col); c.arc(x, y, r, 0, 2 * math.pi); c.fill()
s.write_to_png("/tmp/wall.png")
from swayctl_center import themes, schema
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule
from swayctl_center.modules.effects import EffectsModule
v = schema.defaults(); v["appearance"]["style"] = "modern"; v["effects"]["glass"] = True
t = themes.BUILTIN[sys.argv[1]]
ctx = Context(pathlib.Path("/tmp/app"), values=v, theme=t,
              live={"sway_original_version": "x", "swayctl_features": ["glass", "glass-shaped", "glass-blur"]})
d = pathlib.Path("/tmp/bar"); d.mkdir(exist_ok=True)
(d / "config.json").write_text(json.dumps(BarModule().native_config(v["bar"] | {"program": "swayctl-bar"}, ctx)))
(d / "style.css").write_text(BarModule().native_css(ctx, t))
open("/tmp/fx.cmds", "w").write("\n".join(EffectsModule().commands("effects", v["effects"], None, ctx)))
PY
swaymsg 'output * bg /tmp/wall.png fill' >/dev/null
while IFS= read -r c; do swaymsg -- "$c" >/dev/null 2>&1 || true; done < /tmp/fx.cmds
$bin --config-dir /tmp/bar 2>>/tmp/out/cal-bar.log &
pid=$!
sleep 2
$v click 960 27 272 & sleep 1
grim "/tmp/out/calendar-$theme.png"
$v click 300 700 272 & sleep 0.6      # outside: closes
$bin quick; sleep 1
grim "/tmp/out/quick-$theme.png"
kill $pid; sleep 0.5
done

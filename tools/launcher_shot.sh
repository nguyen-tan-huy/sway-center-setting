#!/bin/sh
# Walker with the generated theme over a busy wallpaper, glass off and on.
#   tools/sandbox.sh --fx /home/repo/tools/launcher_shot.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp
for mode in ${MODES:-plain glass}; do
python3 - "$mode" <<'PY'
import sys, pathlib, cairo, math
sys.path.insert(0, "/home/repo")
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 1920, 1080); c = cairo.Context(s)
g = cairo.LinearGradient(0, 0, 1920, 1080)
g.add_color_stop_rgb(0, 0.10, 0.20, 0.55); g.add_color_stop_rgb(0.5, 0.75, 0.25, 0.55); g.add_color_stop_rgb(1, 0.98, 0.65, 0.20)
c.set_source(g); c.paint()
c.set_source_rgb(0.96, 0.94, 0.9); c.rectangle(0, 0, 1920, 1080); c.fill()
for i in range(40):
    c.set_source_rgba(1, 1, 1, 0.18 if i % 2 else 0.05); c.rectangle(i * 48, 0, 20, 1080); c.fill()
for x, y, r, col in ((700, 300, 140, (0.2, 0.9, 0.6)), (1250, 650, 120, (0.3, 0.6, 1))):
    c.set_source_rgb(*col); c.arc(x, y, r, 0, 2 * math.pi); c.fill()
# a page of text, like a chat window behind the launcher
c.select_font_face("Sans", 0, 0); c.set_font_size(30)
for row in range(30):
    c.set_source_rgb(*((0.1, 0.1, 0.1) if row % 3 else (0.85, 0.35, 0.2)))
    c.move_to(40 + (row % 2) * 30, 40 + row * 36)
    c.show_text("Thông nhất về thiết lập, triển khai sớm nhất có thể nha anh  " * 2)
s.write_to_png("/tmp/wall.png")
from swayctl_center import themes, schema
from swayctl_center.modules import Context
from swayctl_center.modules.launcher import LauncherModule
from swayctl_center.modules.effects import EffectsModule
v = schema.defaults(); v["appearance"]["style"] = "modern"; v["effects"]["glass"] = sys.argv[1] == "glass"
ctx = Context(pathlib.Path("/tmp/app"), values=v, theme=themes.BUILTIN[__import__("os").environ.get("THEME", "dark")],
              live={"sway_original_version": "x", "swayctl_features": ["glass", "glass-shaped", "glass-blur"]})
m = LauncherModule()
for name, text in m.files(v["launcher"], ctx).items():
    p = m.root(ctx) / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
m.link_plugins(ctx)
open("/tmp/fx.cmds", "w").write("\n".join(EffectsModule().commands("effects", v["effects"], None, ctx)))
PY
swaymsg 'output * bg /tmp/wall.png fill' >/dev/null
while IFS= read -r c; do swaymsg -- "$c" >/dev/null 2>&1 || true; done < /tmp/fx.cmds
elephant --config /tmp/app/generated/launcher/elephant > /tmp/out/elephant.log 2>&1 &
el=$!
sleep 1.5
XDG_CONFIG_HOME=/tmp/app/generated/launcher walker > /tmp/out/walker.log 2>&1 &
wk=$!
sleep 2.5
grim "/tmp/out/launcher-$mode-${THEME:-dark}.png"
kill $wk $el 2>/dev/null || true; sleep 0.5
done

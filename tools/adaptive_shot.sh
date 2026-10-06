#!/bin/sh
# Adaptive text on glass over a half white / half black wallpaper: bar modules
# pick their text from what's behind (swayctl-bar), panes keep their text
# readable (glass_text in the shader).
#   tools/sandbox.sh --fx env THEME=dark TINT=0 /home/repo/tools/adaptive_shot.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp
mkdir -p bar
python3 - <<'PY'
import os, sys, json, pathlib, cairo
sys.path.insert(0, "/home/repo")
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 1920, 1080); c = cairo.Context(s)
c.set_source_rgb(0.97, 0.97, 0.97); c.rectangle(0, 0, 1100, 1080); c.fill()
c.set_source_rgb(0.05, 0.05, 0.08); c.rectangle(1100, 0, 820, 1080); c.fill()
c.select_font_face("Sans", 0, 1); c.set_font_size(36)
for row in range(26):
    c.set_source_rgb(*((0.1, 0.1, 0.1) if row % 2 else (0.9, 0.9, 0.9)))
    c.move_to(1300, 140 + row * 36); c.show_text("light and dark text behind")
if os.environ.get("INVERT"):
    s2 = cairo.ImageSurface(cairo.FORMAT_RGB24, 1920, 1080); c2 = cairo.Context(s2)
    c2.translate(1920, 0); c2.scale(-1, 1); c2.set_source_surface(s); c2.paint(); s = s2
s.write_to_png("/tmp/wall.png")
from swayctl_center import themes, schema
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule
from swayctl_center.modules.effects import EffectsModule
v = schema.defaults(); v["appearance"]["style"] = "modern"; v["effects"]["glass"] = True
v["effects"]["glass_opacity"] = int(os.environ.get("TINT", 0))
v["background"]["image"] = "wall.png"
v["bar"]["modules_center"] = ["clock"]
t = themes.BUILTIN[os.environ.get("THEME", "dark")]
ctx = Context(pathlib.Path("/tmp"), values=v, theme=t,
              live={"sway_original_version": "x", "swayctl_features": ["glass", "glass-shaped", "glass-blur", "glass-text"]})
files = BarModule().files(v["bar"] | {"program": "swayctl-bar"}, ctx)
pathlib.Path("/tmp/bar/config.json").write_text(files["config.json"])
pathlib.Path("/tmp/bar/style.css").write_text(files["style.css"])
open("/tmp/fx.cmds", "w").write("\n".join(EffectsModule().commands("effects", v["effects"], None, ctx)))
PY
swaymsg 'output * bg /tmp/wall.png fill' >/dev/null
while IFS= read -r c; do swaymsg -- "$c" >/dev/null 2>&1 || echo "fx failed: $c" >&2; done < /tmp/fx.cmds
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir /tmp/bar 2>/tmp/out/adaptive-bar.log &
sleep 2.5
grim "/tmp/out/adaptive-bar-${THEME:-dark}.png"
$bin quick; sleep 1.2
grim "/tmp/out/adaptive-quick-${THEME:-dark}.png"
$bin quick; sleep 0.5
/home/repo/tools/vptr/vptr click 960 27 272 & sleep 1.2
grim "/tmp/out/adaptive-cal-${THEME:-dark}.png"
/home/repo/tools/vptr/vptr click 300 700 272 & sleep 0.8
notify-send -a Mail "Hello" "A notification over what's there" ; sleep 1.2
grim "/tmp/out/adaptive-notify-${THEME:-dark}.png"

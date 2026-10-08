#!/bin/sh
# The bar and Quick Settings with swayctl-fx's key ink (`glass_text auto`),
# on a half dark / half light wallpaper: the text must be light on the left,
# dark on the right, with no key colour (#FF00FE) left anywhere and no
# backdrop probe asked by the bar.
#   tools/sandbox.sh --fx /home/repo/tools/bar_ink_shot.sh
# Shots: tools/out/bar-ink-bar.png, tools/out/bar-ink-quick.png
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp
trap 'cp /tmp/sway.log /tmp/out/bar-ink-sway.log 2>/dev/null || true' EXIT
python3 - <<'PY'
import cairo
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 1920, 1080)
c = cairo.Context(s)
c.set_source_rgb(0.08, 0.10, 0.22); c.rectangle(0, 0, 960, 1080); c.fill()
c.set_source_rgb(0.95, 0.93, 0.88); c.rectangle(960, 0, 960, 1080); c.fill()
s.write_to_png("/tmp/wall.png")
PY
swaymsg 'output * bg /tmp/wall.png fill' >/dev/null
mkdir -p bar
cat > bar/config.json <<'JSON'
{"modules_left": ["workspaces", "mode"], "modules_center": ["clock"], "modules_right": ["status"],
 "margins": [8, 8, 0, 8], "height": 38, "backdrop": {"adaptive": true, "lens": true, "lens_tint": 0.04}}
JSON
python3 - <<'PY'
import sys; sys.path.insert(0, "/home/repo")
from swayctl_center import themes, schema
from swayctl_center.modules.components import BarModule, key_ink_css
from swayctl_center.modules import Context
import pathlib
v = schema.defaults(); v["appearance"]["style"] = "modern"; v["effects"]["glass"] = True
ctx = Context(pathlib.Path("/tmp/app"), values=v, theme=themes.BUILTIN["dark"])
css = BarModule().native_css(ctx, ctx.theme) + BarModule.adaptive_css(ctx)
open("/tmp/bar/style.css", "w").write(css)
PY
python3 - <<'PY' > /tmp/lens.sh
import sys; sys.path.insert(0, "/home/repo")
from swayctl_center import schema
import os
eff = schema.defaults()["effects"]
# GLASS_BLUR=37 BLUR_PASSES=2 BLUR_RADIUS=5: blurred glass (no kept backdrop)
eff["glass_blur"] = int(os.environ.get("GLASS_BLUR", eff["glass_blur"]))
for ns in ("swayctl-bar", "swayctl-quick"):
    # one effect per command: layer_effects parses only its first effect
    for e in ["blur enable", "glass enable", "blur_ignore_transparent enable",
              "shadows disable", "glass_text auto"] + ["%s %g" % (k, eff[k]) for k in
              ("glass_refraction", "glass_highlight", "glass_blur",
               "glass_edge", "glass_thickness", "glass_chroma")]:
        print('swaymsg \'layer_effects "%s" "%s"\' >/dev/null' % (ns, e))
PY
swaymsg "blur_passes ${BLUR_PASSES:-0}; blur_radius ${BLUR_RADIUS:-0}" >/dev/null
. /tmp/lens.sh
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir /tmp/bar 2>/tmp/out/bar-ink.log &
sleep 2.5
grim -g "0,0 1920x70" /tmp/out/bar-ink-bar.png
$bin quick
sleep 3
grim -g "1100,0 820x700" /tmp/out/bar-ink-quick.png
echo done

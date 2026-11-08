#!/bin/sh
# Shadows of what a popup draws (swayctl-fx's shaped shadows): Quick Settings and the launcher on a
# light wallpaper with the Window shadows setting on, and again with it off.
#   tools/sandbox.sh --fx /home/repo/tools/shadow_shot.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp; mkdir -p bar /tmp/out
setup() {   # $1 = shadows on|off
  SHADOWS=$1 python3 - <<'PY'
import json, os, pathlib, subprocess, sys
sys.path.insert(0, "/home/repo")
from swayctl_center import themes, schema, swayipc
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule
from swayctl_center.modules.effects import EffectsModule
v = schema.defaults(); v["appearance"]["style"] = "modern"
on = os.environ["SHADOWS"] == "on"
v["effects"].update(glass=True, panels=True, anim_quick=False, shadows=on, shadow_blur_radius=40, shadow_offset_y=10)
ctx = Context(pathlib.Path("/tmp/app"), values=v, theme=themes.BUILTIN["light"], live=swayipc.Connection().get_version())
pathlib.Path("/tmp/bar/config.json").write_text(json.dumps(BarModule().native_config(v["bar"] | {"program": "swayctl-bar"}, ctx)))
pathlib.Path("/tmp/bar/style.css").write_text(BarModule().native_css(ctx, ctx.theme))
for c in EffectsModule().commands("effects", v["effects"], None, ctx):
    subprocess.run(["swaymsg", c], capture_output=True)
PY
}
swaymsg 'output * bg #e8e6f0 solid_color' >/dev/null
bin=${BAR_BIN:-/home/repo/swayctl-bar/target/release/swayctl-bar}
for mode in on off; do
  setup $mode
  $bin --config-dir /tmp/bar 2>/dev/null & b=$!
  sleep 2.5
  $bin quick; sleep 1.2; grim -g "1380,0 540x420" /tmp/out/sh-quick-$mode.png; $bin quick; sleep 0.8
  $bin launcher; sleep 1.2; grim -g "480,120 960x420" /tmp/out/sh-launcher-$mode.png; $bin launcher; sleep 0.8
  kill $b 2>/dev/null || true; sleep 0.6
done
echo done

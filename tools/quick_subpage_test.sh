#!/bin/sh
# Open Quick Settings, go into a sub-page (Power) and back: the layer surface
# must follow the page's size each time.
#   tools/sandbox.sh --fx /home/repo/tools/quick_subpage_test.sh
set -eu
cd /tmp
mkdir -p bar
printf '{"modules_left":["workspaces"],"modules_center":["clock"],"modules_right":["status"],"margins":[8,8,0,8],"height":38}' > bar/config.json
python3 - <<'PY'
import os, sys, pathlib
sys.path.insert(0, "/home/repo")
from swayctl_center import themes, schema
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule
from swayctl_center.modules.effects import EffectsModule
v = schema.defaults(); v["appearance"]["style"] = "modern"; v["effects"]["glass"] = os.environ.get("GLASS", "1") == "1"
v["effects"]["glass_opacity"] = int(os.environ.get("TINT", 50)); v["effects"]["glass_blur"] = int(os.environ.get("FROST", 100))
t = themes.BUILTIN[os.environ.get("THEME", "dark")]
ctx = Context(pathlib.Path("/tmp/app"), values=v, theme=t,
              live={"sway_original_version": "x", "swayctl_features": ["glass", "glass-shaped", "glass-blur"]})
pathlib.Path("/tmp/bar/style.css").write_text(BarModule().native_css(ctx, t))
open("/tmp/fx.cmds", "w").write("\n".join(EffectsModule().commands("effects", v["effects"], None, ctx)))
PY
while IFS= read -r c; do swaymsg -- "$c" >/dev/null 2>&1 || true; done < /tmp/fx.cmds
swaymsg 'output * bg /home/repo/tools/out/wall-text.png fill' >/dev/null 2>&1 || swaymsg 'output * bg #6a4c93 solid_color' >/dev/null
python3 /home/repo/tools/fake_mpris.py 2>/dev/null &
/home/repo/swayctl-bar/target/release/swayctl-bar --config-dir /tmp/bar 2>/tmp/out/qs.log &
sleep 2
size() { swaymsg -t get_outputs | python3 -c "
import json,sys
for l in json.load(sys.stdin)[0].get('layer_shell_surfaces',[]):
    if l['namespace']=='swayctl-quick': print(l['extent']['width'], 'x', l['extent']['height'], '@', l['extent']['x'], l['extent']['y'])"; }
v=/home/repo/tools/vptr/vptr
$v click 1880 27 272 & sleep 1.2
echo "main page:  $(size)"
grim -g "1300,0 620x500" /tmp/out/qs-main.png
# power button: bottom right of the panel
set -- $(size); w=$1; h=$3; x=${5}; y=${6}
$v click $((x + w - 30)) $((y + h - 30)) 272 & sleep 1.2
echo "power page: $(size)"
grim -g "1300,0 620x500" /tmp/out/qs-sub-${THEME:-dark}.png
# back arrow, top left of the sub-page header
set -- $(size); x=${5}; y=${6}
$v click $((x + 38)) $((y + 38)) 272 & sleep 1.2
echo "back:       $(size)"
grim -g "1300,0 620x500" /tmp/out/qs-back.png

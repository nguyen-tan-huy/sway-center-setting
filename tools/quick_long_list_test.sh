#!/bin/sh
# Many notifications: Quick Settings must stay on screen, the list scrolls.
#   tools/sandbox.sh --fx /home/repo/tools/quick_long_list_test.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp
mkdir -p bar
python3 - <<'PY'
import json, pathlib, sys
sys.path.insert(0, "/home/repo")
from swayctl_center import themes, schema
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule
v = schema.defaults(); v["appearance"]["style"] = "modern"; v["effects"]["glass"] = True
v["notifications"]["timeout"] = 1
ctx = Context(pathlib.Path("/tmp/app"), values=v, theme=themes.BUILTIN["dark"])
pathlib.Path("/tmp/bar/config.json").write_text(json.dumps(BarModule().native_config(v["bar"] | {"program": "swayctl-bar"}, ctx)))
pathlib.Path("/tmp/bar/style.css").write_text(BarModule().native_css(ctx, ctx.theme))
PY
swaymsg 'output * bg #6a4c93 solid_color' >/dev/null
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir /tmp/bar 2>/tmp/out/qll.log &
sleep 2
for i in $(seq 15); do notify-send -a "App $i" "Notification number $i" "Some body text for notification $i"; done
sleep 2.5
size() { swaymsg -t get_outputs | python3 -c "
import json,sys
for l in json.load(sys.stdin)[0].get('layer_shell_surfaces',[]):
    if l['namespace']=='swayctl-quick': print(l['extent']['height'], 'px tall, bottom at', l['extent']['y'] + l['extent']['height'])"; }
$bin quick; sleep 1.2
echo "screen 1080: $(size)"
grim /tmp/out/quick-long.png
/home/repo/tools/vptr/vptr click 1700 600 272 & sleep 0.6   # puts the pointer on a card (no default action: nothing happens)
VPTR_X=1700 VPTR_Y=600 /home/repo/tools/vptr/vptr wheel 6 60; sleep 1
VPTR_X=1700 VPTR_Y=600 /home/repo/tools/vptr/vptr finger 40 12 10; sleep 2
grim /tmp/out/quick-long-scrolled.png
echo "after scroll: $(size)"

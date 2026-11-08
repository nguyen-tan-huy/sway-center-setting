#!/bin/sh
# First notification: how big is its surface? (and a screenshot)
#   tools/sandbox.sh --fx /home/repo/tools/notif_first_probe.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp; mkdir -p bar /tmp/out
python3 - <<'PY'
import json, pathlib, sys
sys.path.insert(0, "/home/repo")
from swayctl_center import themes, schema
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule
v = schema.defaults(); v["appearance"]["style"] = "modern"; v["effects"]["glass"] = True
ctx = Context(pathlib.Path("/tmp/app"), values=v, theme=themes.BUILTIN["dark"])
pathlib.Path("/tmp/bar/config.json").write_text(json.dumps(BarModule().native_config(v["bar"] | {"program": "swayctl-bar"}, ctx)))
pathlib.Path("/tmp/bar/style.css").write_text(BarModule().native_css(ctx, ctx.theme))
PY
swaymsg 'output HEADLESS-1 resolution 3072x1920 scale 1.25' >/dev/null; sleep 1
export PYTHONPATH=/home/repo
python3 -m swayctl_center daemon > /tmp/out/daemon.log 2>&1 &
sleep 3
bin=${BAR_BIN:-/home/repo/swayctl-bar/target/release/swayctl-bar}
$bin --config-dir /tmp/bar 2>/tmp/out/nf.log &
sleep 2
ext() { swaymsg -t get_outputs | python3 -c "
import json,sys
for o in json.load(sys.stdin):
    for l in o.get('layer_shell_surfaces',[]):
        if l['namespace']=='swayctl-notifications': print('$1', l['extent'])"; }
LONG="$(python3 -c "print('A notification body that wraps' * 1)")"
notify-send -a Test "A fairly long summary line for the first notification of the session $LONG" "$LONG" &
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do sleep 0.12; ext "t$i"; done
grim /tmp/out/nf1.png
notify-send -a Test "Second" "Another one"; sleep 1.5; ext second; grim /tmp/out/nf2.png

#!/bin/sh
# Does a notification go away by itself? (default timeout 8 s) Normal, and with the pointer parked where it appears.
#   tools/sandbox.sh --fx /home/repo/tools/notif_expire_probe.sh
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
v["notifications"].update(position_x="left", position_y="bottom", max_visible=1, timeout=5)
ctx = Context(pathlib.Path("/tmp/app"), values=v, theme=themes.BUILTIN["dark"])
pathlib.Path("/tmp/bar/config.json").write_text(json.dumps(BarModule().native_config(v["bar"] | {"program": "swayctl-bar"}, ctx)))
pathlib.Path("/tmp/bar/style.css").write_text(BarModule().native_css(ctx, ctx.theme))
PY
export PYTHONPATH=/home/repo
python3 -m swayctl_center daemon > /tmp/out/daemon.log 2>&1 &
sleep 3
bin=${BAR_BIN:-/home/repo/swayctl-bar/target/release/swayctl-bar}
$bin --config-dir /tmp/bar 2>/tmp/out/ne.log &
sleep 2
shown() { swaymsg -t get_outputs | python3 -c "
import json,sys
n=[l['extent'] for o in json.load(sys.stdin) for l in o.get('layer_shell_surfaces',[]) if l['namespace']=='swayctl-notifications']
print('$1', 'SHOWN' if n else 'gone', n[0] if n else '')"; }
AV=/tmp/out/avatar.png; ffmpeg -v error -y -f lavfi -i color=c=orange:s=96x96 -frames:v 1 $AV 2>/dev/null || cp /home/repo/data/icons/*.png $AV
cs() { gdbus call --session --dest org.freedesktop.Notifications --object-path /org/freedesktop/Notifications \
  --method org.freedesktop.Notifications.Notify -- "ChoSua" 0 "chosua" "$1" "$2" '["default","Open"]' \
  "{'desktop-entry': <'chosua'>, 'image-path': <'$AV'>}" -1 >/dev/null; }
echo "--- a card on screen, then Do Not Disturb on (clears the screen), then off"
cs "Công" "first message"; sleep 1.5; shown "before"
$bin dnd on; sleep 1.5; shown "dnd on +1.5s"; sleep 3; shown "dnd on +4.5s"
$bin dnd off; sleep 1
echo "--- after DnD off: a new one must appear and then go"
cs "Next" "after dnd"; sleep 1.5; shown "t=1.5s"; sleep 7; shown "t=8.5s"
echo "--- the card expires while Quick Settings is open"
cs "Q" "with quick open"; sleep 1; $bin quick; sleep 8; shown "t=9s quick open"; $bin quick; sleep 1; shown "quick closed"

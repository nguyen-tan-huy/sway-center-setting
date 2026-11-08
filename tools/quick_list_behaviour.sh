#!/bin/sh
# The lazy notification list: 50 notifications, only some cards are built at
# first, scrolling to the end builds the rest, closing one removes just it.
#   tools/sandbox.sh --fx /home/repo/tools/quick_list_behaviour.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp
mkdir -p bar /tmp/out
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
bin=${BAR_BIN:-/home/repo/swayctl-bar/target/release/swayctl-bar}
log=/tmp/out/quick-behaviour.log
: > "$log"
SWAYCTL_BAR_TRACE=1 $bin --config-dir /tmp/bar 2>>"$log" &
sleep 2
for i in $(seq 50); do notify-send -a "App $i" "Notification number $i" "Body of notification $i"; done
sleep 3
$bin quick; sleep 1.5
echo "after open:";           grep -c 'list synced' "$log" | sed 's/^/  list syncs: /'
grim /tmp/out/qlb-open.png
# scroll to the end: more cards get built as it nears the end
for k in 1 2 3 4 5 6; do VPTR_X=1700 VPTR_Y=600 /home/repo/tools/vptr/vptr wheel 6 60; sleep 0.4; done
sleep 1
echo "after scrolling:";      grep -c 'list synced' "$log" | sed 's/^/  list syncs: /'
grim /tmp/out/qlb-scrolled.png
# close the newest one over D-Bus: one sync, no rebuild of the rest
before=$(grep -c 'list synced' "$log")
gdbus call --session --dest org.freedesktop.Notifications --object-path /org/freedesktop/Notifications \
  --method org.freedesktop.Notifications.CloseNotification 50 >/dev/null
sleep 0.5
after=$(grep -c 'list synced' "$log")
echo "closing one notification: $((after - before)) sync(s)"
grep 'list synced' "$log" | tail -1

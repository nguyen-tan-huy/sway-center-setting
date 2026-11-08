#!/bin/sh
# The Smooth UI tile and its page, with the real daemon behind them (a private config).
#   tools/sandbox.sh --fx /home/repo/tools/quick_priority_shot.sh
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
ctx = Context(pathlib.Path("/tmp/app"), values=v, theme=themes.BUILTIN["dark"])
pathlib.Path("/tmp/bar/config.json").write_text(json.dumps(BarModule().native_config(v["bar"] | {"program": "swayctl-bar"}, ctx)))
pathlib.Path("/tmp/bar/style.css").write_text(BarModule().native_css(ctx, ctx.theme))
PY
swaymsg 'output * bg #6a4c93 solid_color' >/dev/null
export PYTHONPATH=/home/repo
python3 -m swayctl_center daemon > /tmp/out/daemon.log 2>&1 &
sleep 3
bin=${BAR_BIN:-/home/repo/swayctl-bar/target/release/swayctl-bar}
$bin --config-dir /tmp/bar 2>/tmp/out/psh.log &
sleep 2
$bin quick; sleep 1.5
grim /tmp/out/qp-main.png
echo "main page taken"
case "${1:-}" in
  click) VPTR_X=${2:-1830} VPTR_Y=${3:-300} /home/repo/tools/vptr/vptr click "${2:-1830}" "${3:-300}" 272; sleep 1.2; grim /tmp/out/qp-page.png; echo "clicked ${2:-} ${3:-}" ;;
esac
if [ -n "${4:-}" ]; then   # then press a control on the page and read what the daemon now holds
  echo "before: ui_nice=$(python3 -m swayctl_center get priority.ui_nice)"
  /home/repo/tools/vptr/vptr click "$4" "$5" 272; sleep 1.2
  echo "after : ui_nice=$(python3 -m swayctl_center get priority.ui_nice)"
  grim /tmp/out/qp-after.png
fi
python3 -m swayctl_center get priority.enabled

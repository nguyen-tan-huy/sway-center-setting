#!/bin/sh
# Does Quick Settings follow the compositor's own animation settings (the ones windows follow)?
# Opens and closes it under different `animation_curve` / `animation_spring` / `animation_duration_ms`
# and counts the frames the compositor draws for each (damage-driven: it only draws while it moves),
# and how long the window then takes to go.
#   SWAY_FRAME_TIMES=/tmp/out/ft.log tools/sandbox.sh --fx /home/repo/tools/quick_follows_global.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
[ -n "${SWAY_FRAME_TIMES:-}" ] || { echo "set SWAY_FRAME_TIMES=/tmp/out/ft.log" >&2; exit 1; }
cd /tmp; mkdir -p bar /tmp/out
python3 - <<'PY'
import json, pathlib, subprocess, sys
sys.path.insert(0, "/home/repo")
from swayctl_center import themes, schema, swayipc
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule
from swayctl_center.modules.effects import EffectsModule
v = schema.defaults(); v["appearance"]["style"] = "modern"
v["effects"].update(glass=True, anim_quick=True, anim_open_close=True)
ctx = Context(pathlib.Path("/tmp/app"), values=v, theme=themes.BUILTIN["dark"], live=swayipc.Connection().get_version())
pathlib.Path("/tmp/bar/config.json").write_text(json.dumps(BarModule().native_config(v["bar"] | {"program": "swayctl-bar"}, ctx)))
pathlib.Path("/tmp/bar/style.css").write_text(BarModule().native_css(ctx, ctx.theme))
for c in EffectsModule().commands("effects", v["effects"], None, ctx):
    subprocess.run(["swaymsg", c], capture_output=True)
PY
swaymsg 'output * bg #6a4c93 solid_color' >/dev/null
bin=${BAR_BIN:-/home/repo/swayctl-bar/target/release/swayctl-bar}
$bin --config-dir /tmp/bar 2>/dev/null & b=$!
sleep 2.5
frames() { wc -l < "$SWAY_FRAME_TIMES"; }
measure() {   # label, then sway commands
  label=$1; shift
  for c in "$@"; do swaymsg "$c" >/dev/null; done
  $bin quick; sleep 1.6; $bin quick; sleep 1.6           # warm for this setting
  a=$(frames); $bin quick; sleep 1.6; o=$(( $(frames) - a ))
  a=$(frames); $bin quick; sleep 1.6; c=$(( $(frames) - a ))
  echo "$label: open $o frames, close $c frames"
}
swaymsg 'animation_duration_ms 200' >/dev/null
measure "ease 150 ms        " "animation_duration_ms 150" "animation_curve ease"
measure "ease 500 ms        " "animation_duration_ms 500" "animation_curve ease"
measure "spring 160 ms      " "animation_duration_ms 200" "animation_curve spring" "animation_spring 160 0"
measure "spring 340 ms 0.08 " "animation_curve spring" "animation_spring 340 0.08"
measure "spring 600 ms 0.30 " "animation_curve spring" "animation_spring 600 0.3"
measure "popups disabled    " "animation_curve spring" "animation_spring 340 0.08" "animations popups disable"
measure "popups enabled again" "animations popups enable"
kill $b 2>/dev/null || true

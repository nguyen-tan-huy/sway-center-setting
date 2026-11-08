#!/bin/sh
# Frames of Quick Settings opening, animated by the compositor: grim runs are started at fixed
# offsets after the toggle (each takes ~50 ms, so they overlap in the background).
#   [ANIM_CURVE=ease|spring ANIM_DURATION=ms ANIM_RESPONSE=ms ANIM_BOUNCE=%] tools/sandbox.sh --fx /home/repo/tools/quick_compositor_shot.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp; mkdir -p bar /tmp/out
python3 - <<'PY'
import json, pathlib, subprocess, sys
sys.path.insert(0, "/home/repo")
from swayctl_center import themes, schema, swayipc
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule
from swayctl_center.modules.effects import EffectsModule
v = schema.defaults(); v["appearance"]["style"] = "modern"
import os
v["effects"].update(glass=True, anim_quick=True, anim_open_close=True, anim_duration=int(os.environ.get("ANIM_DURATION", 120)),
                    anim_curve=os.environ.get("ANIM_CURVE", "spring"), anim_response=int(os.environ.get("ANIM_RESPONSE", 340)),
                    anim_bounce=int(os.environ.get("ANIM_BOUNCE", 8)))
ctx = Context(pathlib.Path("/tmp/app"), values=v, theme=themes.BUILTIN["dark"], live=swayipc.Connection().get_version())
pathlib.Path("/tmp/bar/config.json").write_text(json.dumps(BarModule().native_config(v["bar"] | {"program": "swayctl-bar"}, ctx)))
pathlib.Path("/tmp/bar/style.css").write_text(BarModule().native_css(ctx, ctx.theme))
for c in EffectsModule().commands("effects", v["effects"], None, ctx):
    subprocess.run(["swaymsg", c], capture_output=True)
PY
swaymsg 'output * bg #6a4c93 solid_color' >/dev/null
bin=${BAR_BIN:-/home/repo/swayctl-bar/target/release/swayctl-bar}
$bin --config-dir /tmp/bar 2>/tmp/out/cs.log & b=$!
sleep 2.5
# warm: one full open and close, so the first measured opening is not the cold one
$bin quick; sleep 1.2; $bin quick; sleep 1
for pass in open close; do
  python3 - "$pass" <<'PY'
import subprocess, sys, time
which = sys.argv[1]
bin_ = "/home/repo/swayctl-bar/target/release/swayctl-bar"
if which == "close":
    subprocess.run([bin_, "quick"]); time.sleep(1.2)   # open and settle first
t0 = time.monotonic()
subprocess.Popen([bin_, "quick"])
procs = []
for i, off in enumerate((0.02, 0.06, 0.10, 0.15, 0.22, 0.32)):
    time.sleep(max(0, t0 + off - time.monotonic()))
    procs.append(subprocess.Popen(["grim", "-g", "1480,0 440x330", f"/tmp/out/cs-{which}-{i}.png"]))
for p in procs: p.wait()
time.sleep(1.2)
subprocess.run(["grim", "-g", "1480,0 440x330", f"/tmp/out/cs-{which}-end.png"])
PY
  [ "$pass" = open ] && { $bin quick; sleep 1; }   # (closed again by the open pass's toggle below)
done
kill $b 2>/dev/null || true
cat /tmp/out/cs.log | grep -v "system bus" | head -5

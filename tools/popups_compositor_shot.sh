#!/bin/sh
# Launcher and OSD opening / closing, animated by the compositor: grim runs started at fixed offsets.
#   tools/sandbox.sh --fx /home/repo/tools/popups_compositor_shot.sh
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
v["effects"].update(glass=True, anim_quick=True, anim_open_close=True, anim_duration=120)
ctx = Context(pathlib.Path("/tmp/app"), values=v, theme=themes.BUILTIN["dark"], live=swayipc.Connection().get_version())
pathlib.Path("/tmp/bar/config.json").write_text(json.dumps(BarModule().native_config(v["bar"] | {"program": "swayctl-bar"}, ctx)))
pathlib.Path("/tmp/bar/style.css").write_text(BarModule().native_css(ctx, ctx.theme))
for c in EffectsModule().commands("effects", v["effects"], None, ctx):
    subprocess.run(["swaymsg", c], capture_output=True)
PY
swaymsg 'output * bg #6a4c93 solid_color' >/dev/null
bin=${BAR_BIN:-/home/repo/swayctl-bar/target/release/swayctl-bar}
$bin --config-dir /tmp/bar 2>/tmp/out/pc.log & b=$!
sleep 2.5
python3 - <<'PY'
import subprocess, sys, time
bin_ = "/home/repo/swayctl-bar/target/release/swayctl-bar"
def burst(name, cmd, region, offsets):
    t0 = time.monotonic()
    subprocess.Popen(cmd)
    procs = []
    for i, off in enumerate(offsets):
        time.sleep(max(0, t0 + off - time.monotonic()))
        procs.append(subprocess.Popen(["grim", "-g", region, f"/tmp/out/pc-{name}-{i}.png"]))
    for p in procs: p.wait()
def shot(name, region): subprocess.run(["grim", "-g", region, f"/tmp/out/pc-{name}.png"])
L = "560,150 800x420"; O = "760,860 400x160"
# warm: one round of each so nothing measured is the cold start
subprocess.run([bin_, "launcher"]); time.sleep(1.0); subprocess.run([bin_, "launcher"]); time.sleep(1.0)
burst("launcher-open", [bin_, "launcher"], L, (0.02, 0.06, 0.10, 0.16, 0.26, 0.40)); time.sleep(0.8); shot("launcher-open-end", L)
burst("launcher-close", [bin_, "launcher"], L, (0.01, 0.04, 0.07, 0.10, 0.16, 0.30)); time.sleep(0.8); shot("launcher-close-end", L)
burst("osd-open", [bin_, "osd", "brightness-up"], O, (0.02, 0.05, 0.09, 0.13, 0.20, 0.35)); shot("osd-open-end", O)
time.sleep(1.1)
burst("osd-close", ["true"], O, (0.01, 0.04, 0.08, 0.12, 0.18, 0.30)); time.sleep(0.8); shot("osd-close-end", O)
PY
kill $b 2>/dev/null || true
grep -v "system bus\|a11y\|pa_context\|Connection" /tmp/out/pc.log | head -5

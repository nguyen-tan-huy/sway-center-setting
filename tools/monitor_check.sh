#!/bin/sh
# Test riêng: bar có tự nạp style.css khi file đổi không (không qua daemon)?
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh" >&2; exit 1 ;; esac
export PYTHONPATH=/home/repo
OUT=/tmp/out
GEN=/home/sandbox/.config/swayctl-center/generated/bar
mkdir -p "$GEN"

swaymsg 'output * bg #0d0d14 solid_color' >/dev/null

python3 - <<'PY'
import sys, pathlib, json
sys.path.insert(0, "/home/repo")
from swayctl_center import themes, schema
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule
v = schema.defaults(); v["appearance"]["style"] = "modern"; v["effects"]["glass"] = True
v["effects"]["glass_opacity"] = 10
t = themes.BUILTIN["dark"]
ctx = Context(pathlib.Path("/home/sandbox/.config/swayctl-center"), values=v, theme=t,
              live={"sway_original_version": "x", "swayctl_features": ["glass", "glass-shaped", "glass-blur", "glass-text"]})
files = BarModule().files(v["bar"] | {"program": "swayctl-bar"}, ctx)
pathlib.Path("/tmp/gen/style.css").parent.mkdir(parents=True, exist_ok=True)
pathlib.Path("/tmp/gen/style.css").write_text(files["style.css"])
pathlib.Path("/tmp/gen/config.json").write_text(files["config.json"])
print("gen ok")
PY
mkdir -p "$GEN"
cp /tmp/gen/style.css "$GEN/style.css"
cp /tmp/gen/config.json "$GEN/config.json"

bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir "$GEN" > "$OUT/mon-bar1.log" 2>&1 &
pid=$!
sleep 2.5
grim "$OUT/mon-a.png"

# đổi style: làm tối module phải mạnh để thấy rõ (tăng alpha nền module)
python3 - <<'PY'
import pathlib
p = pathlib.Path("/home/sandbox/.config/swayctl-center/generated/bar/style.css")
css = p.read_text()
css += ("\n/* mon-test */\n"
        ".clock.clock.clock.clock.clock.clock.clock.clock,\n"
        ".status.status.status.status.status.status.status.status {"
        " background: #ff0000; color: #ffffff; }\n")
p.write_text(css)
print("rewrote style.css")
PY
sleep 2
grim "$OUT/mon-b.png"
kill "$pid" 2>/dev/null || true

/usr/bin/python3 - <<'PY'
import cairo, sys
def px(path, x, y):
    s = cairo.ImageSurface.create_from_png(path)
    st, buf = s.get_stride(), bytes(s.get_data())
    i = y * st + x * 4
    return (buf[i+2], buf[i+1], buf[i])
a = px("/tmp/out/mon-a.png", 1860, 25)
b = px("/tmp/out/mon-b.png", 1860, 25)
print("right module truoc:", a, "sau:", b)
if a != b:
    print("PASS: bar tu nap style.css khi file doi (inotify hoat dong)")
else:
    print("FAIL: style.css doi nhung bar khong doi render")
    sys.exit(1)
PY

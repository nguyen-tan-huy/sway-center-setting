#!/bin/sh
# The real bar, Quick Settings and OSD over *your* wallpaper, glass off and on,
# with every compositor command taken from EffectsModule — the code path
# swayctl-center uses — so the screenshot is what the shell actually applies
# (no hand-typed layer_effects lines that drift away from effects.py).
#
#   tools/liquid_wall.sh                         # host: wallpaper + settings -> tools/out/
#   tools/sandbox.sh --fx /home/repo/tools/liquid_shot.sh
#
# pactl / brightnessctl are faked (there is no sound server in the sandbox) so
# the volume OSD and the brightness slider show up; tools/fake_mpris.py fakes
# the player. Panels needing the system bus (Wi-Fi/Bluetooth tiles) stay empty.
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp

mkdir -p /tmp/bin
cat > /tmp/bin/pactl <<'EOF'
#!/bin/sh
case "$1" in
  get-sink-volume) echo "Volume: front-left: 32768 /  42% / -18.06 dB,   front-right: 32768 /  42% / -18.06 dB" ;;
  get-sink-mute)   echo "Mute: no" ;;
  get-default-sink) echo "sandbox-sink" ;;
  list) echo "[]" ;;
  *) exit 0 ;;
esac
EOF
cat > /tmp/bin/brightnessctl <<'EOF'
#!/bin/sh
case "$1" in
  -m) echo "intel_backlight,backlight,12000,65%,24000" ;;
  *) exit 0 ;;
esac
EOF
chmod +x /tmp/bin/pactl /tmp/bin/brightnessctl
PATH="/tmp/bin:$PATH"; export PATH

# --- wallpaper: yours (tools/liquid_wall.sh), else stripes so bending shows ---
wall() {          # $1 = real | busy
  if [ "$1" = real ] && [ -f /tmp/out/wall-real.png ]; then
    cp /tmp/out/wall-real.png /tmp/wall.png
  else
    python3 - <<'PY'
import cairo, math
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 1920, 1080)
c = cairo.Context(s)
g = cairo.LinearGradient(0, 0, 1920, 1080)
g.add_color_stop_rgb(0, 0.10, 0.20, 0.55); g.add_color_stop_rgb(0.5, 0.75, 0.25, 0.55); g.add_color_stop_rgb(1, 0.98, 0.65, 0.20)
c.set_source(g); c.paint()
for i in range(40):
    c.set_source_rgba(1, 1, 1, 0.18 if i % 2 else 0.05)
    c.rectangle(i * 48, 0, 20, 1080); c.fill()
for x, y, r, col in ((1650, 160, 140, (0.2, 0.9, 0.6)), (300, 60, 90, (1, 0.9, 0.2)), (1200, 330, 110, (0.3, 0.6, 1))):
    c.set_source_rgb(*col); c.arc(x, y, r, 0, 2 * math.pi); c.fill()
c.select_font_face("Sans", 0, 1); c.set_font_size(54); c.set_source_rgb(1, 1, 1)
c.move_to(700, 90); c.show_text("swayctl liquid glass")
s.write_to_png("/tmp/wall.png")
PY
    if [ "$1" = real ]; then echo "liquid_shot: no tools/out/wall-real.png - using stripes" >&2; fi
  fi
  swaymsg 'output * bg /tmp/wall.png fill' >/dev/null
}

# config.json + style.css + effects.sh for one glass state, from the modules
gen() {
  python3 - "$1" <<'PY'
import json, pathlib, subprocess, sys
sys.path.insert(0, "/home/repo")
from swayctl_center import themes
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule
from swayctl_center.modules.effects import EffectsModule

store = pathlib.Path("/tmp/out/liquid-config.json")
if not store.exists():
    sys.exit("run tools/liquid_wall.sh on the host first (tools/out/liquid-config.json missing)")
cfg = json.loads(store.read_text())
v = cfg["values"]
v["effects"]["glass"] = sys.argv[1] == "glass"
theme = themes.BUILTIN["dark" if cfg.get("dark") else "light"]
live = json.loads(subprocess.check_output(["swaymsg", "-t", "get_version"]))
ctx = Context(pathlib.Path("/tmp/out"), values=v, theme=theme, live=live)

d = pathlib.Path("/tmp/bar"); d.mkdir(exist_ok=True)
conf = BarModule().native_config(v["bar"], ctx)
if conf["backdrop"].get("image"):
    conf["backdrop"]["image"] = "/tmp/out/wall-real.png"
(d / "config.json").write_text(json.dumps(conf, ensure_ascii=False, indent=1))
# the stylesheet exactly as BarModule.files() ships it (look + adaptive ink +
# module sizes from bar.height)
(d / "style.css").write_text(BarModule().files(v["bar"] | {"program": "swayctl-bar"}, ctx)["style.css"])
cmds = EffectsModule().commands("effects", v["effects"], None, ctx)
# sway errors on namespaces that aren't up ("No matching node.") - tolerated
# in the real app too (EffectsModule.tolerated_errors)
(d / "effects.sh").write_text("".join(
    f"swaymsg '{c}' >/dev/null 2>>/tmp/bar/effects.err || true\n" for c in cmds))
print(f"liquid_shot[{sys.argv[1]}]: {len(cmds)} compositor commands, "
      f"features={live.get('swayctl_features')}")
PY
}

bin=/home/repo/swayctl-bar/target/release/swayctl-bar
python3 /home/repo/tools/fake_mpris.py 2>/dev/null &
shoot() {           # $1 = plain|glass, $2 = file prefix
  gen "$1"
  sh /tmp/bar/effects.sh
  $bin --config-dir /tmp/bar 2>/tmp/out/$2-$1-bar.log &
  pid=$!
  sleep 2
  sh /tmp/bar/effects.sh            # surfaces made after the first pass
  grim -g "0,0 1920x70" /tmp/out/$2-$1-bar.png
  $bin osd volume-up; sleep 0.35
  grim -g "760,900 400x140" /tmp/out/$2-$1-osd.png
  $bin quick; sleep 1.2
  grim -g "1100,0 820x560" /tmp/out/$2-$1-quick.png
  kill $pid; sleep 0.6
}
wall real
shoot plain liquid
shoot glass liquid
# structure behind the glass: refraction is invisible on a white wallpaper
wall busy
shoot glass liquid-busy
echo "liquid_shot: tools/out/liquid-{plain,glass}-*.png, liquid-busy-glass-*.png"

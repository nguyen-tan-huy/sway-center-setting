#!/bin/sh
# Bar + Quick Settings over a busy wallpaper, glass off and on, to judge the
# effect. tools/sandbox.sh --fx /home/repo/tools/glass_shot.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp
python3 - <<'PY'
import cairo, math
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 1920, 1080)
c = cairo.Context(s)
g = cairo.LinearGradient(0, 0, 1920, 1080)
g.add_color_stop_rgb(0, 0.10, 0.20, 0.55); g.add_color_stop_rgb(0.5, 0.75, 0.25, 0.55); g.add_color_stop_rgb(1, 0.98, 0.65, 0.20)
c.set_source(g); c.paint()
for i in range(40):  # stripes and circles so bending shows
    c.set_source_rgba(1, 1, 1, 0.18 if i % 2 else 0.05)
    c.rectangle(i * 48, 0, 20, 1080); c.fill()
for x, y, r, col in ((1650, 160, 140, (0.2, 0.9, 0.6)), (300, 60, 90, (1, 0.9, 0.2)), (1200, 330, 110, (0.3, 0.6, 1))):
    c.set_source_rgb(*col); c.arc(x, y, r, 0, 2 * math.pi); c.fill()
c.select_font_face("Sans", 0, 1); c.set_font_size(54); c.set_source_rgb(1, 1, 1)
c.move_to(700, 30 + 60); c.show_text("swayctl liquid glass")
s.write_to_png("/tmp/wall.png")
PY
swaymsg 'output * bg /tmp/wall.png fill' >/dev/null
mkdir -p bar
cat > bar/config.json <<'JSON'
{"modules_left": ["workspaces", "mode"], "modules_center": ["clock"], "modules_right": ["status"],
 "margins": [8, 8, 0, 8], "height": 38}
JSON
python3 /home/repo/tools/fake_mpris.py 2>/dev/null &
python3 - <<'PY'
import sys; sys.path.insert(0, "/home/repo")
from swayctl_center import themes
from swayctl_center.modules.components import BarModule
from swayctl_center.modules import Context
from swayctl_center import schema
for glass in (False, True):
    v = schema.defaults(); v["appearance"]["style"] = "modern"; v["effects"]["glass"] = glass
    v["effects"]["glass_opacity"] = int(__import__("os").environ.get("TINT", 50))
    ctx = Context(__import__("pathlib").Path("/tmp/app"), values=v,
                  theme=themes.BUILTIN[themes.LEGACY.get("modern-dark", "dark")])
    css = BarModule().native_css(ctx, ctx.theme)
    open(f"/tmp/style-{'glass' if glass else 'plain'}.css", "w").write(css)
PY
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
fx() { for ns in swayctl-bar swayctl-quick swayctl-osd; do for e in "$@"; do swaymsg layer_effects "$ns" "$e" >/dev/null; done; done; }
# Quick Settings is shaped glass: the panel is invisible, each control a pane
quick_shaped() { for e in "blur_ignore_transparent enable" "shadows disable"; do swaymsg layer_effects swayctl-quick "$e" >/dev/null; done; }
for mode in plain glass; do
  cp /tmp/style-$mode.css bar/style.css
  fx reset "blur enable" "blur_ignore_transparent enable" "shadows disable"
  swaymsg layer_effects swayctl-osd "shadows enable" >/dev/null
  swaymsg layer_effects swayctl-bar "corner_radius 14" >/dev/null
  swaymsg layer_effects swayctl-quick "corner_radius 20" >/dev/null
  swaymsg layer_effects swayctl-osd "corner_radius 999" >/dev/null
  if [ $mode = glass ]; then
    swaymsg "blur_saturation 1.4; blur_brightness 1.08; blur_passes 0; blur_radius 0" >/dev/null
    # the Liquid glass knobs: the same settings effects.py sends (schema
    # defaults here) so this harness can never drift from the compositor.
    python3 - <<'PY' > /tmp/lens.sh
import sys; sys.path.insert(0, "/home/repo")
from swayctl_center import schema
eff = schema.defaults()["effects"]
tune = ' '.join('"%s %g"' % (k, eff[k]) for k in
                ("glass_refraction", "glass_highlight", "glass_blur",
                 "glass_edge", "glass_thickness", "glass_chroma"))
for ns in ("swayctl-bar", "swayctl-quick", "swayctl-osd"):
    print('swaymsg layer_effects "%s" "glass enable" "blur_ignore_transparent enable" %s >/dev/null'
          % (ns, tune))
print('swaymsg layer_effects swayctl-bar "blur_ignore_transparent enable" >/dev/null')
PY
    . /tmp/lens.sh
  fi
  $bin --config-dir /tmp/bar 2>/tmp/out/glass-bar.log &
  pid=$!
  sleep 2
  $bin quick
  sleep 0.07
  grim -g "1100,0 820x560" /tmp/out/glass-$mode-opening.png
  sleep 3   # let the panel finish sliding: mid-animation positions dwarf shader deltas
  grim -g "1100,0 820x560" /tmp/out/glass-$mode.png
  grim -g "0,0 1920x70" /tmp/out/glass-$mode-bar.png
  kill $pid; sleep 0.5
done
echo done

#!/bin/sh
# GPU cost of a liquid glass window whose content changes a little every
# frame (typing, a clock): a clear window of static glass pills, one label
# rewritten each frame, at the user's real mode (3072x1920, scale 2) over a
# busy wallpaper. swayctl-fx logs each frame's GPU time and redrawn pixels
# (SWAY_FRAME_TIMES); compare the kept-backdrop glass against the old path:
#   SWAY_FRAME_TIMES=/tmp/out/gcp-on.log tools/sandbox.sh --fx /home/repo/tools/glass_cache_probe.sh
#   WLR_SCENE_GLASS_CACHE=0 SWAY_FRAME_TIMES=/tmp/out/gcp-off.log tools/sandbox.sh --fx /home/repo/tools/glass_cache_probe.sh
# MODE=scroll: every pill moves each frame instead (the whole window redraws)
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
trap 'cp /tmp/sway.log /tmp/out/gcp-sway.log 2>/dev/null || true' EXIT
cd /tmp
swaymsg 'output HEADLESS-1 mode 3072x1920; output HEADLESS-1 scale 2' >/dev/null
python3 - <<'PY'
import cairo, math
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 3072, 1920)
c = cairo.Context(s)
g = cairo.LinearGradient(0, 0, 3072, 1920)
g.add_color_stop_rgb(0, 0.10, 0.20, 0.55); g.add_color_stop_rgb(0.5, 0.95, 0.85, 0.75); g.add_color_stop_rgb(1, 0.98, 0.65, 0.20)
c.set_source(g); c.paint()
for i in range(64):
    c.set_source_rgba(1, 1, 1, 0.18 if i % 2 else 0.05)
    c.rectangle(i * 48, 0, 20, 1920); c.fill()
for x, y, r, col in ((2650, 260, 190, (0.2, 0.9, 0.6)), (500, 1110, 330, (1, 0.9, 0.2)), (1900, 560, 160, (0.3, 0.6, 1))):
    c.set_source_rgb(*col); c.arc(x, y, r, 0, 2 * math.pi); c.fill()
s.write_to_png("/tmp/wall.png")
PY
swaymsg 'output * bg /tmp/wall.png fill' >/dev/null
swaymsg "blur_passes ${BLUR_PASSES:-0}; blur_radius ${BLUR_RADIUS:-0}" >/dev/null
python3 - <<'PY' > /tmp/glass.cmd
import sys; sys.path.insert(0, "/home/repo")
from swayctl_center import schema
e = schema.defaults()["effects"]
import os
for k in list(e):
    v = os.environ.get(k.upper())
    if v is not None:
        e[k] = type(e[k])(float(v)) if not isinstance(e[k], bool) else v == "1"
print('[title="glassprobe"] floating enable, resize set 1400 900, move position 40 40, border none, '
      'glass enable, glass refraction %d, glass blur %d, glass highlight %g, glass edge %d, '
      'glass thickness %d, glass chroma %g' % (e["glass_refraction"], e["glass_blur"], e["glass_highlight"],
      e["glass_edge"], e["glass_thickness"], e["glass_chroma"]))
PY
python3 - <<'PY' &
import gi, os, time
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
GLib.set_prgname("glassprobe")
loop = GLib.MainLoop()
win = Gtk.Window(title="glassprobe")
win.set_decorated(False)
win.set_default_size(1400, 900)
prov = Gtk.CssProvider()
prov.load_from_string("""
window { background: none; }
.pill { background: alpha(white, 0.06); border-radius: 18px; padding: 10px 16px; color: white; font-size: 15px; }
.tick { background: alpha(white, 0.06); border-radius: 18px; padding: 10px 16px; color: white; font-size: 15px; }
""" + ("""
.pill, .tick { color: #FF00FE; }
""" if os.environ.get("MODE") == "ink" else ""))
Gtk.StyleContext.add_provider_for_display(win.get_display(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
scroll = os.environ.get("MODE") == "scroll"
col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_start=30, margin_top=30)
pills = []
for i in range(12):
    text = "Tin nhắn số %d — một dòng chữ trên kính, đứng yên" % i
    if os.environ.get("MODE") == "ink":
        text = ("Chữ màu khoá đi từ nền tối sang nền sáng · %d · " % i) * 3
    l = Gtk.Label(label=text, xalign=0, halign=Gtk.Align.START, wrap=True, max_width_chars=150)
    l.add_css_class("pill")
    col.append(l)
    pills.append(l)
tick = Gtk.Label(label="", xalign=0, halign=Gtk.Align.START)
tick.add_css_class("tick")
col.append(tick)
win.set_child(col)
n = [0]
def on_tick(w, clock):
    n[0] += 1
    tick.set_label("đang gõ %06d %s" % (n[0], "▌" if n[0] % 2 else " "))
    if scroll:
        col.set_margin_top(30 + (n[0] % 60))
    return True
win.add_tick_callback(on_tick)
win.present()
GLib.timeout_add_seconds(30, loop.quit)
loop.run()
PY
if [ "${MODE:-}" = under ]; then
# a window under the glass with a box moving behind it for 3 s, then still:
# the glass must show where it ended, not where it was when last copied
python3 - <<'PY2' &
import gi, time
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
GLib.set_prgname("under")
loop = GLib.MainLoop()
win = Gtk.Window(title="under")
win.set_default_size(1400, 900)
t0 = time.monotonic()
def draw(area, cr, w, h):
    cr.set_source_rgb(0.1, 0.1, 0.15); cr.paint()
    t = min(time.monotonic() - t0, 3.0)
    x = 50 + (t / 3.0) * 900
    cr.set_source_rgb(0.95, 0.2, 0.3); cr.rectangle(x, 120, 260, 600); cr.fill()
da = Gtk.DrawingArea(); da.set_draw_func(draw)
def tick(w, clock):
    w.queue_draw()
    return time.monotonic() - t0 < 3.2
da.add_tick_callback(tick)
win.set_child(da); win.present()
GLib.timeout_add_seconds(30, loop.quit)
loop.run()
PY2
sleep 1
swaymsg '[title="under"] floating enable, resize set 1400 900, move position 40 40, border none' >/dev/null
fi
sleep 1.5
swaymsg "$(cat /tmp/glass.cmd)" >/dev/null
[ "${MODE:-}" = ink ] && swaymsg '[title="glassprobe"] glass text auto' >/dev/null
if [ "${MODE:-}" = under ]; then
  sleep 4   # the box has stopped
  swaymsg '[title="glassprobe"] move position 140 90' >/dev/null
  sleep 0.5
  swaymsg '[title="glassprobe"] move position 40 40' >/dev/null
fi
sleep 1
# measure: only the frames from here on
: > "${SWAY_FRAME_TIMES:-/tmp/out/gcp.log}" 2>/dev/null || true
sleep 6
grim /tmp/out/gcp-shot.png 2>/dev/null || true
python3 - "${SWAY_FRAME_TIMES:-/tmp/out/gcp.log}" <<'PY'
import statistics, sys
rows = []
for line in open(sys.argv[1]):
    parts = line.split()
    if len(parts) == 3 and parts[1] != "-1":
        rows.append((int(parts[1]), int(parts[2])))
if not rows:
    print("no frames logged"); sys.exit(0)
gpu = sorted(r[0] for r in rows)
dmg = sorted(r[1] for r in rows)
p = lambda xs, q: xs[min(len(xs) - 1, int(len(xs) * q))]
print("frames=%d gpu_us median=%d p95=%d max=%d  damage_px median=%d p95=%d" % (
    len(rows), p(gpu, .5), p(gpu, .95), gpu[-1], p(dmg, .5), p(dmg, .95)))
PY

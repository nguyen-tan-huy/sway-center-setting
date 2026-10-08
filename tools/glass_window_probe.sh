#!/bin/sh
# GPU cost of a liquid glass *window* that redraws itself every frame — the
# ChoSua case (a Matrix client scrolling its timeline): a transparent window
# that draws one big card plus a few input pills, all shaped glass off the
# window's own alpha, at the user's real mode (3072x1920, scale 2) over a
# still wallpaper. The window repaints at the frame clock; its fps and the
# GPU busy % are the numbers to compare when the glass pipeline changes.
#   tools/sandbox.sh --fx /home/repo/tools/glass_window_probe.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
trap 'cp /tmp/sway.log /tmp/out/glass-window-sway.log 2>/dev/null || true' EXIT
cd /tmp
swaymsg 'output HEADLESS-1 mode 3072x1920; output HEADLESS-1 scale 2' >/dev/null
python3 - <<'PY'
import cairo, math
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 3072, 1920)
c = cairo.Context(s)
g = cairo.LinearGradient(0, 0, 3072, 1920)
g.add_color_stop_rgb(0, 0.10, 0.20, 0.55); g.add_color_stop_rgb(0.5, 0.75, 0.25, 0.55); g.add_color_stop_rgb(1, 0.98, 0.65, 0.20)
c.set_source(g); c.paint()
for i in range(64):
    c.set_source_rgba(1, 1, 1, 0.18 if i % 2 else 0.05)
    c.rectangle(i * 48, 0, 20, 1920); c.fill()
for x, y, r, col in ((2650, 260, 190, (0.2, 0.9, 0.6)), (500, 1110, 330, (1, 0.9, 0.2)), (1900, 560, 160, (0.3, 0.6, 1))):
    c.set_source_rgb(*col); c.arc(x, y, r, 0, 2 * math.pi); c.fill()
s.write_to_png("/tmp/wall.png")
PY
swaymsg 'output * bg /tmp/wall.png fill' >/dev/null
python3 - <<'PY' > /tmp/glass.cmd
import sys; sys.path.insert(0, "/home/repo")
from swayctl_center import schema
e = schema.defaults()["effects"]
# GLASS_<KEY>=value overrides a default (e.g. GLASS_REFRACTION=140 to try a user's settings)
import os
for k in list(e):
    v = os.environ.get(k.upper())
    if v is not None:
        e[k] = type(e[k])(float(v)) if not isinstance(e[k], bool) else v == "1"
print('[app_id="glassprobe"] floating enable, resize set 1100 860, move position 200 60, border none, '
      'glass enable, glass refraction %d, glass blur %d, glass highlight %g, glass edge %d, '
      'glass thickness %d, glass chroma %g' % (e["glass_refraction"], e["glass_blur"],
      e["glass_highlight"], e["glass_edge"], e["glass_thickness"], e["glass_chroma"]))
PY
python3 - <<'PY' &
import gi, math, os, time
open("/tmp/app.pid", "w").write(str(os.getpid()))
GLib_ = __import__("gi.repository.GLib", fromlist=["GLib"]); GLib_.set_prgname("glassprobe")
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
app_loop = GLib.MainLoop()
win = Gtk.Window(title="glassprobe")
win.set_decorated(False)
win.set_default_size(1100, 860)
prov = Gtk.CssProvider()
prov.load_from_string("window { background-color: transparent; }")
Gtk.StyleContext.add_provider_for_display(win.get_display(), prov,
                                          Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
def rounded(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()
frames = [0]
def draw(area, cr, w, h):
    frames[0] += 1
    # the card: ChoSua's faint fill (any alpha is glass)
    # CARD=0: no card, every pill its own pane on a clear window (ChoSua's
    # message bubbles)
    if os.environ.get("CARD", "1") != "0":
        rounded(cr, 20, 20, w - 40, h - 40, 28)
        cr.set_source_rgba(1, 1, 1, 0.06); cr.fill()
    # a scrolling timeline inside it: rows of pills moving up every frame
    off = (time.monotonic() * 240) % 90
    for i in range(10):
        y = 60 + i * 90 - off
        # a faint sliver above each pill (a shadow / text halo's few % of
        # alpha): glass must not smear across it
        cr.rectangle(80, y - 9, 300, 3)
        cr.set_source_rgba(1, 1, 1, 0.012); cr.fill()
        rounded(cr, 60, y, w - 120, 64, 22)
        cr.set_source_rgba(1, 1, 1, 0.10); cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.45); cr.set_line_width(2); cr.stroke()
        cr.set_source_rgba(1, 1, 1, 0.9); cr.move_to(90, y + 40); cr.set_font_size(22)
        cr.show_text("message %d  %.3f" % (i, time.monotonic()))
da = Gtk.DrawingArea()
da.set_draw_func(draw)
def tick(widget, clock):
    widget.queue_draw()
    return True
da.add_tick_callback(tick)
win.set_child(da)
win.set_application = None
win.present()
def report():
    open("/tmp/frames", "w").write(str(frames[0]))
    return True
GLib.timeout_add(100, report)
GLib.timeout_add_seconds(120, app_loop.quit)
app_loop.run()
PY
apppid=$!
# GTK sets app_id from the program name; give the rule a moment, then apply by title
sleep 1.5
swaymsg "$(sed 's/app_id="glassprobe"/title="glassprobe"/' /tmp/glass.cmd)" >/dev/null
sleep 1
python3 - "$@" <<'PY'
import statistics, subprocess, sys, threading, time

def gpu_busy():
    for card in ("card0", "card1"):
        try:
            return float(open("/sys/class/drm/%s/device/gpu_busy_percent" % card).read())
        except OSError:
            pass
    return None

def frames():
    try:
        return int(open("/tmp/frames").read())
    except (OSError, ValueError):
        return 0

def probe(label, secs=4.0):
    gpus = []
    f0, t0 = frames(), time.monotonic()
    while time.monotonic() - t0 < secs:
        b = gpu_busy()
        if b is not None:
            gpus.append(b)
        time.sleep(0.05)
    fps = (frames() - f0) / (time.monotonic() - t0)
    gpu = " gpu=%.0f%%" % statistics.mean(gpus) if gpus else ""
    print("PROBE %-14s fps=%.1f%s" % (label, fps, gpu))
    sys.stdout.flush()

def glass(on):
    subprocess.run(["swaymsg", '[title="glassprobe"] glass %s' % ("enable" if on else "disable")],
                   check=False, stdout=subprocess.DEVNULL)

probe("glass")
subprocess.run(["grim", "/tmp/out/glass-window.png"], check=False)
glass(False); time.sleep(0.5)
probe("noglass")
glass(True); time.sleep(0.5)
probe("glass again")
# the app asks what's behind it to pick its text (GET_BACKDROP), as ChoSua does
stop = [False]
def asker():
    while not stop[0]:
        subprocess.run(["/home/fx/swayfx/build/swaymsg/swaymsg", "-r", "-t", "get_backdrop",
                        '{"app_id":"glassprobe","cols":4,"rows":4}'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.25)
import threading
th = threading.Thread(target=asker, daemon=True); th.start()
probe("glass + backdrop asks")
stop[0] = True; th.join()
# the app holds still while what's behind it changes (a video, a terminal):
# its glass is redrawn every frame but its shape never changes
app = open("/tmp/app.pid").read().strip()
subprocess.run(["kill", "-STOP", app], check=False)
term = subprocess.Popen(["foot", "-e", "sh", "-c",
    'while :; do printf "\\033[H\\033[2J"; seq 1 400 | sed "s/^/$(date +%N) /"; sleep 0.016; done'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.5)
probe("still app, busy backdrop")
subprocess.run(["grim", "/tmp/out/glass-window-backdrop.png"], check=False)
term.kill()
subprocess.run(["kill", "-CONT", app], check=False)
PY
kill "$apppid" 2>/dev/null || true
echo done

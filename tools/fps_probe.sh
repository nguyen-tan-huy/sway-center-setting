#!/bin/sh
# Frame cost with liquid glass at the user's real mode (3072x1920, scale 2):
# bar + Quick Settings + a floating window of ~24 small glass panes, all over
# a fullscreen terminal painting its whole screen ~60x/s — the damage runs
# *behind* the glass, so every frame re-shades it. Three phases attribute the
# cost: A no damage (grim+readback floor), C damage with glass on, B the same
# damage with glass off. grim round-trips wait for a fresh frame, so their
# duration tracks frame time — an A/B proxy when the shader changes.
#   tools/sandbox.sh --fx /home/repo/tools/fps_probe.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
# keep the compositor log even when a phase aborts the script
trap 'cp /tmp/sway.log /tmp/out/probe-sway.log 2>/dev/null || true' EXIT
cd /tmp
swaymsg 'output HEADLESS-1 mode 3072x1920; output HEADLESS-1 scale 2' >/dev/null
python3 - <<'PY'
import cairo, math
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 3072, 1920)
c = cairo.Context(s)
g = cairo.LinearGradient(0, 0, 3072, 1920)
g.add_color_stop_rgb(0, 0.10, 0.20, 0.55); g.add_color_stop_rgb(0.5, 0.75, 0.25, 0.55); g.add_color_stop_rgb(1, 0.98, 0.65, 0.20)
c.set_source(g); c.paint()
for i in range(64):  # stripes and circles so bending shows
    c.set_source_rgba(1, 1, 1, 0.18 if i % 2 else 0.05)
    c.rectangle(i * 48, 0, 20, 1920); c.fill()
for x, y, r, col in ((2650, 260, 190, (0.2, 0.9, 0.6)), (500, 110, 130, (1, 0.9, 0.2)), (1900, 560, 160, (0.3, 0.6, 1))):
    c.set_source_rgb(*col); c.arc(x, y, r, 0, 2 * math.pi); c.fill()
c.select_font_face("Sans", 0, 1); c.set_font_size(72); c.set_source_rgb(1, 1, 1)
c.move_to(1100, 90); c.show_text("swayctl liquid glass")
s.write_to_png("/tmp/wall.png")
PY
swaymsg 'output * bg /tmp/wall.png fill' >/dev/null
# fullscreen damage source first, so the glass sits on top of the churn
foot -e sh -c 'while :; do printf "\033[H\033[2J%s" "$(date +%s.%N)"; sleep 0.016; done' >/dev/null 2>&1 &
footpid=$!
sleep 0.7
# the "many liquid glass panes" window: transparent GTK4 box of 24 pills
# (Cairo-drawn: widget themes ignore background-color rules, and the mask
# only needs the pills' own alpha)
python3 - <<'PY' &
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
loop = GLib.MainLoop()
win = Gtk.Window(title="glasspills")
win.set_decorated(False)   # no titlebar alpha: PILLS=0 must draw nothing
win.set_default_size(1440, 900)
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

def pill(area, cr, w, h):
    rounded(cr, 4, 4, w - 8, h - 8, 26)
    cr.set_source_rgba(1, 1, 1, 0.10)
    cr.fill_preserve()
    cr.set_source_rgba(1, 1, 1, 0.45)
    cr.set_line_width(2.5)
    cr.stroke()

grid = Gtk.Grid()
grid.set_column_homogeneous(True)
grid.set_row_homogeneous(True)
# PILLS=0 leaves the window fully transparent: the glass pipeline still runs
# (backdrop copy + stencil) but the shader draws no pane fragments. An EMPTY
# grid would never map (GTK skips 0x0 surfaces), so keep one full-size blank
# drawing area.
def blank(area, cr, w, h):
    pass

n = int(__import__("os").environ.get("PILLS", "24"))
if n == 0:
    da = Gtk.DrawingArea()
    da.set_content_width(1440)
    da.set_content_height(900)
    da.set_draw_func(blank)
    grid.attach(da, 0, 0, 1, 1)
for i in range(n):
    da = Gtk.DrawingArea()
    da.set_content_width(210)
    da.set_content_height(170)
    da.set_margin_start(8); da.set_margin_end(8)
    da.set_margin_top(8); da.set_margin_bottom(8)
    da.set_draw_func(pill)
    grid.attach(da, i % 6, i // 6, 1, 1)
win.set_child(grid)
win.connect("destroy", lambda *_: loop.quit())
win.connect("close-request", lambda *_: (loop.quit(), True)[1])
win.present()
GLib.timeout_add_seconds(600, loop.quit)
loop.run()
PY
glasspid=$!
sleep 1.5
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
v = schema.defaults(); v["appearance"]["style"] = "modern"; v["effects"]["glass"] = True
v["effects"]["glass_opacity"] = int(__import__("os").environ.get("TINT", 50))
ctx = Context(__import__("pathlib").Path("/tmp/app"), values=v,
              theme=themes.BUILTIN[themes.LEGACY.get("modern-dark", "dark")])
css = BarModule().native_css(ctx, ctx.theme)
open("/tmp/style-glass.css", "w").write(css)
PY
cp /tmp/style-glass.css bar/style.css
fx() { for ns in swayctl-bar swayctl-quick swayctl-osd; do for e in "$@"; do swaymsg layer_effects "$ns" "$e" >/dev/null; done; done; }
fx reset "blur enable" "blur_ignore_transparent enable" "shadows disable"
swaymsg layer_effects swayctl-osd "shadows enable" >/dev/null
swaymsg layer_effects swayctl-bar "corner_radius 14" >/dev/null
swaymsg layer_effects swayctl-quick "corner_radius 20" >/dev/null
swaymsg layer_effects swayctl-osd "corner_radius 999" >/dev/null
swaymsg "blur_saturation 1.4; blur_brightness 1.08; blur_passes 0; blur_radius 0" >/dev/null
# the Liquid glass knobs: the same settings effects.py sends (schema defaults
# here) so this harness can never drift from the compositor.
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
# the pill window: shaped glass off the window's own alpha (like the settings app)
win = 'swaymsg \'[title="glasspills"] floating enable, resize set 1440 900, move position 48 100, ' \
      'glass enable, glass refraction %g, glass highlight %g, glass edge %g, glass thickness %g, glass chroma %g\'' % (
          eff["glass_refraction"], eff["glass_highlight"], eff["glass_edge"],
          eff["glass_thickness"], eff["glass_chroma"])
print(win)
PY
. /tmp/lens.sh
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir /tmp/bar 2>/tmp/out/probe-bar.log &
pid=$!
sleep 2
$bin quick
sleep 1
python3 - "$@" <<'PY'
import glob, os, statistics, subprocess, sys, threading, time

def sway_pid():
    for comm in glob.glob("/proc/[0-9]*/comm"):
        try:
            if open(comm).read().strip() != "sway":
                continue
            pid = comm.split("/")[2]
            if "/home/fx/" in open(f"/proc/{pid}/cmdline", "rb").read().decode(errors="replace"):
                return int(pid)
        except OSError:
            pass
    return None

def cpu_ms(pid):
    with open(f"/proc/{pid}/stat") as f:
        p = f.read().split()
    ticks = int(p[13]) + int(p[14])
    return ticks * 1000 / os.sysconf("SC_CLK_TCK")

def gpu_busy():
    try:
        return float(open("/sys/class/drm/card1/device/gpu_busy_percent").read())
    except OSError:
        return None

class Sampler(threading.Thread):
    def __init__(self, pid):
        super().__init__(daemon=True)
        self.pid = pid
        self.gpus, self.stop = [], False

    def run(self):
        while not self.stop:
            b = gpu_busy()
            if b is not None:
                self.gpus.append(b)
            time.sleep(0.05)

def probe(label, pid, n=12):
    ts = []
    cpu0 = cpu_ms(pid) if pid else None
    smp = Sampler(pid); smp.start()
    for _ in range(n):
        t0 = time.monotonic()
        r = subprocess.run(["grim", "-g", "0,0 1920x700", "/tmp/out/probe.png"])
        dt = (time.monotonic() - t0) * 1000
        if r.returncode == 0:
            ts.append(dt)
        else:
            break
    smp.stop = True; smp.join(timeout=1)
    if not ts:
        print("PROBE %-22s FAILED" % label)
        sys.stdout.flush()
        return
    m = statistics.mean(ts)
    gpu = (" gpu=%.0f%%" % (statistics.mean(smp.gpus),)) if smp.gpus else ""
    cpu = (" cpu=%.0fms" % ((cpu_ms(pid) - cpu0) / len(ts))) if cpu0 is not None else ""
    print("PROBE %-22s avg=%.1fms min=%.1f%s%s (n=%d)"
          % (label, m, min(ts), gpu, cpu, len(ts)))
    sys.stdout.flush()

def win_glass(on):
    subprocess.run(["swaymsg", '[title="glasspills"] glass %s' % ("enable" if on else "disable")],
                   check=False, stdout=subprocess.DEVNULL)

mode = sys.argv[1] if len(sys.argv) > 1 else "all"
pid = sway_pid()
if mode in ("all", "idle"):
    subprocess.run(["pkill", "-STOP", "-f", "while :; do printf"], check=False)
    probe("A idle+glass", pid)
    subprocess.run(["pkill", "-CONT", "-f", "while :; do printf"], check=False)
    time.sleep(0.5)
if mode in ("all", "glass"):
    probe("C damage+glass", pid)
    subprocess.run(["grim", "-g", "0,0 3072x1920", "/tmp/out/probe-scene-C.png"],
                   check=False)
if mode in ("all", "noglass"):
    for ns in ("swayctl-bar", "swayctl-quick", "swayctl-osd"):
        subprocess.run(["swaymsg", "layer_effects", ns, "glass disable"], check=False,
                       stdout=subprocess.DEVNULL)
    win_glass(False)
    time.sleep(0.5)
    probe("B damage+noglass", pid)
PY
kill "$pid" 2>/dev/null || true
kill "$glasspid" 2>/dev/null || true
kill "$footpid" 2>/dev/null || true
echo done

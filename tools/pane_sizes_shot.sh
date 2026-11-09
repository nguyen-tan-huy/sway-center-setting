#!/bin/sh
# Does a big pane bend at its rim like a small one? A pill, a card and a big sheet over a grid, with the one look.
#   tools/sandbox.sh --fx /home/repo/tools/pane_sizes_shot.sh   -> tools/out/ps-*.png
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
swaymsg 'output HEADLESS-1 mode 3072x1920; output HEADLESS-1 scale 2' >/dev/null
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/ps-daemon.log 2>&1 &
sleep 2.5
python3 -m swayctl_center set background.image /tmp/out/${WALL:-rim_grid.png} >/dev/null
sleep 3
L=$(python3 -c "from swayctl_center.glass import LOOK as l; print(l['refraction'], l['edge_share'], l['thickness'], l['chroma'], l['highlight'])")
set -- $L
swaymsg 'for_window [title="pane"] "floating enable, border none, shadows disable, glass enable, glass refraction '"$1"', glass blur 0, glass highlight '"$5"', glass edge 21, glass thickness '"$3"', glass chroma '"$4"', glass text none"' >/dev/null
cat > /tmp/pane.py <<'PY'
import sys, gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
w, h, r = (int(a) for a in sys.argv[1:4])
loop = GLib.MainLoop()
win = Gtk.Window(title="pane"); win.set_decorated(False); win.set_default_size(w + 40, h + 40)
prov = Gtk.CssProvider(); prov.load_from_string("window { background-color: transparent; }")
Gtk.StyleContext.add_provider_for_display(win.get_display(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
def draw(area, cr, ww, hh):
    cr.new_sub_path(); cr.arc(20+w-r, 20+r, r, -1.5708, 0); cr.arc(20+w-r, 20+h-r, r, 0, 1.5708)
    cr.arc(20+r, 20+h-r, r, 1.5708, 3.1416); cr.arc(20+r, 20+r, r, 3.1416, 4.7124); cr.close_path()
    cr.set_source_rgba(1, 1, 1, 0.04); cr.fill()       # the UI draws only the shape
da = Gtk.DrawingArea(); da.set_content_width(w+40); da.set_content_height(h+40); da.set_draw_func(draw)
win.set_child(da); win.present(); GLib.timeout_add_seconds(20, loop.quit); loop.run()
PY
shot() { python3 /tmp/pane.py "$2" "$3" "$4" >/dev/null 2>&1 & pp=$!; sleep 2.5
  swaymsg '[title="pane"] move position 400 100' >/dev/null 2>&1 || true; sleep 1
  grim -g "400,100 $(( $2 + 40 ))x$(( $3 + 40 ))" /tmp/out/ps-$1.png; kill $pp 2>/dev/null || true; sleep 0.8; }
shot pill 300 56 28
shot card 400 150 22
shot sheet 700 500 22

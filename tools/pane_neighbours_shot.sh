#!/bin/sh
# Do neighbouring glass panes change each other's refraction? One pill alone, then the same pill with a
# neighbour under it at a given gap (logical px); the first pill is compared pixel by pixel.
#   tools/sandbox.sh --fx /home/repo/tools/pane_neighbours_shot.sh   -> tools/out/pn-*.png
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
swaymsg 'output HEADLESS-1 mode 3072x1920; output HEADLESS-1 scale 2' >/dev/null
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/pn-daemon.log 2>&1 &
sleep 2.5
python3 -m swayctl_center set background.image /tmp/out/rim_grid.png >/dev/null
sleep 3
rules() { swaymsg 'for_window [title="pills"] "floating enable, border none, shadows disable, glass enable, glass refraction '"${REFR:-50}"', glass blur 0, glass highlight 0.9, glass edge '"${EDGE:-16}"', glass thickness 90, glass chroma '"${CHROMA:-0}"', glass text none"' >/dev/null; }
rules
cat > /tmp/pills.py <<'PY'
import sys, gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
gap = int(sys.argv[1]); count = int(sys.argv[2]); w, h = 300, 60
loop = GLib.MainLoop()
win = Gtk.Window(title="pills"); win.set_decorated(False); win.set_default_size(w + 40, 40 + count * (h + gap))
prov = Gtk.CssProvider(); prov.load_from_string("window { background-color: transparent; }")
Gtk.StyleContext.add_provider_for_display(win.get_display(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
def rounded(cr, x, y, ww, hh, r):
    cr.new_sub_path(); cr.arc(x+ww-r, y+r, r, -1.5708, 0); cr.arc(x+ww-r, y+hh-r, r, 0, 1.5708)
    cr.arc(x+r, y+hh-r, r, 1.5708, 3.1416); cr.arc(x+r, y+r, r, 3.1416, 4.7124); cr.close_path()
def draw(area, cr, ww, hh):
    for i in range(count):
        rounded(cr, 20, 20 + i*(h+gap), w, h, h/2)
        cr.set_source_rgba(1, 1, 1, 0.04); cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.88); cr.set_line_width(2); cr.stroke()
da = Gtk.DrawingArea(); da.set_content_width(w+40); da.set_content_height(40 + count*(h+gap)); da.set_draw_func(draw)
win.set_child(da); win.present(); GLib.timeout_add_seconds(30, loop.quit); loop.run()
PY
shot() { # tag gap count
  python3 /tmp/pills.py "$2" "$3" >/tmp/out/pn-app-$1.log 2>&1 &
  pp=$!; sleep 2.5
  swaymsg '[title="pills"] move position 400 100' >/dev/null 2>&1 || true; sleep 1
  swaymsg -t get_tree | python3 -c "import json,sys
def walk(n):
    if n.get('name')=='pills': print('$1 window rect', n['rect'], n.get('floating'))
    for c in n.get('nodes',[])+n.get('floating_nodes',[]): walk(c)
walk(json.load(sys.stdin))" >> /tmp/out/pn-tree.txt
  grim -g "380,80 380x360" /tmp/out/pn-$1.png
  kill $pp 2>/dev/null || true; sleep 0.8
}
shot alone 12 1
shot gap6 6 2
shot gap12 12 2
shot gap24 24 2
shot gap48 48 2

#!/bin/sh
# Tạm: test GTK cascade — .quick-footer button vs rule .on-dark x3 + tint-N.
# Present 1 cửa sổ rồi grim chụp lại (sandbox headless). Chạy qua:
#   tools/sandbox.sh --fx /home/repo/tools/gtk_cascade_probe.sh
set -eu
cat > /tmp/t.css <<'EOF'
.quick-footer button {
  background: rgb(255,0,0);
  color: rgb(255,0,0);
}
.on-dark.on-dark.on-dark.tint-10:not(.active):not(:selected) {
  background: linear-gradient(0deg, rgb(0,255,0), rgb(0,255,0));
  color: rgb(0,0,255);
}
EOF
cat > /tmp/t.py <<'EOF'
import sys, traceback
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib

loop = GLib.MainLoop()

def main():
    try:
        css = open("/tmp/t.css").read()
        p = Gtk.CssProvider()
        p.load_from_string(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        btn = Gtk.Button(label="X")
        for c in ("circular", "on-dark", "tint-10"):
            btn.add_css_class(c)
        btn.set_size_request(200, 70)
        footer = Gtk.Box()
        footer.add_css_class("quick-footer")
        footer.set_margin_top(40); footer.set_margin_start(40)
        footer.append(btn)
        win = Gtk.Window()
        win.set_child(footer)
        win.set_default_size(400, 160)
        win.present()
        print("window up", flush=True)
        GLib.timeout_add(2500, lambda: (loop.quit(), False)[1])
        loop.run()
    except Exception:
        traceback.print_exc()
        sys.exit(2)

main()
EOF
/usr/bin/python3 /tmp/t.py &
sleep 1.2
grim /tmp/out/gtk-cascade.png
wait
echo "probe done"

"""Fullscreen GTK window that logs every scroll event it receives as JSON
lines (t ms, dy, unit) to the file given; used by scroll_test.sh."""
import json
import sys
import time

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

out = open(sys.argv[1], "a", buffering=1)  # append: the test truncates it between runs
t0 = time.monotonic()


def on_scroll(ctrl, dx, dy):
    out.write(json.dumps({"t": round((time.monotonic() - t0) * 1000, 1), "dy": dy,
                          "unit": ctrl.get_unit().value_nick}) + "\n")
    return True


def on_end(_ctrl):
    out.write(json.dumps({"t": round((time.monotonic() - t0) * 1000, 1), "end": True}) + "\n")


def activate(app):
    win = Gtk.ApplicationWindow(application=app, title="scroll-probe")
    ctrl = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
    ctrl.connect("scroll", on_scroll)
    ctrl.connect("scroll-end", on_end)
    win.add_controller(ctrl)
    win.set_child(Gtk.Label(label="scroll probe"))
    win.present()


app = Gtk.Application(application_id="io.github.huyhappy.ScrollProbe")
app.connect("activate", activate)
app.run([])

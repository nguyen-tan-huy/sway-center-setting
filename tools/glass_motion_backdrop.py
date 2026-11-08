#!/usr/bin/env python3
"""A window that repaints every frame with hard-edged moving colour blocks (what a playing video does to the
backdrop of a glass popup). Only for tools/glass_motion_check.sh, inside tools/sandbox.sh."""
import math, random, sys
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

SIZE = float(sys.argv[2]) if len(sys.argv) > 2 else 0.2


class Area(Gtk.DrawingArea):
    def __init__(self):
        super().__init__(hexpand=True, vexpand=True)
        self.t = 0.0
        random.seed(3)
        self.blocks = [(random.random(), random.random(), random.random() * SIZE + .01, random.random() * SIZE + .01,
                        random.random(), random.random(), random.random()) for _ in range(int(sys.argv[1]) if len(sys.argv) > 1 else 60)]
        self.set_draw_func(self.draw)
        self.add_tick_callback(self.tick)

    def tick(self, *_):
        # moves for STOP seconds (argv[3]; 0 = for ever), then stands still on a fixed frame
        stop = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
        if stop and self.t >= stop * 50 * 0.02:
            self.t = stop * 50 * 0.02
            self.queue_draw()
            return False
        self.t += 0.02
        self.queue_draw()
        return True

    def draw(self, _a, cr, w, h):
        cr.set_source_rgb(0.95, 0.95, 0.9); cr.paint()
        for i, (x, y, bw, bh, r, g, b) in enumerate(self.blocks):
            ox = (x + 0.15 * math.sin(self.t + i)) % 1.0
            oy = (y + 0.10 * math.cos(self.t * 0.8 + i)) % 1.0
            cr.set_source_rgb(r, g, b)
            cr.rectangle(ox * w, oy * h, bw * w, bh * h)
            cr.fill()

class App(Gtk.Application):
    def do_activate(self):
        w = Gtk.ApplicationWindow(application=self)
        w.set_child(Area())
        w.present()

App(application_id="local.motion").run([])

"""Shared helper for offloading blocking backend calls (subprocess, D-Bus, file
I/O) onto a background thread, so page reload()s never block the GTK main loop.

Without this, every page's reload() ran its subprocess/D-Bus calls directly on
the GTK thread via GLib.idle_add - that only delays *when* the call happens
(until after the window is shown), not *where* it runs, so the window still
freezes while any of those calls is in flight. With N pages doing this at
startup, the freezes stack up serially into the multi-second stall this fixes.
"""
import threading

from gi.repository import GLib


def run_async(work, on_done):
    """Run `work()` (no args, returns a plain value - must not touch GTK
    widgets) on a background thread. Once it finishes, `on_done(result)` runs
    on the GTK main thread via GLib.idle_add. If `work` raises, `on_done`
    receives the exception instance instead - check with isinstance(result,
    Exception) before treating it as real data."""
    def _worker():
        try:
            result = work()
        except Exception as e:
            result = e
        GLib.idle_add(on_done, result)

    threading.Thread(target=_worker, daemon=True).start()

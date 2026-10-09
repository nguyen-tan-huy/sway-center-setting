"""Keep a page current without a Refresh button: reload it when the service
behind it says something changed (NetworkManager / BlueZ PropertiesChanged on
the system bus, `pactl subscribe` for audio).

Changes come in bursts (a scan touches every access point), so they are
gathered for DEBOUNCE_MS and reload once. Nothing reloads while the page is
off screen; showing it again reloads if something changed meanwhile, and
`busy()` can hold a reload back (a password being typed into a row).
"""
import ctypes
import signal
import subprocess

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GioUnix", "2.0")
from gi.repository import Gio, GioUnix, GLib, Gtk

DEBOUNCE_MS = 600
# pactl subscribe facilities that change what the sound page shows ("client"
# events come from pactl itself, including our own reload's calls)
AUDIO_FACILITIES = (" sink ", " source ", " server", " card ")


def _die_with_parent():
    # pactl must not outlive the settings app (it never exits on its own)
    ctypes.CDLL(None).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG


class Live:
    def __init__(self, page: Gtk.Widget, reload, busy=lambda: False):
        self._page, self._reload, self._busy = page, reload, busy
        self._timer = 0
        self._stale = False
        self._subs: list[tuple[Gio.DBusConnection, int]] = []
        self._proc: subprocess.Popen | None = None
        page.connect("map", lambda *_: self._stale and self.changed())
        page.connect("destroy", lambda *_: self.stop())

    def dbus(self, sender: str) -> "Live":
        """Follow every PropertiesChanged/InterfacesAdded/Removed from `sender`."""
        try:
            conn = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error:
            return self
        for iface, member in (("org.freedesktop.DBus.Properties", "PropertiesChanged"),
                              ("org.freedesktop.DBus.ObjectManager", "InterfacesAdded"),
                              ("org.freedesktop.DBus.ObjectManager", "InterfacesRemoved"),
                              (None, "StateChanged")):
            sid = conn.signal_subscribe(sender, iface, member, None, None, Gio.DBusSignalFlags.NONE,
                                        lambda *_: self.changed())
            self._subs.append((conn, sid))
        return self

    def pactl(self) -> "Live":
        """Follow `pactl subscribe` (PulseAudio or PipeWire's pulse server)."""
        try:
            self._proc = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, preexec_fn=_die_with_parent)
        except OSError:
            return self
        stream = Gio.DataInputStream.new(GioUnix.InputStream.new(self._proc.stdout.fileno(), False))

        def on_line(s, res):
            try:
                line, _ = s.read_line_finish_utf8(res)
            except GLib.Error:
                return
            if line is None:
                return  # pactl ended (server gone)
            if any(f in line for f in AUDIO_FACILITIES):
                self.changed()
            s.read_line_async(GLib.PRIORITY_DEFAULT, None, on_line)

        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, on_line)
        return self

    def changed(self):
        if not self._page.get_mapped():
            self._stale = True
            return
        if not self._timer:
            self._timer = GLib.timeout_add(DEBOUNCE_MS, self._fire)

    def _fire(self):
        self._timer = 0
        if self._busy():
            self._timer = GLib.timeout_add(DEBOUNCE_MS, self._fire)
            return GLib.SOURCE_REMOVE
        self._stale = False
        self._reload()
        return GLib.SOURCE_REMOVE

    def stop(self):
        for conn, sid in self._subs:
            conn.signal_unsubscribe(sid)
        self._subs.clear()
        if self._proc:
            self._proc.terminate()
            self._proc = None

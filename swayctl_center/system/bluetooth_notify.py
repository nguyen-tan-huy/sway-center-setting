"""Pairing prompts as desktop notifications, with the Confirm / Cancel buttons
on the card (like blueman). Plugs into bluetooth_agent.Agent as its `ui`."""
import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

from .bluetooth_agent import Agent

NOTIFY = "org.freedesktop.Notifications"
TIMEOUT_MS = 60000
LEGACY_PIN = "0000"  # a notification can't take typing; this is what old gadgets expect


class NotifyUI:
    def __init__(self, session_bus: Gio.DBusConnection):
        self.bus = session_bus
        self._pending: dict[int, "callable"] = {}
        for sig in ("ActionInvoked", "NotificationClosed"):
            self.bus.signal_subscribe(NOTIFY, NOTIFY, sig, "/org/freedesktop/Notifications",
                                      None, Gio.DBusSignalFlags.NONE, self._on_signal)
        self.agent = Agent(self)

    def start(self):
        """Own the agent for as long as bluetoothd is on the bus."""
        Gio.bus_watch_name(Gio.BusType.SYSTEM, "org.bluez", Gio.BusNameWatcherFlags.NONE,
                           self._appeared, None)

    def _appeared(self, *_):
        try:
            self.agent.register()
        except Exception as e:  # noqa: BLE001 - bluez may be mid-start
            print(f"bluetooth agent: {e}")

    # ---- notification plumbing -------------------------------------------
    def _send(self, summary, body, actions, on_action, replace=0):
        try:
            res = self.bus.call_sync(
                NOTIFY, "/org/freedesktop/Notifications", NOTIFY, "Notify",
                GLib.Variant("(susssasa{sv}i)", (
                    "Bluetooth", replace, "bluetooth", summary, body, actions,
                    {"urgency": GLib.Variant("y", 2)}, TIMEOUT_MS)),
                None, Gio.DBusCallFlags.NONE, 2000, None)
        except GLib.Error:
            return 0
        nid = res.unpack()[0]
        if on_action:
            self._pending[nid] = on_action
        return nid

    def _on_signal(self, _c, _s, _p, _i, name, params):
        args = params.unpack()
        cb = self._pending.get(args[0])
        if cb is None:
            return
        if name == "ActionInvoked":
            self._pending.pop(args[0], None)
            cb(args[1])
        else:  # closed / expired / dismissed without an answer
            self._pending.pop(args[0], None)
            cb("cancel")

    def _close(self, nid):
        self._pending.pop(nid, None)
        try:
            self.bus.call_sync(NOTIFY, "/org/freedesktop/Notifications", NOTIFY, "CloseNotification",
                               GLib.Variant("(u)", (nid,)), None, Gio.DBusCallFlags.NONE, 2000, None)
        except GLib.Error:
            pass

    # ---- Agent ui ----------------------------------------------------------
    def confirm(self, name, code, done):
        if code:
            summary, body, ok = f"Pair with {name}?", f"Make sure {name} shows this code:\n{code}", "Pair"
        else:
            summary, body, ok = f"{name} wants to connect", "Allow this device?", "Allow"
        self._send(summary, body, ["yes", ok, "cancel", "Cancel"], lambda a: done(a == "yes"))

    def ask(self, name, numeric, done):
        # no text entry on a notification: legacy PIN for old devices, refuse passkey prompts
        done(None if numeric else LEGACY_PIN)

    def show(self, name, code):
        self._send(f"Pairing {name}", f"Type {code} on {name}, then press Enter", [], None)

    def cancel(self):
        pass

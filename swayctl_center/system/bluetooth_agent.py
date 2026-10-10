"""BlueZ pairing agent (org.bluez.Agent1) exported on the system bus.

Without an agent bluetoothd has nobody to ask when a device wants a passkey
confirmation / PIN, so pairing a new device just fails silently. This exports
the agent from the GTK process; every request is handed to `ui`, which answers
later (the D-Bus reply is deferred until the user decides).
"""
import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

from .bluetooth import BLUEZ, _bus

AGENT_PATH = "/org/swayctl/BluetoothAgent"
CAPABILITY = "KeyboardDisplay"

_XML = """
<node><interface name="org.bluez.Agent1">
  <method name="Release"/>
  <method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
  <method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
  <method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
  <method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
  <method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
  <method name="RequestAuthorization"><arg type="o" direction="in"/></method>
  <method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
  <method name="Cancel"/>
</interface></node>
"""

_DENIED = "org.bluez.Error.Rejected"


def device_name(path: str) -> str:
    try:
        v = _bus().call_sync(
            BLUEZ, path, "org.freedesktop.DBus.Properties", "Get",
            GLib.Variant("(ss)", ("org.bluez.Device1", "Alias")),
            None, Gio.DBusCallFlags.NONE, 2000, None)
        return v.unpack()[0]
    except GLib.Error:
        return path.rsplit("/", 1)[-1].removeprefix("dev_").replace("_", ":")


class Agent:
    """`ui` needs: confirm(title, body, done(bool)), ask(title, body, numeric,
    done(str|None)), show(title, body), cancel()."""

    def __init__(self, ui):
        self.ui = ui
        self._reg = None
        self._registered = False

    def register(self):
        bus = _bus()
        if self._reg is not None:
            bus.unregister_object(self._reg)
            self._reg = None
        info = Gio.DBusNodeInfo.new_for_xml(_XML).interfaces[0]
        self._reg = bus.register_object(AGENT_PATH, info, self._on_call, None, None)
        for method, args in (("RegisterAgent", (AGENT_PATH, CAPABILITY)), ("RequestDefaultAgent", (AGENT_PATH,))):
            bus.call_sync(
                BLUEZ, "/org/bluez", "org.bluez.AgentManager1", method,
                GLib.Variant("(os)" if len(args) == 2 else "(o)", args),
                None, Gio.DBusCallFlags.NONE, 2000, None)
        self._registered = True

    def unregister(self):
        bus = _bus()
        if self._registered:
            try:
                bus.call_sync(BLUEZ, "/org/bluez", "org.bluez.AgentManager1", "UnregisterAgent",
                              GLib.Variant("(o)", (AGENT_PATH,)), None, Gio.DBusCallFlags.NONE, 2000, None)
            except GLib.Error:
                pass
            self._registered = False
        if self._reg is not None:
            bus.unregister_object(self._reg)
            self._reg = None

    def _on_call(self, conn, sender, path, iface, method, params, inv):
        args = params.unpack()
        dev = device_name(args[0]) if args and isinstance(args[0], str) and args[0].startswith("/") else ""

        def reject():
            inv.return_dbus_error(_DENIED, "rejected")

        def yes_no(ok):
            inv.return_value(None) if ok else reject()

        if method == "RequestConfirmation":
            self.ui.confirm(dev, f"{args[1]:06d}", yes_no)
        elif method in ("RequestAuthorization", "AuthorizeService"):
            self.ui.confirm(dev, "", yes_no)
        elif method == "RequestPinCode":
            self.ui.ask(dev, False, lambda s: inv.return_value(GLib.Variant("(s)", (s,))) if s else reject())
        elif method == "RequestPasskey":
            def done(s):
                if s and s.isdigit():
                    inv.return_value(GLib.Variant("(u)", (int(s),)))
                else:
                    reject()
            self.ui.ask(dev, True, done)
        elif method == "DisplayPasskey":
            self.ui.show(dev, f"{args[1]:06d}")
            inv.return_value(None)
        elif method == "DisplayPinCode":
            self.ui.show(dev, args[1])
            inv.return_value(None)
        else:  # Cancel / Release
            self.ui.cancel()
            inv.return_value(None)

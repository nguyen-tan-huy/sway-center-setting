"""A fake BlueZ on the session bus, for sandbox shots: an adapter (powered) and a connected headset with a
battery (and a second device without one). Run with DBUS_SYSTEM_BUS_ADDRESS pointing at the session bus."""
import sys
import gi
from gi.repository import Gio, GLib

OM = Gio.DBusNodeInfo.new_for_xml('<node><interface name="org.freedesktop.DBus.ObjectManager"><method name="GetManagedObjects"><arg type="a{oa{sa{sv}}}" direction="out"/></method></interface></node>')
PR = Gio.DBusNodeInfo.new_for_xml('<node><interface name="org.freedesktop.DBus.Properties"><method name="GetAll"><arg type="s" direction="in"/><arg type="a{sv}" direction="out"/></method></interface></node>')
BAT = int(sys.argv[1]) if len(sys.argv) > 1 else 72

def v(sig, x): return GLib.Variant(sig, x)
adapter = {"Powered": v("b", True), "Alias": v("s", "laptop")}
headset = {"Connected": v("b", True), "Alias": v("s", "WH-1000XM4"), "Icon": v("s", "audio-headset")}
mouse = {"Connected": v("b", True), "Alias": v("s", "MX Master 3"), "Icon": v("s", "input-mouse")}
objs = {
    "/org/bluez/hci0": {"org.bluez.Adapter1": adapter},
    "/org/bluez/hci0/dev_1": {"org.bluez.Device1": headset, "org.bluez.Battery1": {"Percentage": v("y", BAT)}},
    "/org/bluez/hci0/dev_2": {"org.bluez.Device1": mouse},
}
def om_call(conn, sender, path, iface, method, params, inv):
    inv.return_value(GLib.Variant("(a{oa{sa{sv}}})", (objs,)))
def pr_call(conn, sender, path, iface, method, params, inv):
    which = params.unpack()[0]
    inv.return_value(GLib.Variant("(a{sv})", (objs.get(path, {}).get(which, {}),)))
def on_bus(conn, name):
    conn.register_object("/", OM.interfaces[0], om_call, None, None)
    for p in objs:
        conn.register_object(p, PR.interfaces[0], pr_call, None, None)
Gio.bus_own_name(Gio.BusType.SESSION, "org.bluez", Gio.BusNameOwnerFlags.NONE, on_bus, None, None)
GLib.MainLoop().run()

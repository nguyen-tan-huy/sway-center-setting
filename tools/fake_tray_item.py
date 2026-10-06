"""A StatusNotifierItem with a dbusmenu, for testing swayctl-bar's tray in the
sandbox. Logs calls it receives to the file given."""
import sys

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

log = open(sys.argv[1], "a", buffering=1)
XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <signal name="NewIcon"/>
  </interface>
  <interface name="com.canonical.dbusmenu">
    <method name="GetLayout">
      <arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
      <arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/><arg type="u" direction="in"/>
    </method>
    <method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
  </interface>
</node>"""
node = Gio.DBusNodeInfo.new_for_xml(XML)


def item(i, label, **extra):
    props = {"label": GLib.Variant("s", label)}
    for k, v in extra.items():
        props[k.replace("_", "-")] = v
    return GLib.Variant("(ia{sv}av)", (i, props, []))


LAYOUT = GLib.Variant("(ia{sv}av)", (0, {}, [
    item(1, "_Open window"),
    item(2, "Mute", toggle_type=GLib.Variant("s", "checkmark"), toggle_state=GLib.Variant("i", 1)),
    item(3, "", type=GLib.Variant("s", "separator")),
    item(4, "Quit"),
]))


def on_call(conn, sender, path, iface, method, params, inv):
    log.write(f"{iface}.{method} {params.unpack()}\n")
    if method == "GetLayout":
        inv.return_value(GLib.Variant.new_tuple(GLib.Variant("u", 1), LAYOUT))
    elif method == "AboutToShow":
        inv.return_value(GLib.Variant("(b)", (False,)))
    else:
        inv.return_value(None)


def on_get(conn, sender, path, iface, prop):
    return {
        "Category": GLib.Variant("s", "ApplicationStatus"), "Id": GLib.Variant("s", "fake"),
        "Title": GLib.Variant("s", "Fake App"), "Status": GLib.Variant("s", "Active"),
        "IconName": GLib.Variant("s", "audio-volume-high-symbolic"),
        "ToolTip": GLib.Variant("(sa(iiay)ss)", ("", [], "Fake App", "a test tray item")),
        "Menu": GLib.Variant("o", "/MenuBar"), "ItemIsMenu": GLib.Variant("b", False),
    }[prop]


bus = Gio.bus_get_sync(Gio.BusType.SESSION)
bus.register_object("/StatusNotifierItem", node.interfaces[0], on_call, on_get, None)
bus.register_object("/MenuBar", node.interfaces[1], on_call, None, None)
bus.call_sync("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher",
              "RegisterStatusNotifierItem", GLib.Variant("(s)", (bus.get_unique_name(),)), None,
              Gio.DBusCallFlags.NONE, 3000, None)
log.write("registered\n")
GLib.MainLoop().run()

"""A minimal StatusNotifierItem with a dbusmenu, for tray tests in the sandbox:
items, a separator, a checkbox, a disabled item and a submenu. Clicked ids are
printed to stdout."""
from gi.repository import Gio, GLib

ITEM_XML = """<node><interface name="org.kde.StatusNotifierItem">
<property name="Category" type="s" access="read"/><property name="Id" type="s" access="read"/>
<property name="Title" type="s" access="read"/><property name="Status" type="s" access="read"/>
<property name="IconName" type="s" access="read"/><property name="ItemIsMenu" type="b" access="read"/>
<property name="Menu" type="o" access="read"/>
<method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
</interface></node>"""
MENU_XML = """<node><interface name="com.canonical.dbusmenu">
<method name="GetLayout"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
<arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/></method>
<method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
<method name="Event"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/><arg type="u" direction="in"/></method>
<property name="Version" type="u" access="read"/>
</interface></node>"""

def node(i, props, children=()):
    return GLib.Variant("(ia{sv}av)", (i, props, list(children)))

def L(s): return {"label": GLib.Variant("s", s)}
LAYOUT = node(0, {"children-display": GLib.Variant("s", "submenu")}, [
    node(1, L("_Mở cửa sổ")),
    node(2, L("Tạm dừng đồng bộ")),
    node(3, {"type": GLib.Variant("s", "separator")}),
    node(4, {**L("Khởi động cùng hệ thống"), "toggle-type": GLib.Variant("s", "checkmark"), "toggle-state": GLib.Variant("i", 1)}),
    node(5, {**L("Không làm phiền"), "toggle-type": GLib.Variant("s", "checkmark"), "toggle-state": GLib.Variant("i", 0)}),
    node(6, {**L("Mục bị tắt"), "enabled": GLib.Variant("b", False)}),
    node(7, {**L("Trạng thái"), "children-display": GLib.Variant("s", "submenu")},
         [node(71, L("Trực tuyến")), node(72, L("Vắng mặt")), node(73, L("Bận"))]),
    node(8, {"type": GLib.Variant("s", "separator")}),
    node(9, L("Thoát")),
])

def item_call(conn, sender, path, iface, method, params, inv):
    inv.return_value(None)
def item_prop(conn, sender, path, iface, prop):
    return {"Category": GLib.Variant("s", "ApplicationStatus"), "Id": GLib.Variant("s", "faketray"),
            "Title": GLib.Variant("s", "Fake"), "Status": GLib.Variant("s", "Active"),
            "IconName": GLib.Variant("s", "mail-unread-symbolic"), "ItemIsMenu": GLib.Variant("b", True),
            "Menu": GLib.Variant("o", "/Menu")}[prop]
def menu_call(conn, sender, path, iface, method, params, inv):
    if method == "GetLayout":
        inv.return_value(GLib.Variant.new_tuple(GLib.Variant("u", 1), LAYOUT))
    elif method == "AboutToShow":
        inv.return_value(GLib.Variant("(b)", (False,)))
    else:
        print("event", params.unpack(), flush=True); inv.return_value(None)
def menu_prop(conn, sender, path, iface, prop):
    return GLib.Variant("u", 3)

bus = Gio.bus_get_sync(Gio.BusType.SESSION)
bus.register_object("/StatusNotifierItem", Gio.DBusNodeInfo.new_for_xml(ITEM_XML).interfaces[0], item_call, item_prop, None)
bus.register_object("/Menu", Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0], menu_call, menu_prop, None)
name = "org.kde.StatusNotifierItem-%d-1" % __import__("os").getpid()
Gio.bus_own_name_on_connection(bus, name, 0, None, None)
def register():
    try:
        bus.call_sync("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher",
                      "RegisterStatusNotifierItem", GLib.Variant("(s)", (name,)), None, 0, -1, None)
        print("registered", flush=True); return False
    except Exception:
        return True
GLib.timeout_add(300, register)
GLib.MainLoop().run()

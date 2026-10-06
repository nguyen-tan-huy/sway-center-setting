"""An MPRIS player with a very long title, for testing the Quick Settings
media row in the sandbox."""
import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

XML = """<node><interface name="org.mpris.MediaPlayer2.Player">
  <method name="PlayPause"/><method name="Next"/><method name="Previous"/>
  <property name="PlaybackStatus" type="s" access="read"/>
  <property name="Metadata" type="a{sv}" access="read"/>
</interface></node>"""
node = Gio.DBusNodeInfo.new_for_xml(XML)


def get(*_a):
    prop = _a[-1]
    if prop == "PlaybackStatus":
        return GLib.Variant("s", "Playing")
    return GLib.Variant("a{sv}", {
        "xesam:title": GLib.Variant("s", "TẾT NÀY CON SẼ VỀ - TUYỂN TẬP NHẠC XUÂN HAY NHẤT MỌI THỜI ĐẠI (bản rất rất dài)"),
        "xesam:artist": GLib.Variant("as", ["Thanks Long Phiêu Lưu Ký và rất nhiều nghệ sĩ khác nữa"]),
    })


bus = Gio.bus_get_sync(Gio.BusType.SESSION)
bus.register_object("/org/mpris/MediaPlayer2", node.interfaces[0], lambda *a: a[-1].return_value(None), get, None)
Gio.bus_own_name_on_connection(bus, "org.mpris.MediaPlayer2.fake", Gio.BusNameOwnerFlags.NONE, None, None)
GLib.MainLoop().run()

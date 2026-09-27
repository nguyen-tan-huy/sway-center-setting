import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk, Pango

from ..system import network
from .async_util import run_async


class WifiRow(Gtk.Box):
    def __init__(self, net: network.WifiNetwork, saved: bool, page: "NetworkPage"):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.net = net
        self.page = page
        self.set_margin_top(4)
        self.set_margin_bottom(4)

        row = Gtk.Box(spacing=8)
        label_text = f"{net.ssid}  ({net.signal}%, {net.security})"
        if net.active:
            label_text += "  — connected"
        label = Gtk.Label(label=label_text, xalign=0, ellipsize=Pango.EllipsizeMode.END, hexpand=True)
        label.set_tooltip_text(label.get_label())
        label.set_hexpand(True)
        row.append(label)

        if net.active:
            btn = Gtk.Button(label="Disconnect")
            btn.connect("clicked", lambda *_: page.run_action(network.disconnect, "wlan0"))
            row.append(btn)
        elif saved:
            btn = Gtk.Button(label="Connect")
            btn.connect("clicked", lambda *_: page.run_action(network.connect_saved, net.ssid))
            row.append(btn)
        elif net.security == "--":
            btn = Gtk.Button(label="Connect")
            btn.connect("clicked", lambda *_: page.run_action(network.connect, net.ssid, None))
            row.append(btn)
        else:
            btn = Gtk.Button(label="Connect")
            btn.connect("clicked", self._show_password_entry)
            row.append(btn)
        self.append(row)

        self.pw_box = Gtk.Box(spacing=4)
        self.pw_entry = Gtk.PasswordEntry(show_peek_icon=True)
        self.pw_entry.set_hexpand(True)
        self.pw_box.append(self.pw_entry)
        confirm = Gtk.Button(label="OK")
        confirm.connect("clicked", self._connect_with_password)
        self.pw_box.append(confirm)
        self.pw_box.set_visible(False)
        self.append(self.pw_box)

    def _show_password_entry(self, *_):
        self.pw_box.set_visible(True)
        self.pw_entry.grab_focus()

    def _connect_with_password(self, *_):
        pw = self.pw_entry.get_text()
        self.page.run_action(network.connect, self.net.ssid, pw or None)


class SavedRow(Gtk.Box):
    def __init__(self, conn: network.SavedConnection, page: "NetworkPage"):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label=conn.name, xalign=0, ellipsize=Pango.EllipsizeMode.END, hexpand=True)
        label.set_tooltip_text(label.get_label())
        label.set_hexpand(True)
        self.append(label)
        btn = Gtk.Button(label="Forget")
        btn.connect("clicked", lambda *_: page.run_action(network.forget, conn.name))
        self.append(btn)


class VpnRow(Gtk.Box):
    def __init__(self, conn: network.SavedConnection, active: bool, page: "NetworkPage"):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label_text = conn.name + ("  — connected" if active else "")
        label = Gtk.Label(label=label_text, xalign=0, ellipsize=Pango.EllipsizeMode.END, hexpand=True)
        label.set_tooltip_text(label.get_label())
        label.set_hexpand(True)
        self.append(label)

        if active:
            btn = Gtk.Button(label="Disconnect")
            btn.connect("clicked", lambda *_: page.run_action(network.connection_down, conn.name))
        else:
            btn = Gtk.Button(label="Connect")
            btn.connect("clicked", lambda *_: page.run_action(network.connect_saved, conn.name))
        self.append(btn)

        forget_btn = Gtk.Button(label="Forget")
        forget_btn.connect("clicked", lambda *_: page.run_action(network.forget, conn.name))
        self.append(forget_btn)


class NetworkPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)

        title = Gtk.Label(label="Network", xalign=0)
        title.add_css_class("title-1")
        self.append(title)

        header = Gtk.Box(spacing=8)
        self.wifi_switch = Gtk.Switch()
        self.wifi_switch.connect("state-set", self._on_wifi_toggle)
        header.append(Gtk.Label(label="Wi-Fi"))
        header.append(self.wifi_switch)
        rescan_btn = Gtk.Button(label="Rescan")
        rescan_btn.connect("clicked", lambda *_: self._rescan())
        header.append(rescan_btn)
        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", lambda *_: self.reload())
        header.append(refresh_btn)
        self.append(header)

        self.status_label = Gtk.Label(xalign=0, wrap=True)
        self.append(self.status_label)

        nets_title = Gtk.Label(label="Available networks", xalign=0)
        nets_title.add_css_class("heading")
        self.append(nets_title)
        self.wifi_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.append(self.wifi_box)

        saved_title = Gtk.Label(label="Saved networks", xalign=0)
        saved_title.add_css_class("heading")
        self.append(saved_title)
        self.saved_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.append(self.saved_box)

        vpn_title = Gtk.Label(label="VPN", xalign=0)
        vpn_title.add_css_class("heading")
        self.append(vpn_title)
        self.vpn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.append(self.vpn_box)

        # Deferred so the window can appear before the first reload() runs.
        GLib.idle_add(self._reload_once)

    def _reload_once(self):
        self.reload()
        return GLib.SOURCE_REMOVE

    def reload(self):
        # nmcli spawns a subprocess per call (3 of them here); run off the
        # GTK thread so switching to/loading this page never freezes the UI.
        run_async(self._gather, self._apply_loaded)

    def _gather(self):
        return {
            "wifi_enabled": network.wifi_enabled(),
            "saved": network.saved_connections(),
            "nets": network.list_wifi(),
            "active_names": network.active_connection_names(),
        }

    def _apply_loaded(self, data):
        if isinstance(data, Exception):
            self.status_label.set_label(f"nmcli error: {data}")
            return GLib.SOURCE_REMOVE

        self.wifi_switch.set_active(data["wifi_enabled"])
        saved = data["saved"]
        saved_names = {c.name for c in saved if c.type == "802-11-wireless"}
        nets = data["nets"]

        current = next((n.ssid for n in nets if n.active), None)
        self.status_label.set_label(f"Connected to: {current}" if current else "Not connected")

        for child in list(self.wifi_box):
            self.wifi_box.remove(child)
        for n in nets:
            self.wifi_box.append(WifiRow(n, n.ssid in saved_names, self))

        for child in list(self.saved_box):
            self.saved_box.remove(child)
        for c in saved:
            if c.type == "802-11-wireless":
                self.saved_box.append(SavedRow(c, self))

        active_names = data["active_names"]
        for child in list(self.vpn_box):
            self.vpn_box.remove(child)
        for c in saved:
            if c.type == "vpn":
                self.vpn_box.append(VpnRow(c, c.name in active_names, self))
        return GLib.SOURCE_REMOVE

    def _on_wifi_toggle(self, switch, state):
        self.run_action(network.set_wifi_enabled, state)
        return False

    def _rescan(self):
        network.rescan()
        self.reload()

    def run_action(self, fn, *args):
        try:
            fn(*args)
        except Exception as e:
            self.status_label.set_label(f"Error: {e}")
        self.reload()

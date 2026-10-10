import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk, Pango

from ..system import bluetooth
from .async_util import run_async
from .live import Live


class DeviceRow(Gtk.Box):
    def __init__(self, device: bluetooth.Device, page: "BluetoothPage"):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.device = device
        self.page = page
        self.set_margin_top(4)
        self.set_margin_bottom(4)

        status = "connected" if device.connected else ("paired" if device.paired else "new")
        label = Gtk.Label(label=f"{device.name}  [{device.address}]  ({status})", xalign=0, ellipsize=Pango.EllipsizeMode.END, hexpand=True)
        label.set_tooltip_text(label.get_label())
        label.set_hexpand(True)
        self.append(label)

        if device.connected:
            btn = Gtk.Button(label="Disconnect")
            btn.connect("clicked", lambda *_: page.run_action(bluetooth.disconnect, device.path))
        elif device.paired:
            btn = Gtk.Button(label="Connect")
            btn.connect("clicked", lambda *_: page.run_slow(bluetooth.connect, device.path, what=f"Connecting {device.name}…"))
        else:
            btn = Gtk.Button(label="Pair")
            btn.connect("clicked", lambda *_: page.run_slow(bluetooth.pair_and_connect, device.path, what=f"Pairing {device.name}…"))
        self.append(btn)

        if device.paired:
            remove_btn = Gtk.Button(label="Remove")
            remove_btn.connect(
                "clicked",
                lambda *_: page.run_action(bluetooth.remove, device.adapter_path, device.path),
            )
            self.append(remove_btn)


class BluetoothPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)
        self._discovering = False
        self._adapter = None

        title = Gtk.Label(label="Bluetooth", xalign=0)
        title.add_css_class("title-1")
        self.append(title)

        header = Gtk.Box(spacing=8)
        self.power_switch = Gtk.Switch()
        self.power_switch.connect("state-set", self._on_power)
        header.append(Gtk.Label(label="Adapter power"))
        header.append(self.power_switch)

        self.scan_btn = Gtk.Button(label="Start scanning")
        self.scan_btn.connect("clicked", lambda *_: self._toggle_scan())
        header.append(self.scan_btn)

        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", lambda *_: self.reload())
        header.append(refresh_btn)
        self.append(header)

        self.status_label = Gtk.Label(xalign=0, wrap=True)
        self.append(self.status_label)

        self.rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.append(self.rows_box)

        # Deferred so the window can appear before the first reload() runs.
        GLib.idle_add(self._reload_once)
        # follows BlueZ: power, devices found while scanning, (dis)connects
        self._live = Live(self, self.reload).dbus("org.bluez")

    def _reload_once(self):
        self.reload()
        return GLib.SOURCE_REMOVE

    def reload(self):
        # D-Bus round-trips per call; run off the GTK thread so switching
        # to/loading this page (and each change BlueZ reports)
        # never freezes the UI.
        run_async(self._gather, self._apply_loaded)

    def _gather(self):
        adapters = bluetooth.list_adapters()
        devices = bluetooth.list_devices(adapters[0].path) if adapters else []
        return {"adapters": adapters, "devices": devices}

    def _apply_loaded(self, data):
        if isinstance(data, Exception):
            self.status_label.set_label(f"bluez error: {data}")
            return GLib.SOURCE_REMOVE
        adapters = data["adapters"]
        if not adapters:
            self.status_label.set_label("No bluetooth adapter found")
            return GLib.SOURCE_REMOVE
        self._adapter = adapters[0]
        self.power_switch.set_active(self._adapter.powered)
        self._discovering = self._adapter.discovering
        self.scan_btn.set_label("Stop scanning" if self._discovering else "Start scanning")

        for child in list(self.rows_box):
            self.rows_box.remove(child)
        devices = data["devices"]
        devices.sort(key=lambda d: (not d.connected, not d.paired, d.name))
        for d in devices:
            self.rows_box.append(DeviceRow(d, self))
        self.status_label.set_label(f"{len(devices)} device(s) known")
        return GLib.SOURCE_REMOVE

    def _on_power(self, switch, state):
        if self._adapter:
            self.run_action(bluetooth.set_adapter_powered, self._adapter.path, state)
        return False

    def _toggle_scan(self):
        if not self._adapter:
            return
        if self._discovering:
            self.run_action(bluetooth.stop_discovery, self._adapter.path)
        else:
            self.run_action(bluetooth.start_discovery, self._adapter.path)

    def run_slow(self, fn, *args, what=""):
        """Pair/connect can wait on the user or the device: keep the UI alive."""
        self.status_label.set_label(what)

        def done(result):
            if isinstance(result, Exception):
                self.status_label.set_label(f"Error: {result}")
            self.reload()
            return GLib.SOURCE_REMOVE

        run_async(lambda: fn(*args), done)

    def run_action(self, fn, *args):
        try:
            fn(*args)
        except Exception as e:
            self.status_label.set_label(f"Error: {e}")
        self.reload()

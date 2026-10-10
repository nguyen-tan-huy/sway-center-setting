"""Backend for Bluetooth, talking to bluez directly over D-Bus (system bus).

Uses GLib's own D-Bus bindings (gi.repository.Gio), already pulled in by
PyGObject/GTK4 - no extra python-dbus/pydbus package needed.
"""
from dataclasses import dataclass, field

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

BLUEZ = "org.bluez"


@dataclass
class Adapter:
    path: str
    address: str
    name: str
    powered: bool
    discoverable: bool
    discovering: bool


@dataclass
class Device:
    path: str
    adapter_path: str
    address: str
    name: str
    paired: bool
    trusted: bool
    connected: bool
    icon: str = ""
    rssi: int | None = None


class BluezError(RuntimeError):
    pass


_bus_singleton: Gio.DBusConnection | None = None


def _bus() -> Gio.DBusConnection:
    # MUST be a cached, long-lived connection - not a fresh Gio.bus_get_sync() per call.
    # BlueZ ties a StartDiscovery session to the CALLER's own D-Bus connection: the moment that
    # connection's sender disappears from the bus, bluetoothd auto-stops discovery for it (same
    # rule that makes `bluetoothctl scan on` stop scanning the instant you Ctrl-C it). A fresh
    # local `Gio.bus_get_sync(...)` return value has no other reference once the calling function
    # returns, so CPython's refcounting GC drops it (and the underlying socket) almost
    # immediately - confirmed for real: `Discovering` flipped straight from True back to False
    # within about a second of calling start_discovery(), even though nothing ever called
    # stop_discovery() - matching exactly "scan mà không hiển thị thiết bị để nhấn connect" (scan
    # runs but no devices ever show up to connect to). Caching it at module level keeps the SAME
    # connection alive for this whole process's lifetime, the same way bluetoothctl's own
    # long-running process keeps its scan alive for as long as it's running.
    global _bus_singleton
    if _bus_singleton is None:
        _bus_singleton = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    return _bus_singleton


def _call(bus, path, interface, method, args=None, reply_type=None, timeout=2000):
    try:
        return bus.call_sync(
            BLUEZ,
            path,
            interface,
            method,
            args,
            reply_type,
            Gio.DBusCallFlags.NONE,
            timeout,
            None,
        )
    except GLib.Error as e:
        raise BluezError(f"{interface}.{method} on {path} failed: {e.message}") from e


def _get_property(bus, path, interface, name):
    variant = _call(
        bus, path, "org.freedesktop.DBus.Properties", "Get",
        GLib.Variant("(ss)", (interface, name)),
    )
    return variant.unpack()[0]


def _set_property(bus, path, interface, name, value: GLib.Variant):
    _call(
        bus, path, "org.freedesktop.DBus.Properties", "Set",
        GLib.Variant("(ssv)", (interface, name, value)),
    )


def _managed_objects(bus) -> dict:
    variant = _call(bus, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")
    return variant.unpack()[0]


def list_adapters() -> list[Adapter]:
    bus = _bus()
    objects = _managed_objects(bus)
    adapters = []
    for path, ifaces in objects.items():
        props = ifaces.get("org.bluez.Adapter1")
        if not props:
            continue
        adapters.append(
            Adapter(
                path=path,
                address=props.get("Address", ""),
                name=props.get("Alias", props.get("Name", "")),
                powered=props.get("Powered", False),
                discoverable=props.get("Discoverable", False),
                discovering=props.get("Discovering", False),
            )
        )
    return adapters


def list_devices(adapter_path: str | None = None) -> list[Device]:
    bus = _bus()
    objects = _managed_objects(bus)
    devices = []
    for path, ifaces in objects.items():
        props = ifaces.get("org.bluez.Device1")
        if not props:
            continue
        dev_adapter = props.get("Adapter", "")
        if adapter_path and dev_adapter != adapter_path:
            continue
        devices.append(
            Device(
                path=path,
                adapter_path=dev_adapter,
                address=props.get("Address", ""),
                name=props.get("Alias", props.get("Name", props.get("Address", ""))),
                paired=props.get("Paired", False),
                trusted=props.get("Trusted", False),
                connected=props.get("Connected", False),
                icon=props.get("Icon", ""),
                rssi=props.get("RSSI"),
            )
        )
    return devices


def set_adapter_powered(adapter_path: str, powered: bool) -> None:
    bus = _bus()
    _set_property(bus, adapter_path, "org.bluez.Adapter1", "Powered", GLib.Variant("b", powered))


def start_discovery(adapter_path: str) -> None:
    _call(_bus(), adapter_path, "org.bluez.Adapter1", "StartDiscovery")


def stop_discovery(adapter_path: str) -> None:
    _call(_bus(), adapter_path, "org.bluez.Adapter1", "StopDiscovery")


def pair(device_path: str) -> None:
    # waits for the user to answer the agent's confirmation, so no 2 s limit
    _call(_bus(), device_path, "org.bluez.Device1", "Pair", timeout=120000)


def connect(device_path: str) -> None:
    _call(_bus(), device_path, "org.bluez.Device1", "Connect", timeout=30000)


def pair_and_connect(device_path: str) -> None:
    pair(device_path)
    set_trusted(device_path, True)
    connect(device_path)


def disconnect(device_path: str) -> None:
    _call(_bus(), device_path, "org.bluez.Device1", "Disconnect")


def set_trusted(device_path: str, trusted: bool) -> None:
    bus = _bus()
    _set_property(bus, device_path, "org.bluez.Device1", "Trusted", GLib.Variant("b", trusted))


def remove(adapter_path: str, device_path: str) -> None:
    _call(
        _bus(), adapter_path, "org.bluez.Adapter1", "RemoveDevice",
        GLib.Variant("(o)", (device_path,)),
    )

"""D-Bus client for the daemon, shared by the CLI and the UI."""
from __future__ import annotations

import json
from typing import Any

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from .daemon import BUS_NAME, INTERFACE, OBJECT_PATH  # noqa: E402


class DaemonUnavailable(Exception):
    pass


class CallError(Exception):
    pass


def _message(e: GLib.Error) -> tuple[str, str]:
    remote = Gio.DBusError.get_remote_error(e) or ""
    msg = e.message
    prefix = f"GDBus.Error:{remote}: "
    if remote and msg.startswith(prefix):
        msg = msg[len(prefix):]
    return remote, msg


class Client:
    def __init__(self, bus: Gio.DBusConnection | None = None):
        self._bus = bus
        self._proxy: Gio.DBusProxy | None = None

    def _get_proxy(self) -> Gio.DBusProxy:
        if self._proxy is None:
            bus = self._bus or Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self._proxy = Gio.DBusProxy.new_sync(
                bus, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES, None,
                BUS_NAME, OBJECT_PATH, INTERFACE, None)
        return self._proxy

    def call(self, method: str, signature: str | None = None, *args) -> str | None:
        params = GLib.Variant(signature, args) if signature else None
        try:
            result = self._get_proxy().call_sync(method, params, Gio.DBusCallFlags.NONE, 5000, None)
        except GLib.Error as e:
            remote, msg = _message(e)
            if remote.endswith(("ServiceUnknown", "NameHasNoOwner")):
                raise DaemonUnavailable("the swayctl-center daemon is not running") from None
            raise CallError(msg) from None
        return result.unpack()[0] if result is not None and len(result) else None

    def get_schema(self) -> list[dict[str, Any]]:
        return json.loads(self.call("GetSchema"))

    def get_all(self) -> dict[str, dict[str, Any]]:
        return json.loads(self.call("GetAll"))

    def get(self, path: str) -> Any:
        return json.loads(self.call("Get", "(s)", path))

    def set(self, path: str, value: Any) -> None:
        self.call("Set", "(ss)", path, json.dumps(value))

    def reset(self, path: str) -> None:
        self.call("Reset", "(s)", path)

    def apply_all(self) -> None:
        self.call("ApplyAll")

    def status(self) -> dict[str, Any]:
        return json.loads(self.call("GetStatus"))

    def action(self, name: str) -> None:
        self.call("Action", "(s)", name)

    def export(self, path: str) -> dict[str, Any]:
        return json.loads(self.call("Export", "(s)", path))

    def import_(self, path: str) -> dict[str, Any]:
        return json.loads(self.call("Import", "(s)", path))

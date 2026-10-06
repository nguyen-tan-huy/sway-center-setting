"""Minimal sway IPC client (the i3-ipc wire protocol), stdlib only."""
from __future__ import annotations

import json
import os
import socket
import struct
from typing import Any

MAGIC = b"i3-ipc"
_HEADER = struct.Struct("<6sII")

RUN_COMMAND = 0
GET_OUTPUTS = 3
GET_TREE = 4
GET_BAR_CONFIG = 6
GET_VERSION = 7
SUBSCRIBE = 2
GET_INPUTS = 100
GET_CONFIG = 9

EVENT_BIT = 0x80000000
EVENT_NAMES = {
    EVENT_BIT | 0: "workspace",
    EVENT_BIT | 1: "output",
    EVENT_BIT | 6: "shutdown",
    EVENT_BIT | 21: "input",
}


class IPCError(RuntimeError):
    pass


def socket_path() -> str:
    path = os.environ.get("SWAYSOCK")
    if not path:
        raise IPCError("SWAYSOCK is not set - is sway running?")
    return path


def pack(msg_type: int, payload: str = "") -> bytes:
    body = payload.encode()
    return _HEADER.pack(MAGIC, len(body), msg_type) + body


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise IPCError("sway closed the IPC socket")
        buf += chunk
    return buf


def read_message(sock: socket.socket) -> tuple[int, Any]:
    magic, length, msg_type = _HEADER.unpack(_recv_exact(sock, _HEADER.size))
    if magic != MAGIC:
        raise IPCError(f"bad IPC magic {magic!r}")
    body = _recv_exact(sock, length) if length else b""
    return msg_type, json.loads(body) if body else None


class Connection:
    """Request/response connection. Reconnects once if sway dropped it."""

    def __init__(self, path: str | None = None):
        self.path = path or socket_path()
        self._sock: socket.socket | None = None

    def _connect(self) -> socket.socket:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self.path)
        return sock

    def request(self, msg_type: int, payload: str = "") -> Any:
        for attempt in (0, 1):
            if self._sock is None:
                self._sock = self._connect()
            try:
                self._sock.sendall(pack(msg_type, payload))
                _, reply = read_message(self._sock)
                return reply
            except (OSError, IPCError):
                self.close()
                if attempt:
                    raise

    def command(self, cmd: str) -> list[dict[str, Any]]:
        return self.request(RUN_COMMAND, cmd)

    def get_outputs(self) -> list[dict[str, Any]]:
        return self.request(GET_OUTPUTS)

    def get_inputs(self) -> list[dict[str, Any]]:
        return self.request(GET_INPUTS)

    def get_bar_config(self, bar_id: str = "") -> Any:
        """The ids of sway's own bars (`bar { }` blocks), or one bar's config."""
        return self.request(GET_BAR_CONFIG, bar_id)

    def get_version(self) -> dict[str, Any]:
        return self.request(GET_VERSION)

    def get_config(self) -> str:
        return self.request(GET_CONFIG).get("config", "")

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None


class EventSubscription:
    """A dedicated socket subscribed to events. Poll `fileno()` and call `read()`."""

    def __init__(self, events: list[str], path: str | None = None):
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(path or socket_path())
        self._sock.sendall(pack(SUBSCRIBE, json.dumps(events)))
        _, reply = read_message(self._sock)
        if not reply or not reply.get("success"):
            raise IPCError(f"subscribe failed: {reply}")

    def fileno(self) -> int:
        return self._sock.fileno()

    def read(self) -> tuple[str, Any]:
        msg_type, payload = read_message(self._sock)
        return EVENT_NAMES.get(msg_type, hex(msg_type)), payload

    def close(self) -> None:
        self._sock.close()

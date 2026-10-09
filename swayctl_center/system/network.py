"""Backend for Wi-Fi/network, entirely via nmcli (NetworkManager) - no GUI tool needed."""
import subprocess
from dataclasses import dataclass


class NetworkError(RuntimeError):
    pass


@dataclass
class WifiNetwork:
    ssid: str
    signal: int
    security: str
    active: bool


@dataclass
class SavedConnection:
    name: str
    type: str
    device: str


def _unescape(field: str) -> str:
    # nmcli -t escapes ':' as '\:' inside field values.
    return field.replace("\\:", ":")


def _run(*args: str) -> str:
    result = subprocess.run(["nmcli", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise NetworkError(result.stderr.strip() or f"nmcli {' '.join(args)} failed")
    return result.stdout


def wifi_enabled() -> bool:
    out = _run("-t", "-f", "WIFI", "radio")
    return out.strip().lower() == "enabled"


def set_wifi_enabled(enabled: bool) -> None:
    _run("radio", "wifi", "on" if enabled else "off")


def rescan() -> None:
    try:
        _run("device", "wifi", "rescan")
    except NetworkError:
        pass  # rescan can fail if one just ran recently; list_wifi() below still works


def list_wifi() -> list[WifiNetwork]:
    out = _run("-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "no")
    seen: dict[str, WifiNetwork] = {}
    for line in out.splitlines():
        if not line:
            continue
        parts = line.split(":")
        if len(parts) < 4:
            continue
        active, ssid, signal, security = parts[0], _unescape(parts[1]), parts[2], ":".join(parts[3:])
        if not ssid:
            continue
        net = WifiNetwork(
            ssid=ssid,
            signal=int(signal) if signal.isdigit() else 0,
            security=security or "--",
            active=(active == "yes"),
        )
        # Same SSID can appear once per BSSID - keep the strongest/active one.
        existing = seen.get(ssid)
        if existing is None or net.active or net.signal > existing.signal:
            seen[ssid] = net
    return sorted(seen.values(), key=lambda n: (-n.active, -n.signal))


def saved_connections() -> list[SavedConnection]:
    out = _run("-t", "-f", "NAME,TYPE,DEVICE", "connection", "show")
    result = []
    for line in out.splitlines():
        if not line:
            continue
        parts = line.split(":")
        if len(parts) < 3:
            continue
        result.append(SavedConnection(name=_unescape(parts[0]), type=parts[1], device=parts[2]))
    return result


def current_connection() -> str | None:
    for net in list_wifi():
        if net.active:
            return net.ssid
    return None


def connect(ssid: str, password: str | None = None) -> None:
    args = ["device", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    _run(*args)


def connect_saved(name: str) -> None:
    _run("connection", "up", name)


def disconnect(device: str) -> None:
    _run("device", "disconnect", device)


def connection_down(name: str) -> None:
    """Bring down a connection by name - unlike disconnect(), works for VPNs
    (and anything else without a persistent device entry when inactive)."""
    _run("connection", "down", name)


def active_connection_names() -> set[str]:
    out = _run("-t", "-f", "NAME", "connection", "show", "--active")
    return {_unescape(line) for line in out.splitlines() if line}


def forget(name: str) -> None:
    _run("connection", "delete", name)

"""Backend for audio: volume/mute and default input/output device, via pactl
(works against PipeWire's pulse-compat layer, same as plain PulseAudio)."""
import json
import subprocess
from dataclasses import dataclass


class AudioError(RuntimeError):
    pass


@dataclass
class Device:
    name: str
    description: str
    volume_percent: int
    mute: bool


def _run(*args: str) -> str:
    result = subprocess.run(["pactl", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise AudioError(result.stderr.strip() or f"pactl {' '.join(args)} failed")
    return result.stdout


def _run_json(*args: str) -> list:
    out = _run("-f", "json", *args).strip()
    return json.loads(out) if out else []


def _parse_devices(raw: list) -> list[Device]:
    devices = []
    for d in raw:
        vol_map = d.get("volume") or {}
        percents = []
        for v in vol_map.values():
            raw_pct = str(v.get("value_percent", "0%")).rstrip("%")
            try:
                percents.append(int(round(float(raw_pct))))
            except ValueError:
                pass
        avg = round(sum(percents) / len(percents)) if percents else 0
        devices.append(Device(
            name=d["name"],
            description=d.get("description") or d["name"],
            volume_percent=avg,
            mute=bool(d.get("mute", False)),
        ))
    return devices


def list_sinks() -> list[Device]:
    return _parse_devices(_run_json("list", "sinks"))


def list_sources() -> list[Device]:
    # Exclude monitor sources (e.g. "..analog-stereo.monitor") - those are
    # loopback taps on an output, not real microphones, and would otherwise
    # show up as a bogus "microphone" choice.
    return [d for d in _parse_devices(_run_json("list", "sources")) if not d.name.endswith(".monitor")]


def default_sink() -> str:
    return _run("get-default-sink").strip()


def default_source() -> str:
    return _run("get-default-source").strip()


def set_default_sink(name: str) -> None:
    _run("set-default-sink", name)


def set_default_source(name: str) -> None:
    _run("set-default-source", name)


def set_sink_volume(name: str, percent: int) -> None:
    _run("set-sink-volume", name, f"{percent}%")


def set_source_volume(name: str, percent: int) -> None:
    _run("set-source-volume", name, f"{percent}%")


def set_sink_mute(name: str, mute: bool) -> None:
    _run("set-sink-mute", name, "1" if mute else "0")


def set_source_mute(name: str, mute: bool) -> None:
    _run("set-source-mute", name, "1" if mute else "0")

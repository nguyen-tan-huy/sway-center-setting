"""Per-user UI state (e.g. whether the setup assistant has run)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(base) / "swayctl-center" / "ui.json"


def get(key: str, default: Any = None) -> Any:
    try:
        return json.loads(_path().read_text()).get(key, default)
    except (OSError, ValueError):
        return default


def set(key: str, value: Any) -> None:  # noqa: A001 - mirrors get()
    path = _path()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))

"""Runtime state that isn't a setting: e.g. a temporary theme override from
"toggle" while on an automatic schedule. Kept in $XDG_STATE_HOME so it
survives a daemon restart but is never exported with the settings."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def state_file() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(base) / "swayctl-center" / "state.json"


class State:
    def __init__(self, path: Path | None = None):
        self.path = path or state_file()
        try:
            self.data: dict[str, Any] = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.data = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if value is None:
            self.data.pop(key, None)
        else:
            self.data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2))
        os.replace(tmp, self.path)

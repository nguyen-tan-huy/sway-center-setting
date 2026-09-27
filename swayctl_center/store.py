"""Where swayctl-center keeps its settings.

Two JSON files under $XDG_CONFIG_HOME/swayctl-center/:
  settings.json        shared settings (exported/imported between machines)
  settings.local.json  machine-scoped settings (outputs, wallpaper path, ...)

Only values the user actually set are stored; everything else comes from the
schema defaults. Users are not expected to edit these files, but hand edits are
picked up by the daemon's file watcher like any other change.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from . import schema

log = logging.getLogger(__name__)

FORMAT_VERSION = 1


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "swayctl-center"


class Store:
    def __init__(self, directory: Path | None = None):
        self.dir = directory or config_dir()
        self.files = {
            schema.SHARED: self.dir / "settings.json",
            schema.MACHINE: self.dir / "settings.local.json",
        }
        self._data: dict[str, dict[str, dict[str, Any]]] = {s: {} for s in self.files}

    @property
    def exists(self) -> bool:
        return any(p.exists() for p in self.files.values())

    def load(self) -> None:
        """(Re)read both files. A file that fails to parse keeps its last good content."""
        for scope, path in self.files.items():
            try:
                raw = json.loads(path.read_text())
            except FileNotFoundError:
                self._data[scope] = {}
                continue
            except (OSError, json.JSONDecodeError) as e:
                log.warning("ignoring unreadable %s (keeping last good values): %s", path, e)
                continue
            values = raw.get("values", {}) if isinstance(raw, dict) else {}
            self._data[scope] = values if isinstance(values, dict) else {}

    def effective(self) -> dict[str, dict[str, Any]]:
        """Schema defaults overlaid with stored values; invalid stored values are skipped."""
        out = schema.defaults()
        for scope in (schema.SHARED, schema.MACHINE):
            for section, values in self._data[scope].items():
                if not isinstance(values, dict):
                    continue
                for name, value in values.items():
                    try:
                        key = schema.lookup(section, name)
                        out[section][name] = key.validate(value)
                    except (KeyError, ValueError) as e:
                        log.warning("ignoring stored value: %s", e)
        return out

    def is_set(self, section: str, name: str) -> bool:
        key = schema.lookup(section, name)
        return name in self._data[key.scope].get(section, {})

    def set(self, section: str, name: str, value: Any) -> Any:
        key = schema.lookup(section, name)
        value = key.validate(value)
        self._data[key.scope].setdefault(section, {})[name] = value
        self._write(key.scope)
        return value

    def set_many(self, values: dict[str, dict[str, Any]]) -> None:
        """Validate and store a whole {section: {name: value}} tree; invalid entries are skipped."""
        touched = set()
        for section, items in values.items():
            for name, value in items.items():
                try:
                    key = schema.lookup(section, name)
                    self._data[key.scope].setdefault(section, {})[name] = key.validate(value)
                    touched.add(key.scope)
                except (KeyError, ValueError) as e:
                    log.warning("skipping %s.%s: %s", section, name, e)
        for scope in touched:
            self._write(scope)

    def scope_values(self, scope: str) -> dict[str, dict[str, Any]]:
        """The values actually stored (not defaults) for one scope."""
        import copy
        return copy.deepcopy(self._data[scope])

    def replace_scope(self, scope: str, values: dict[str, dict[str, Any]]) -> None:
        """Replace everything stored for a scope (values must be validated)."""
        self._data[scope] = {s: dict(v) for s, v in values.items() if v}
        self._write(scope)

    def reset(self, section: str, name: str) -> None:
        key = schema.lookup(section, name)
        section_values = self._data[key.scope].get(section, {})
        if name in section_values:
            del section_values[name]
            if not section_values:
                del self._data[key.scope][section]
            self._write(key.scope)

    def _write(self, scope: str) -> None:
        path = self.files[scope]
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": FORMAT_VERSION, "values": self._data[scope]}, indent=2, sort_keys=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(payload + "\n")
            os.replace(tmp, path)
        except BaseException:
            os.unlink(tmp)
            raise

"""Read-only parser for the user's sway config, used once on first start to
adopt their existing setup. Nothing here ever writes to the config.

Handles what real configs use: `set $var` (expanded in order, like sway),
`include` (globs, ~, relative paths), `\\` line continuations, and `{ }` blocks
(so e.g. bindings inside `mode "resize" { }` aren't mistaken for defaults).
"""
from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Line:
    text: str                 # variables already expanded
    blocks: tuple[str, ...]   # enclosing block headers, outermost first
    raw: str = ""             # as written, before variable expansion


@dataclass
class Config:
    lines: list[Line] = field(default_factory=list)
    variables: dict[str, str] = field(default_factory=dict)

    def top_level(self) -> list[str]:
        return [line.text for line in self.lines if not line.blocks]


SYSTEM_CONFIG = Path("/etc/sway/config")  # the stock config, used when the user has none


def main_config_path() -> Path | None:
    """Same search order as sway."""
    home = Path.home()
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    for p in (home / ".sway/config", xdg / "sway/config", home / ".i3/config",
              xdg / "i3/config", SYSTEM_CONFIG, Path("/etc/i3/config")):
        if p.is_file():
            return p
    return None


def _logical_lines(text: str) -> list[str]:
    out, pending = [], ""
    for raw in text.splitlines():
        line = raw.strip()
        if pending:
            line = pending + " " + line
            pending = ""
        if line.endswith("\\"):
            pending = line[:-1].rstrip()
            continue
        if line and not line.startswith("#"):
            out.append(line)
    if pending:
        out.append(pending)
    return out


def _expand(text: str, variables: dict[str, str]) -> str:
    if "$" not in text:
        return text
    # longest names first so $paper_bg_bare isn't eaten by $paper_bg
    for name in sorted(variables, key=len, reverse=True):
        text = text.replace(name, variables[name])
    return text


_SET_RE = re.compile(r"^set\s+(\$\S+)\s+(.*)$")


def parse(text: str, base_dir: Path, config: Config | None = None,
          _blocks: list[str] | None = None, _seen: set[Path] | None = None) -> Config:
    config = config if config is not None else Config()
    blocks = _blocks if _blocks is not None else []
    seen = _seen if _seen is not None else set()

    for line in _logical_lines(text):
        m = _SET_RE.match(line)
        if m:
            config.variables[m.group(1)] = _expand(m.group(2).strip(), config.variables)
            continue
        raw = line
        line = _expand(line, config.variables)
        if line == "}":
            if blocks:
                blocks.pop()
            continue
        if line.endswith("{"):
            blocks.append(line[:-1].strip())
            continue
        if line.startswith("include "):
            pattern = os.path.expandvars(os.path.expanduser(line[len("include "):].strip().strip('"')))
            if not os.path.isabs(pattern):
                pattern = str(base_dir / pattern)
            for name in sorted(glob.glob(pattern)):
                path = Path(name).resolve()
                if path in seen or not path.is_file():
                    continue
                seen.add(path)
                try:
                    parse(path.read_text(), path.parent, config, blocks, seen)
                except OSError:
                    continue
            continue
        config.lines.append(Line(line, tuple(blocks), raw))
    return config


def load(ipc) -> Config:
    """Parse the config sway has loaded (text via IPC, includes from disk)."""
    try:
        text = ipc.get_config()
    except Exception:
        text = ""
    main = main_config_path()
    if not text and main is not None:
        text = main.read_text()
    base = main.parent if main is not None else Path.home() / ".config/sway"
    return parse(text, base)

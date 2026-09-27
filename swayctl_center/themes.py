"""Color themes. A theme is four colors - the same roles the "paper" themes
used: background, foreground, accent (focused borders) and muted (inactive).
Built-in themes live here; users can add their own as JSON files in
<app folder>/themes/<name>.json with the same four keys.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_HEX = re.compile(r"#[0-9a-fA-F]{6}")


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    fg: str
    accent: str
    muted: str

    @property
    def dark(self) -> bool:
        r, g, b = (int(self.bg[i:i + 2], 16) for i in (1, 3, 5))
        return (r * 299 + g * 587 + b * 114) / 1000 < 128

    def to_json(self) -> dict:
        return {"name": self.name, "bg": self.bg, "fg": self.fg, "accent": self.accent,
                "muted": self.muted, "dark": self.dark}


BUILTIN = {t.name: t for t in (
    Theme("gruvbox-light", "#fbf1c7", "#3c3836", "#d65d0e", "#a89984"),
    Theme("gruvbox-dark", "#282828", "#ebdbb2", "#fabd2f", "#928374"),
    Theme("light", "#e8dcb8", "#2b2015", "#2b2015", "#a8976f"),
    Theme("dark", "#1c1712", "#e3d5ad", "#e3d5ad", "#8a7a54"),
    Theme("nord", "#2e3440", "#d8dee9", "#88c0d0", "#4c566a"),
    Theme("dracula", "#282a36", "#f8f8f2", "#bd93f9", "#6272a4"),
    Theme("solarized-dark", "#002b36", "#839496", "#268bd2", "#586e75"),
)}


def user_theme_dir(data_dir: Path) -> Path:
    return data_dir / "themes"


def load_all(data_dir: Path | None) -> dict[str, Theme]:
    themes = dict(BUILTIN)
    if data_dir is None:
        return themes
    for path in sorted(user_theme_dir(data_dir).glob("*.json")):
        try:
            raw = json.loads(path.read_text())
            colors = {k: raw[k] for k in ("bg", "fg", "accent", "muted")}
            if not all(isinstance(v, str) and _HEX.fullmatch(v) for v in colors.values()):
                raise ValueError("colors must be #rrggbb")
            themes[path.stem] = Theme(path.stem, **colors)
        except (OSError, KeyError, ValueError, TypeError) as e:
            log.warning("ignoring theme %s: %s", path, e)
    return themes

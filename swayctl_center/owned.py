"""Files the app owns. When a setting points at one of the user's own files
(a waybar config, a style template...), the file is copied into the app's
folder and the setting points at the copy from then on: the user never has to
know or keep track of where it is, and export/import can carry it.

A copied config's references to files next to the original (scripts, menus)
are copied along and rewritten to the copies.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from .theming import expand


def _is_inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def _reference_forms(folder: Path) -> list[str]:
    """How a config may spell a path in `folder`: absolute, ~/..., $HOME/..."""
    forms = [str(folder)]
    try:
        rel = folder.relative_to(Path.home())
        forms += [f"~/{rel}", f"$HOME/{rel}", f"${{HOME}}/{rel}"]
    except ValueError:
        pass
    return forms


def adopt(value: str, data_dir: Path, sub: str, name: str, with_references: bool = False) -> str:
    """Copy the file `value` points at into data_dir/sub/name; returns the new
    value (the copy's path). Values already inside data_dir are kept."""
    if not value:
        return value
    src = expand(value)
    dest_dir = data_dir / sub
    if _is_inside(src, data_dir):
        return value
    if not src.is_file():
        raise ValueError(f"file not found: {value}")
    text = src.read_text()
    if with_references:
        forms = "|".join(re.escape(f) for f in _reference_forms(src.parent))
        pattern = re.compile(rf"(?:{forms})/([\w.@+-]+(?:/[\w.@+-]+)*)")

        def copy_ref(m: re.Match) -> str:
            ref = src.parent / m.group(1)
            if not ref.is_file():
                return m.group(0)  # leave references to missing files alone
            target = dest_dir / "files" / m.group(1)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ref, target)
            return str(target)
        text = pattern.sub(copy_ref, text)
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / name).write_text(text)
    return str(dest_dir / name)

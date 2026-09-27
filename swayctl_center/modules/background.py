"""Wallpaper, applied with `output * bg` (sway runs swaybg itself).

Images are copied into <app folder>/wallpapers and stored by relative path, so
the setting survives the original file being moved or deleted and can be
carried to another machine by export/import.
"""
from __future__ import annotations

import hashlib
import re
import shlex
import shutil
from pathlib import Path
from typing import Any

from .. import schema, swayconfig, swayipc
from . import Context

WALLPAPER_DIR = "wallpapers"
_BG_RE = re.compile(r"^output\s+(\*|\"\*\")\s+(?:bg|background)\s+(.*)$")


def _quote(path: str) -> str:
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def adopt_image(src: str, data_dir: Path) -> str:
    """Copy an image into the app folder; returns the stored (relative) path."""
    path = Path(src).expanduser()
    if not path.is_absolute():  # already one of ours
        if (data_dir / path).is_file():
            return str(path)
        raise ValueError(f"background.image: file not found: {src}")
    if not path.is_file():
        raise ValueError(f"background.image: file not found: {src}")
    dest_dir = data_dir / WALLPAPER_DIR
    if path.parent == dest_dir.resolve():
        return f"{WALLPAPER_DIR}/{path.name}"
    digest = hashlib.sha1(path.read_bytes()).hexdigest()[:10]
    dest = dest_dir / f"{digest}-{path.name}"
    if not dest.exists():
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    return f"{WALLPAPER_DIR}/{dest.name}"


class BackgroundModule:
    sections = ("background",)
    tolerated_errors = ()
    depends_on = ("theme",)

    def commands(self, section: str, v: dict[str, Any], changed: set[str] | None,
                 ctx: Context | None = None) -> list[str]:
        color = v["color"] or (ctx.theme.bg if ctx is not None and ctx.theme else "#000000")
        if v["image"] and ctx is not None:
            path = str(ctx.data_dir / v["image"])
            return [f"output * bg {_quote(path)} {v['mode']} {color}"]
        return [f"output * bg {color} solid_color"]

    def before_set(self, section: str, name: str, value: Any, ctx: Context) -> Any:
        if name == "image" and isinstance(value, str) and value:
            return adopt_image(value, ctx.data_dir)
        return value

    def import_current(self, ipc: swayipc.Connection, config: swayconfig.Config,
                       ctx: Context) -> dict[str, dict[str, Any]]:
        found: dict[str, Any] = {}
        for cline in config.lines:
            if cline.blocks:
                continue
            line = cline.text
            m = _BG_RE.match(line)
            if not m:
                continue
            try:
                args = shlex.split(m.group(2))
                raw_m = _BG_RE.match(cline.raw)
                raw_args = shlex.split(raw_m.group(2)) if raw_m else args
            except ValueError:
                continue
            # a color taken from a variable ($paper_bg) belongs to the theme:
            # leave it unset so it keeps following the theme
            color_idx = 0 if len(args) >= 2 and args[1] == "solid_color" else 2
            follows_theme = len(raw_args) > color_idx and raw_args[color_idx].startswith("$")
            if len(args) >= 2 and args[1] == "solid_color":
                found = {"image": ""} if follows_theme else {"image": "", "color": args[0]}
            elif len(args) >= 2:
                found = {"mode": args[1]}
                if len(args) >= 3 and not follows_theme:
                    found["color"] = args[2]
                try:
                    found["image"] = adopt_image(args[0], ctx.data_dir)
                except ValueError:
                    found.pop("mode")
        # keep only values the schema accepts (e.g. a named color isn't supported)
        valid = {}
        for name, value in found.items():
            try:
                valid[name] = schema.lookup("background", name).validate(value)
            except ValueError:
                pass
        return {"background": valid}

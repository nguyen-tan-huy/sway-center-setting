"""Export/import of settings as one .zip file, to carry a setup to a new
machine: the shared settings (not machine-specific ones like displays or
location), the wallpaper image and the user's own themes.
"""
from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from . import __version__, schema, themes
from .modules.background import WALLPAPER_DIR
from .store import Store

FORMAT = "swayctl-center-backup"
VERSION = 1
MAX_FILE_BYTES = 64 * 1024 * 1024


class BackupError(ValueError):
    pass


def export(store: Store, dest: Path) -> dict[str, Any]:
    values = store.scope_values(schema.SHARED)
    files: list[Path] = []
    image = values.get("background", {}).get("image", "")
    if image and (store.dir / image).is_file():
        files.append(store.dir / image)
    files += sorted(themes.user_theme_dir(store.dir).glob("*.json"))
    manifest = {"format": FORMAT, "version": VERSION, "app_version": __version__,
                "created": datetime.now().astimezone().isoformat(timespec="seconds")}
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("settings.json", json.dumps(values, indent=2, sort_keys=True))
        for f in files:
            z.write(f, str(f.relative_to(store.dir)))
    tmp.replace(dest)
    return {"path": str(dest), "sections": sorted(values), "files": [str(f.relative_to(store.dir)) for f in files]}


def _safe_member(name: str) -> PurePosixPath | None:
    """Only plain files under wallpapers/ or themes/, no path tricks."""
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or len(p.parts) != 2:
        return None
    if p.parts[0] not in (WALLPAPER_DIR, "themes"):
        return None
    return p


def read(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[str]]:
    """Validate a backup; returns (manifest, settings, skipped entries)."""
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        raise BackupError(f"not a swayctl-center backup: {e}") from None
    with z:
        try:
            manifest = json.loads(z.read("manifest.json"))
            settings = json.loads(z.read("settings.json"))
        except (KeyError, ValueError) as e:
            raise BackupError(f"not a swayctl-center backup: {e}") from None
    if manifest.get("format") != FORMAT:
        raise BackupError("not a swayctl-center backup")
    if manifest.get("version", 0) > VERSION:
        raise BackupError("this backup was made by a newer swayctl-center; update the app first")
    if not isinstance(settings, dict):
        raise BackupError("backup settings are malformed")
    clean: dict[str, dict[str, Any]] = {}
    skipped = []
    for section, items in settings.items():
        if not isinstance(items, dict):
            skipped.append(section)
            continue
        for name, value in items.items():
            try:
                key = schema.lookup(section, name)
                if key.scope != schema.SHARED:
                    raise ValueError("machine-specific")
                clean.setdefault(section, {})[name] = key.validate(value)
            except (KeyError, ValueError):
                skipped.append(f"{section}.{name}")
    return manifest, clean, skipped


def restore(store: Store, path: Path) -> dict[str, Any]:
    manifest, settings, skipped = read(path)
    extracted = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            member = _safe_member(info.filename)
            if member is None or info.is_dir():
                continue
            if info.file_size > MAX_FILE_BYTES:
                skipped.append(info.filename)
                continue
            dest = store.dir.joinpath(*member.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(info))
            extracted.append(str(member))
    image = settings.get("background", {}).get("image")
    if image and not (store.dir / image).is_file():
        settings["background"].pop("image")
        skipped.append("background.image (file missing from backup)")
    store.replace_scope(schema.SHARED, settings)
    return {"created": manifest.get("created"), "sections": sorted(settings),
            "files": extracted, "skipped": skipped}

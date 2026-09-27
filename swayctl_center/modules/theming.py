"""Other programs' config files rendered from templates with the active theme
and font (fuzzel, kitty, btop, GTK 3 CSS...). See theming.py for placeholders."""
from __future__ import annotations

import subprocess
from typing import Any

from pathlib import Path

from .. import owned, theming
from . import Context


class ThemingModule:
    sections = ("theming",)
    tolerated_errors = ()
    depends_on = ("theme", "font")

    def commands(self, section, v, changed, ctx=None) -> list[str]:
        return []

    def apply_extra(self, section: str, v: dict[str, Any], changed: set[str] | None,
                    ctx: Context | None = None) -> list[str]:
        if ctx is None or ctx.theme is None:
            return []
        values = theming.placeholders(ctx.theme, (ctx.values or {}).get("font"))
        errors = []
        for t in v["templates"]:
            if not t.get("enabled", True):
                continue
            src, dest = theming.expand(t["template"]), theming.expand(t["output"])
            try:
                content = theming.render(src.read_text(), values)
                try:
                    if dest.read_text() == content:
                        continue
                except OSError:
                    pass
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content)
            except OSError as e:
                errors.append(f"theming: {src}: {e.strerror or e}")
                continue
            if t["reload"]:
                subprocess.Popen(["sh", "-c", t["reload"]], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
        return errors

    def before_set(self, section, name, value, ctx):
        """Templates are kept in the app's folder, whatever file was picked."""
        if name != "templates":
            return value
        out = []
        for t in value:
            t = dict(t)
            src = Path(t["template"]).name
            dest = ctx.data_dir / "templates" / src
            if dest.exists() and not owned._is_inside(theming.expand(t["template"]), ctx.data_dir):
                # another app's template of the same name is there already
                src = f"{Path(t['output']).parent.name}-{src}"
            t["template"] = owned.adopt(t["template"], ctx.data_dir, "templates", src)
            out.append(t)
        return out

    def import_current(self, ipc, config, ctx) -> dict[str, dict[str, Any]]:
        return {}

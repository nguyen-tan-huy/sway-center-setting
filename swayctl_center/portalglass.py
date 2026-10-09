"""xdg-desktop-portal-gtk's dialogs (file chooser, app chooser, print) as
liquid glass, like the settings window.

The portal is a GTK 3 app with its own service, so it alone gets a theme:
a systemd drop-in sets GTK_THEME=SwayctlGlass for it, and that theme is the
desktop's GTK 3 theme (adw-gtk3 / Adwaita) with the panes drawn as milky glass
and everything else clear. swayctl-fx puts glass behind the window and inks
the text (`glass text auto`, the key colour below), so other GTK 3 apps and
~/.config/gtk-3.0 are left alone.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .modules.components import INK_KEY, MILK_INSET, MILK_RIM, milk_fill

APP_ID = "xdg-desktop-portal-gtk"
SERVICE = "xdg-desktop-portal-gtk.service"
THEME_NAME = "SwayctlGlass"
MARK = "/* managed by swayctl-center (liquid glass for the portal's dialogs); edits are overwritten */"


def theme_dir(home: Path) -> Path:
    return home / ".local/share/themes" / THEME_NAME


def dropin_path(home: Path) -> Path:
    return home / ".config/systemd/user" / f"{SERVICE}.d" / "swayctl-glass.conf"


def base_import(dark: bool) -> str:
    """The desktop's GTK 3 theme to build on (adw-gtk3 when installed)."""
    name = "adw-gtk3-dark" if dark else "adw-gtk3"
    for d in (Path("/usr/share/themes"), Path.home() / ".local/share/themes", Path.home() / ".themes"):
        css = d / name / "gtk-3.0" / "gtk.css"
        if css.is_file():
            return f'@import url("file://{css}");'
    variant = "-dark" if dark else ""
    return f'@import url("resource:///org/gtk/libgtk/theme/Adwaita/gtk-contained{variant}.css");'


def css(dark: bool, accent: str, accent_fg: str, opacity: float) -> str:
    """GTK 3 CSS: clear window, milky panes, text in the key ink."""
    pane = milk_fill(opacity)
    chip = milk_fill(opacity * 0.85)
    k = INK_KEY
    return f"""{MARK}
{base_import(dark)}

/* the window is clear: swayctl-fx shapes the glass by what's drawn */
window, window.background, .background, dialog, messagedialog, decoration,
.dialog-vbox, stack, scrolledwindow, viewport, paned, notebook, notebook > stack,
treeview.view, iconview, list, .view, placessidebar list,
filechooser, filechooser box, actionbar, .titlebar:not(headerbar), infobar {{
  background: none; background-color: transparent; background-image: none;
  box-shadow: none; border-color: transparent;
}}
decoration {{ border-radius: 18px; box-shadow: none; margin: 0; }}
paned > separator, separator {{ background: none; background-color: transparent; }}

/* panes: the header, the places, the file list, fields and buttons */
headerbar {{
  background: {pane}; border: {MILK_RIM}; border-radius: 18px 18px 0 0; box-shadow: {MILK_INSET};
  min-height: 46px;
}}
placessidebar.sidebar, filechooser scrolledwindow.view, filechooser .view scrolledwindow,
filechooser paned > box:last-child scrolledwindow, popover, menu, .menu, .csd.popup decoration {{
  background: {pane}; border: {MILK_RIM}; border-radius: 18px; box-shadow: {MILK_INSET};
}}
placessidebar {{ margin: 4px 4px 8px 8px; }}
placessidebar row {{ border-radius: 999px; margin: 2px 6px; }}
placessidebar row:selected {{ background: alpha({accent}, 0.90); }}
filechooser paned > box:last-child scrolledwindow {{ margin: 4px 8px 8px 4px; }}
filechooser treeview.view header button:not(.flat) {{
  background: none; border: none; border-radius: 0; box-shadow: none;
}}
treeview.view:selected, treeview.view:selected:focus, iconview:selected {{
  background: alpha({accent}, 0.90); color: {accent_fg};
}}
treeview.view:hover:not(:selected) {{ background: alpha(white, 0.10); }}

button:not(.flat):not(.suggested-action):not(.destructive-action):not(.titlebutton),
.path-bar button, entry, spinbutton, combobox button {{
  background: {chip}; background-image: none; border: {MILK_RIM}; box-shadow: {MILK_INSET};
}}
button:not(.flat):not(.titlebutton), .path-bar button, combobox button {{ border-radius: 999px; }}
.linked > button {{ border-radius: 999px; margin: 0 2px; }}
entry, spinbutton {{ border-radius: 12px; }}
button.suggested-action {{
  background: alpha({accent}, 0.92); background-image: none; color: {accent_fg};
  border: {MILK_RIM}; box-shadow: {MILK_INSET}; border-radius: 999px;
}}
button.destructive-action {{ border-radius: 999px; }}
/* the header's own buttons (Cancel, search) are chips in every state, not the
   theme's headerbar fills (the class is repeated to outrank its long selectors) */
headerbar button.text-button.text-button.text-button:not(.suggested-action):not(.destructive-action),
headerbar button.image-button.image-button.image-button:not(.suggested-action):not(.titlebutton) {{
  background: {chip}; background-image: none; border: {MILK_RIM}; box-shadow: {MILK_INSET};
}}
headerbar button.text-button.text-button.text-button:hover:not(.suggested-action):not(.destructive-action),
headerbar button.text-button.text-button.text-button:active:not(.suggested-action):not(.destructive-action),
headerbar button.image-button.image-button.image-button:hover:not(.suggested-action):not(.titlebutton),
headerbar button.image-button.image-button.image-button:checked:not(.suggested-action):not(.titlebutton) {{
  background: {pane}; background-image: none;
}}

/* key ink: swayctl-fx colours this text light or dark from what's behind */
label, treeview.view, iconview, entry, entry text, spinbutton, button, image,
placessidebar row, .path-bar button, menuitem, modelbutton, checkbutton, radiobutton {{
  color: {k}; text-shadow: none; -gtk-icon-shadow: none;
}}
entry selection, treeview.view:selected, treeview.view:selected:focus,
placessidebar row:selected, placessidebar row:selected label, placessidebar row:selected image,
button.suggested-action, button.suggested-action label, button.suggested-action image,
iconview:selected {{ color: {accent_fg}; }}
"""


def dropin_text() -> str:
    return ("# managed by swayctl-center: liquid glass for the portal's dialogs\n"
            "[Service]\n"
            f"Environment=GTK_THEME={THEME_NAME}\n")


def _write(path: Path, text: str) -> bool:
    try:
        if path.read_text() == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return True


def sync(on: bool, theme_css: str, home: Path | None = None) -> bool:
    """Write (on) or remove (off) the theme and the drop-in; True if changed.
    The portal reads its theme at start, so a change restarts it (try-restart:
    only if running; D-Bus starts it again with the new theme otherwise)."""
    home = home or Path.home()
    changed = False
    css_path = theme_dir(home) / "gtk-3.0" / "gtk.css"
    dropin = dropin_path(home)
    if on:
        changed |= _write(css_path, theme_css)
        changed |= _write(dropin, dropin_text())
    elif dropin.exists():
        dropin.unlink()
        changed = True
    if changed:
        for argv in (["systemctl", "--user", "daemon-reload"],
                     ["systemctl", "--user", "try-restart", SERVICE]):
            try:
                subprocess.run(argv, capture_output=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
    return changed

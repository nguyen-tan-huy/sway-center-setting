"""xdg-desktop-portal-gtk's dialogs (file chooser, app chooser, print) as
one sheet of frosted glass.

The portal is a GTK 3 app with its own service, so it alone gets a theme:
a systemd drop-in sets GTK_THEME=SwayctlGlass for it, and that theme is the
desktop's GTK 3 theme (adw-gtk3 / Adwaita) with the whole window one panel
of the theme's surface, mostly opaque, over swayctl-fx's glass (blur and
refraction behind it). Unlike the settings window or ChoSua it isn't clear
panes on the desktop: a dialog is read as one sheet, and its text is the
theme's own (no ink from the compositor). Other GTK 3 apps and
~/.config/gtk-3.0 are left alone.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

APP_ID = "xdg-desktop-portal-gtk"
SERVICE = "xdg-desktop-portal-gtk.service"
THEME_NAME = "SwayctlGlass"
MARK = "/* managed by swayctl-center (liquid glass for the portal's dialogs); edits are overwritten */"
# the sheet's surface and text, as the shell's light/dark glass (components.adaptive_css)
SURFACE = {True: ("#1c1c1e", "#f5f5f7"), False: ("#f5f5f7", "#1d1d1f")}


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
    """GTK 3 CSS: the window one frosted sheet; `opacity` (the shell's milk,
    0.04..0.2) makes it a little thicker."""
    surface, fg = SURFACE[dark]
    sheet = f"alpha({surface}, {min(0.66 + opacity, 0.9):.2f})"
    rim = "alpha(white, 0.22)" if dark else "alpha(white, 0.70)"
    shine = "alpha(white, 0.14)" if dark else "alpha(white, 0.80)"
    hair = f"alpha({fg}, 0.12)"
    chip = f"alpha({fg}, 0.07)"
    hover = f"alpha({fg}, 0.12)"
    return f"""{MARK}
{base_import(dark)}

/* one sheet of frosted glass: the window is the panel, inside it is clear */
window.background, dialog.background {{
  background: {sheet}; background-image: none; border-radius: 18px; color: {fg};
}}
decoration, .csd decoration, dialog.csd decoration, window.csd decoration {{
  border-radius: 18px; border: 1px solid {rim}; box-shadow: inset 0 1px 0 {shine}; margin: 0;
}}
.dialog-vbox, stack, scrolledwindow, viewport, paned, notebook, notebook > stack,
treeview.view, iconview, list, .view, placessidebar, placessidebar.sidebar, placessidebar list,
filechooser, filechooser box, actionbar, .titlebar:not(headerbar), infobar, headerbar {{
  background: none; background-color: transparent; background-image: none;
  box-shadow: none; border-color: transparent;
}}
/* the header is drawn apart from the window's background (CSD): the sheet too */
headerbar, headerbar:backdrop {{
  background: {sheet}; background-image: none;
  border-radius: 18px 18px 0 0; min-height: 46px;
  border-width: 0 0 1px 0; border-style: solid; border-color: {hair};
}}
paned > separator, paned.horizontal > separator, paned > separator.wide {{
  background: none; background-color: {hair}; background-image: none;
  min-width: 1px; min-height: 1px; margin: 0; padding: 0; border: none; box-shadow: none;
}}
placessidebar, .sidebar, placessidebar.sidebar, placessidebar > viewport, placessidebar scrolledwindow {{
  border: none; box-shadow: none;
}}
separator {{ background: {hair}; }}
/* scrollbars float on the sheet: no trough */
scrollbar, scrollbar contents, scrollbar trough, scrollbar:backdrop {{
  background: none; background-color: transparent; border: none; box-shadow: none;
}}
scrollbar slider {{ background: alpha({fg}, 0.35); border: none; }}
popover, menu, .menu, .csd.popup decoration {{
  background: alpha({surface}, 0.92); border: 1px solid {rim}; border-radius: 14px;
}}

/* the places and the files */
placessidebar row {{ border-radius: 999px; margin: 2px 6px; }}
placessidebar row:hover:not(:selected) {{ background: {hover}; }}
placessidebar row:selected {{ background: alpha({accent}, 0.90); }}
filechooser treeview.view header button:not(.flat) {{
  background: none; border: none; border-radius: 0; box-shadow: none;
}}
treeview.view:hover:not(:selected) {{ background: {chip}; }}
treeview.view:selected, treeview.view:selected:focus, iconview:selected {{
  background: alpha({accent}, 0.90); color: {accent_fg};
}}

/* controls: soft capsules on the sheet */
button:not(.flat):not(.suggested-action):not(.destructive-action):not(.titlebutton),
.path-bar button, entry, spinbutton, combobox button {{
  background: {chip}; background-image: none; border: 1px solid {hair}; box-shadow: none;
}}
button:not(.flat):not(.titlebutton), .path-bar button, combobox button {{ border-radius: 999px; }}
.linked > button {{ border-radius: 999px; margin: 0 2px; }}
entry, spinbutton {{ border-radius: 12px; }}
button.suggested-action {{
  background: alpha({accent}, 0.95); background-image: none; color: {accent_fg};
  border: none; box-shadow: none; border-radius: 999px;
}}
button.destructive-action {{ border-radius: 999px; }}
/* the header's own buttons (Cancel, search), in every state, over the theme's
   headerbar fills (the class is repeated to outrank its long selectors) */
headerbar button.text-button.text-button.text-button:not(.suggested-action):not(.destructive-action),
headerbar button.image-button.image-button.image-button:not(.suggested-action):not(.titlebutton) {{
  background: {chip}; background-image: none; border: 1px solid {hair}; box-shadow: none;
}}
headerbar button.text-button.text-button.text-button:hover:not(.suggested-action):not(.destructive-action),
headerbar button.text-button.text-button.text-button:active:not(.suggested-action):not(.destructive-action),
headerbar button.image-button.image-button.image-button:hover:not(.suggested-action):not(.titlebutton),
headerbar button.image-button.image-button.image-button:checked:not(.suggested-action):not(.titlebutton) {{
  background: {hover}; background-image: none;
}}

/* the theme's text on the sheet; what sits on the accent keeps its own */
label, treeview.view, iconview, entry, spinbutton, button, image,
placessidebar row, .path-bar button, menuitem, modelbutton, checkbutton, radiobutton {{
  color: {fg}; text-shadow: none; -gtk-icon-shadow: none;
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

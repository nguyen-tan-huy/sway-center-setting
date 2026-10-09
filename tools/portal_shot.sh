#!/bin/sh
# xdg-desktop-portal-gtk's file chooser as liquid glass (portalglass.py): the
# daemon writes the SwayctlGlass theme, a GTK 3 file chooser with the portal's
# app_id stands in for the portal's dialog.
#   WALL=lockwall.jpg THEME=dark tools/sandbox.sh --fx /home/repo/tools/portal_shot.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/portal-daemon.log 2>&1 &
sleep 2.5
python3 -m swayctl_center set effects.glass true >/dev/null
python3 -m swayctl_center set appearance.mode "${THEME:-dark}" >/dev/null
wall=/tmp/out/${WALL:-wall-text.png}
[ -f "$wall" ] && python3 -m swayctl_center set background.image "$wall" >/dev/null
sleep 1.5
mkdir -p "$HOME/Documents" "$HOME/Pictures" "$HOME/Music"
touch "$HOME/Documents/report.pdf" "$HOME/Documents/notes.txt" "$HOME/Pictures/photo.jpg"
GTK_THEME=SwayctlGlass python3 - <<'PY' > /tmp/out/portal-gtk.log 2>&1 &
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk
GLib.set_prgname("xdg-desktop-portal-gtk")
d = Gtk.FileChooserDialog(title="Open File", action=Gtk.FileChooserAction.OPEN)
d.add_buttons("_Cancel", Gtk.ResponseType.CANCEL, "_Open", Gtk.ResponseType.ACCEPT)
d.set_default_response(Gtk.ResponseType.ACCEPT)
d.set_current_folder(GLib.get_home_dir() + "/Documents")
d.connect("response", lambda *_: Gtk.main_quit())
d.show_all()
Gtk.main()
PY
sleep 3
swaymsg '[app_id="xdg-desktop-portal-gtk"] floating enable, resize set 1000 640, move position center' >/dev/null 2>&1 || true
sleep 1
grim "/tmp/out/portal-${THEME:-dark}.png"
# RAW=1: the app's own pixels too (compositor glass off)
if [ "${RAW:-0}" = 1 ]; then
  swaymsg '[app_id="xdg-desktop-portal-gtk"] glass disable' >/dev/null 2>&1 || true
  sleep 0.5
  grim "/tmp/out/portal-${THEME:-dark}-raw.png"
fi

"""System page: backup/restore, health checks with fixes, setup assistant."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from .. import doctor  # noqa: E402
from ..client import CallError, DaemonUnavailable  # noqa: E402
from .async_util import run_async  # noqa: E402


def heading(text: str, level: str = "title-2") -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0)
    label.add_css_class(level)
    return label


def zip_filter() -> Gio.ListStore:
    f = Gtk.FileFilter(name="swayctl-center backup (*.zip)")
    f.add_pattern("*.zip")
    store = Gio.ListStore.new(Gtk.FileFilter)
    store.append(f)
    return store


class ChecksList(Gtk.Box):
    """doctor.run_checks() as a list, with a Fix button where one exists."""

    def __init__(self, show_ok: bool = True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.show_ok = show_ok
        self.summary = Gtk.Label(xalign=0, wrap=True)
        self.append(self.summary)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("rich-list")
        self.frame = Gtk.Frame(child=self.list)
        self.append(self.frame)
        self.reload()

    def reload(self) -> None:
        self.summary.set_label("Checking…")
        run_async(doctor.run_checks, self._show)

    def _show(self, checks):
        self.list.remove_all()
        if isinstance(checks, Exception):
            self.summary.set_label(f"Couldn't run the checks: {checks}")
            return GLib.SOURCE_REMOVE
        problems = [c for c in checks if not c.ok and not c.optional]
        optional = [c for c in checks if not c.ok and c.optional]
        if problems:
            self.summary.set_label(f"{len(problems)} thing(s) need attention.")
        elif optional:
            self.summary.set_label("Everything needed is in place. Some optional extras are missing.")
        else:
            self.summary.set_label("Everything is in place.")
        shown = [c for c in checks if self.show_ok or not c.ok]
        self.frame.set_visible(bool(shown))
        for c in shown:
            box = Gtk.Box(spacing=10)
            icon = "object-select-symbolic" if c.ok else ("dialog-information-symbolic" if c.optional
                                                       else "dialog-warning-symbolic")
            box.append(Gtk.Image.new_from_icon_name(icon))
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            text.append(Gtk.Label(label=c.label, xalign=0, wrap=True))
            detail = c.detail if c.ok or c.fix else " — ".join(x for x in (c.detail, c.fix_hint) if x)
            if detail:
                d = Gtk.Label(label=detail, xalign=0, wrap=True, selectable=True)
                d.add_css_class("dim-label")
                d.add_css_class("caption")
                text.append(d)
            box.append(text)
            if not c.ok and c.fix:
                btn = Gtk.Button(label="Fix", valign=Gtk.Align.CENTER)
                btn.connect("clicked", self._fix, c.fix)
                box.append(btn)
            self.list.append(Gtk.ListBoxRow(activatable=False, child=box))
        return GLib.SOURCE_REMOVE

    def _fix(self, button, fix):
        button.set_sensitive(False)
        button.set_label("Working…")

        def done(err):
            if isinstance(err, Exception) or err:
                self.summary.set_label(f"Couldn't fix it: {err}")
            self.reload()
            return GLib.SOURCE_REMOVE
        run_async(lambda: doctor.apply_fix(fix), done)


class SystemPage(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                         margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        self.win = win
        self.append(heading("System"))
        self.parts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.append(self.parts)

        self.append(heading("Backup", "heading"))
        intro = Gtk.Label(xalign=0, wrap=True, label=(
            "Save your settings, wallpaper and themes to one file, then restore them on another "
            "computer (or after reinstalling). Display layout and location stay with each machine."))
        intro.add_css_class("dim-label")
        self.append(intro)
        buttons = Gtk.Box(spacing=8)
        export = Gtk.Button(label="Export…")
        export.connect("clicked", self._export)
        imp = Gtk.Button(label="Import…")
        imp.connect("clicked", self._import)
        buttons.append(export)
        buttons.append(imp)
        self.append(buttons)
        self.backup_result = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.append(self.backup_result)

        self.append(heading("Checks", "heading"))
        self.checks = ChecksList()
        self.append(self.checks)
        row = Gtk.Box(spacing=8)
        recheck = Gtk.Button(label="Check again")
        recheck.connect("clicked", lambda _b: self.checks.reload())
        assistant = Gtk.Button(label="Run setup assistant")
        assistant.connect("clicked", lambda _b: win.open_assistant())
        row.append(recheck)
        row.append(assistant)
        self.append(row)

    def add_part(self, title: str, intro: str, widget: Gtk.Widget) -> None:
        self.parts.append(heading(title, "heading"))
        if intro:
            label = Gtk.Label(label=intro, xalign=0, wrap=True)
            label.add_css_class("dim-label")
            self.parts.append(label)
        self.parts.append(widget)

    def _export(self, _b):
        dialog = Gtk.FileDialog(title="Export settings", initial_name=f"swayctl-center-{date.today()}.zip")
        dialog.set_filters(zip_filter())

        def done(d, result):
            try:
                f = d.save_finish(result)
            except GLib.Error:
                return
            try:
                summary = self.win.client.export(f.get_path())
            except (DaemonUnavailable, CallError) as e:
                self.backup_result.set_label(f"Export failed: {e}")
                return
            extra = f" and {len(summary['files'])} file(s)" if summary["files"] else ""
            self.backup_result.set_label(f"Saved {len(summary['sections'])} sections{extra} to {summary['path']}")
        dialog.save(self.win, None, done)

    def _import(self, _b):
        import_backup(self.win, self.backup_result.set_label)


def import_backup(win, report, after=None) -> None:
    """Pick a backup, confirm, import. `report(text)` shows the outcome."""
    dialog = Gtk.FileDialog(title="Import settings")
    dialog.set_filters(zip_filter())

    def picked(d, result):
        try:
            f = d.open_finish(result)
        except GLib.Error:
            return
        confirm = Gtk.AlertDialog(message="Replace your settings with this backup?",
                                  detail="Everything except display layout and location is replaced.",
                                  buttons=["Cancel", "Import"], cancel_button=0, default_button=1)

        def answered(dlg, res):
            try:
                if dlg.choose_finish(res) != 1:
                    return
            except GLib.Error:
                return
            try:
                s = win.client.import_(f.get_path())
            except (DaemonUnavailable, CallError) as e:
                report(f"Import failed: {e}")
                return
            skipped = f" Skipped: {', '.join(s['skipped'])}." if s["skipped"] else ""
            report(f"Restored {len(s['sections'])} sections from {Path(f.get_path()).name}"
                   f" (made {s.get('created') or 'unknown'}).{skipped}")
            win.refresh_everything()
            if after:
                after()
        confirm.choose(win, None, answered)
    dialog.open(win, None, picked)

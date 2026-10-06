"""First-run setup assistant: checks, restore a backup, pick what the app runs."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from ..client import CallError, DaemonUnavailable  # noqa: E402
from . import ui_state  # noqa: E402
from .system import ChecksList, heading, import_backup  # noqa: E402

COMPONENTS = [
    ("bar", "Bar", "waybar: workspaces, clock, volume, network, battery"),
    ("notifications", "Notifications", "swaync: pop-ups and a notification center"),
    ("idle", "Lock & idle", "swayidle + swaylock: lock and turn the screen off when idle"),
    ("clipboard", "Clipboard history", "cliphist: remember what you copy"),
    ("input_method", "Input method", "fcitx5: type Vietnamese, Chinese, Japanese…"),
    ("polkit_agent", "Password prompt", "polkit-gnome: asks for your password when a task needs it"),
]


class SetupAssistant(Gtk.Window):
    def __init__(self, win):
        super().__init__(title="Set up ChoCaiDat", transient_for=win, modal=True,
                         application=win.get_application(),
                         default_width=620, default_height=560)
        self.win = win
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(outer)
        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        outer.append(self.stack)
        self.steps = ["welcome", "restore", "components", "done"]
        self.stack.add_named(self._page(self._welcome()), "welcome")
        self.stack.add_named(self._page(self._restore()), "restore")
        self.stack.add_named(self._page(self._components()), "components")
        self.stack.add_named(self._page(self._done()), "done")

        nav = Gtk.Box(spacing=8, margin_top=12, margin_bottom=12, margin_start=18, margin_end=18)
        self.back = Gtk.Button(label="Back")
        self.back.connect("clicked", lambda _b: self._go(-1))
        self.step_label = Gtk.Label(hexpand=True)
        self.step_label.add_css_class("dim-label")
        self.next = Gtk.Button(label="Next")
        self.next.add_css_class("suggested-action")
        self.next.connect("clicked", lambda _b: self._go(1))
        nav.append(self.back)
        nav.append(self.step_label)
        nav.append(self.next)
        outer.append(Gtk.Separator())
        outer.append(nav)
        self._update_nav()

    def _page(self, content: Gtk.Widget) -> Gtk.Widget:
        content.set_margin_top(24)
        content.set_margin_bottom(12)
        content.set_margin_start(24)
        content.set_margin_end(24)
        return Gtk.ScrolledWindow(child=content, hscrollbar_policy=Gtk.PolicyType.NEVER)

    def _box(self, title: str, text: str) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(heading(title))
        if text:
            box.append(Gtk.Label(label=text, xalign=0, wrap=True))
        return box

    def _welcome(self):
        box = self._box("Welcome", "ChoCaiDat sets up and manages your sway desktop: displays, "
                        "input, appearance, the bar, notifications and more, without editing config files. "
                        "First, a quick check that everything it needs is installed.")
        box.append(ChecksList(show_ok=False))
        return box

    def _restore(self):
        box = self._box("Restore a backup", "Coming from another computer, or reinstalling? Import a backup "
                        "exported from ChoCaiDat to get your settings back. Otherwise, skip this.")
        btn = Gtk.Button(label="Import a backup…", halign=Gtk.Align.START)
        self.restore_result = Gtk.Label(xalign=0, wrap=True)
        btn.connect("clicked", lambda _b: import_backup(self.win, self.restore_result.set_label,
                                                        after=self._refresh_components))
        box.append(btn)
        box.append(self.restore_result)
        return box

    def _components(self):
        box = self._box("What should ChoCaiDat run?",
                        "It styles these with your theme and font and keeps them running. Anything your own "
                        "sway config already starts is left to you.")
        self.comp_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.comp_list.add_css_class("rich-list")
        box.append(Gtk.Frame(child=self.comp_list))
        self._refresh_components()
        return box

    def _refresh_components(self):
        self.comp_list.remove_all()
        try:
            values = self.win.client.get_all()
            comps = self.win.client.status().get("components", {})
        except (DaemonUnavailable, CallError) as e:
            self.comp_list.append(Gtk.Label(label=f"The settings service isn't available: {e}", wrap=True))
            return
        for section, title, desc in COMPONENTS:
            row = Gtk.Box(spacing=12)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            text.append(Gtk.Label(label=title, xalign=0))
            foreign = comps.get(section, {}).get("foreign_pids")
            sub = Gtk.Label(xalign=0, wrap=True,
                            label=desc + (" — already started by your sway config" if foreign else ""))
            sub.add_css_class("dim-label")
            sub.add_css_class("caption")
            text.append(sub)
            row.append(text)
            sw = Gtk.Switch(active=values[section]["managed"], valign=Gtk.Align.CENTER)
            sw.set_sensitive(not foreign or values[section]["managed"])
            sw.connect("notify::active", lambda s, _p, sec=section: self.win.set(f"{sec}.managed", s.get_active()))
            row.append(sw)
            self.comp_list.append(Gtk.ListBoxRow(activatable=False, child=row))

    def _done(self):
        return self._box("All set", "Your desktop is ready. Everything can be changed later in this window; "
                         "the System page has backup, checks and this assistant again.")

    def _go(self, delta: int):
        i = self.steps.index(self.stack.get_visible_child_name()) + delta
        if i >= len(self.steps):
            ui_state.set("setup_done", True)
            self.close()
            return
        self.stack.set_visible_child_name(self.steps[max(0, i)])
        if self.steps[i] == "components":
            self._refresh_components()
        self._update_nav()

    def _update_nav(self):
        i = self.steps.index(self.stack.get_visible_child_name())
        self.back.set_sensitive(i > 0)
        self.next.set_label("Finish" if i == len(self.steps) - 1 else "Next")
        self.step_label.set_label(f"Step {i + 1} of {len(self.steps)}")

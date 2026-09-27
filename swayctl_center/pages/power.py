"""Power page: battery, power profile and brightness, read live."""
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from ..system import power  # noqa: E402
from .async_util import run_async  # noqa: E402

REFRESH_S = 20
PROFILE_LABELS = {"power-saver": "Power saver", "balanced": "Balanced", "performance": "Performance"}


class PowerPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                         margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        title = Gtk.Label(label="Power", xalign=0)
        title.add_css_class("title-2")
        self.append(title)

        self.battery_label = Gtk.Label(xalign=0)
        self.battery_bar = Gtk.LevelBar(min_value=0, max_value=100)
        self.append(self.battery_label)
        self.append(self.battery_bar)

        rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        rows.add_css_class("rich-list")
        frame = Gtk.Frame(child=rows)
        self.append(frame)

        self.profile_model = Gtk.StringList()
        self.profile_dd = Gtk.DropDown(model=self.profile_model, valign=Gtk.Align.CENTER)
        self.profile_dd.connect("notify::selected", self._profile_changed)
        self.profile_row = self._row("Power mode", self.profile_dd)
        rows.append(self.profile_row)

        self.bright = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
        self.bright.set_hexpand(True)
        self.bright.set_size_request(240, -1)
        self.bright.connect("value-changed", self._brightness_changed)
        self.bright_row = self._row("Screen brightness", self.bright)
        rows.append(self.bright_row)

        self.error = Gtk.Label(xalign=0, wrap=True)
        self.error.add_css_class("dim-label")
        self.append(self.error)

        self.profiles: list[str] = []
        self.updating = False
        self._bright_timer = 0
        GLib.idle_add(self.reload)
        GLib.timeout_add_seconds(REFRESH_S, self._auto_refresh)

    def _row(self, title, control):
        box = Gtk.Box(spacing=12)
        box.append(Gtk.Label(label=title, xalign=0, hexpand=True))
        box.append(control)
        row = Gtk.ListBoxRow(activatable=False, child=box)
        return row

    def _auto_refresh(self):
        if self.get_mapped():
            self.reload()
        return GLib.SOURCE_CONTINUE

    def reload(self):
        run_async(lambda: (power.battery(), power.power_profiles(), power.brightness()), self._show)
        return GLib.SOURCE_REMOVE

    def _show(self, result):
        if isinstance(result, Exception):
            self.error.set_label(str(result))
            return GLib.SOURCE_REMOVE
        bat, profiles, bright = result
        self.updating = True
        try:
            if bat is None:
                self.battery_label.set_label("No battery (desktop, or UPower isn't running)")
                self.battery_bar.set_visible(False)
            else:
                timed = bat.state in ("charging", "discharging")
                left = power.format_duration(bat.seconds_left) if timed else ""
                extra = f", {left} {'to full' if bat.state == 'charging' else 'left'}" if left else ""
                self.battery_label.set_label(f"Battery {bat.percentage:.0f}% — {bat.state}{extra}")
                self.battery_bar.set_value(bat.percentage)
                self.battery_bar.set_visible(True)
            self.profile_row.set_visible(profiles is not None)
            if profiles:
                active, available = profiles
                if available != self.profiles:
                    self.profiles = available
                    self.profile_model.splice(0, self.profile_model.get_n_items(),
                                              [PROFILE_LABELS.get(p, p) for p in available])
                if active in available:
                    self.profile_dd.set_selected(available.index(active))
            self.bright_row.set_visible(bright is not None)
            if bright is not None and not self._bright_timer:
                self.bright.set_value(bright.percent)
        finally:
            self.updating = False
        return GLib.SOURCE_REMOVE

    def _profile_changed(self, dd, _p):
        i = dd.get_selected()
        if self.updating or i >= len(self.profiles):
            return
        run_async(lambda: power.set_power_profile(self.profiles[i]), self._after_action)

    def _brightness_changed(self, scale):
        if self.updating:
            return
        if self._bright_timer:
            GLib.source_remove(self._bright_timer)

        def fire():
            self._bright_timer = 0
            value = int(scale.get_value())
            run_async(lambda: power.set_brightness(value), self._after_action)
            return GLib.SOURCE_REMOVE
        self._bright_timer = GLib.timeout_add(150, fire)

    def _after_action(self, result):
        self.error.set_label(str(result) if isinstance(result, Exception) else "")
        return GLib.SOURCE_REMOVE

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from ..system import audio
from .async_util import run_async


class SoundPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)
        # Guards against reload()'s programmatic set_active/set_value calls
        # re-triggering an apply - only real user interaction should write.
        self._loading = True

        title = Gtk.Label(label="Sound", xalign=0)
        title.add_css_class("title-1")
        self.append(title)

        refresh_btn = Gtk.Button(label="Refresh devices")
        refresh_btn.set_halign(Gtk.Align.START)
        refresh_btn.connect("clicked", lambda *_: self.reload())
        self.append(refresh_btn)

        out_title = Gtk.Label(label="Output", xalign=0)
        out_title.add_css_class("heading")
        self.append(out_title)

        self.output_combo = Gtk.DropDown()
        self.append(self.output_combo)
        self.output_combo.connect("notify::selected", self._on_output_device_changed)

        out_row = Gtk.Box(spacing=8)
        self.output_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 150, 1)
        self.output_scale.set_hexpand(True)
        self.output_scale.set_draw_value(True)
        self.output_scale.set_value_pos(Gtk.PositionType.RIGHT)
        out_row.append(self.output_scale)
        self.output_mute_switch = Gtk.Switch()
        out_row.append(Gtk.Label(label="Mute"))
        out_row.append(self.output_mute_switch)
        self.append(out_row)
        self.output_scale.connect("value-changed", self._on_output_volume_changed)
        self.output_mute_switch.connect("state-set", self._on_output_mute_changed)

        in_title = Gtk.Label(label="Input", xalign=0)
        in_title.add_css_class("heading")
        self.append(in_title)

        self.input_combo = Gtk.DropDown()
        self.append(self.input_combo)
        self.input_combo.connect("notify::selected", self._on_input_device_changed)

        in_row = Gtk.Box(spacing=8)
        self.input_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 150, 1)
        self.input_scale.set_hexpand(True)
        self.input_scale.set_draw_value(True)
        self.input_scale.set_value_pos(Gtk.PositionType.RIGHT)
        in_row.append(self.input_scale)
        self.input_mute_switch = Gtk.Switch()
        in_row.append(Gtk.Label(label="Mute"))
        in_row.append(self.input_mute_switch)
        self.append(in_row)
        self.input_scale.connect("value-changed", self._on_input_volume_changed)
        self.input_mute_switch.connect("state-set", self._on_input_mute_changed)

        self.status_label = Gtk.Label(xalign=0, wrap=True)
        self.append(self.status_label)

        self._sinks: list[audio.Device] = []
        self._sources: list[audio.Device] = []

        # Deferred so the window can appear before the first reload() runs.
        GLib.idle_add(self._reload_once)

    def _reload_once(self):
        self.reload()
        return GLib.SOURCE_REMOVE

    def reload(self):
        # pactl spawns a subprocess per call (4 of them here); run off the
        # GTK thread so switching to/loading this page never freezes the UI.
        run_async(self._gather, self._apply_loaded)

    def _gather(self):
        return {
            "sinks": audio.list_sinks(),
            "sources": audio.list_sources(),
            "cur_sink": audio.default_sink(),
            "cur_source": audio.default_source(),
        }

    def _apply_loaded(self, data):
        self._loading = True
        if isinstance(data, Exception):
            self.status_label.set_label(f"pactl error: {data}")
            self._loading = False
            return GLib.SOURCE_REMOVE

        self._sinks = data["sinks"]
        self._sources = data["sources"]
        cur_sink = data["cur_sink"]
        cur_source = data["cur_source"]

        self._populate_combo(self.output_combo, self._sinks, cur_sink)
        self._populate_combo(self.input_combo, self._sources, cur_source)

        out_dev = next((d for d in self._sinks if d.name == cur_sink), None)
        if out_dev:
            self.output_scale.set_value(out_dev.volume_percent)
            self.output_mute_switch.set_active(out_dev.mute)

        in_dev = next((d for d in self._sources if d.name == cur_source), None)
        if in_dev:
            self.input_scale.set_value(in_dev.volume_percent)
            self.input_mute_switch.set_active(in_dev.mute)

        self.status_label.set_label("")
        self._loading = False
        return GLib.SOURCE_REMOVE

    def _populate_combo(self, combo: Gtk.DropDown, devices: list[audio.Device], current: str):
        labels = [d.description for d in devices] or ["(no device)"]
        combo.set_model(Gtk.StringList.new(labels))
        idx = next((i for i, d in enumerate(devices) if d.name == current), 0)
        combo.set_selected(idx)

    def _selected_device(self, combo: Gtk.DropDown, devices: list[audio.Device]):
        idx = combo.get_selected()
        if devices and 0 <= idx < len(devices):
            return devices[idx]
        return None

    def _on_output_device_changed(self, *_):
        if self._loading:
            return
        dev = self._selected_device(self.output_combo, self._sinks)
        if not dev:
            return
        try:
            audio.set_default_sink(dev.name)
        except Exception as e:
            self.status_label.set_label(f"Failed: {e}")
            return
        self.reload()

    def _on_input_device_changed(self, *_):
        if self._loading:
            return
        dev = self._selected_device(self.input_combo, self._sources)
        if not dev:
            return
        try:
            audio.set_default_source(dev.name)
        except Exception as e:
            self.status_label.set_label(f"Failed: {e}")
            return
        self.reload()

    def _on_output_volume_changed(self, *_):
        if self._loading:
            return
        dev = self._selected_device(self.output_combo, self._sinks)
        if not dev:
            return
        try:
            audio.set_sink_volume(dev.name, int(self.output_scale.get_value()))
        except Exception as e:
            self.status_label.set_label(f"Failed: {e}")

    def _on_input_volume_changed(self, *_):
        if self._loading:
            return
        dev = self._selected_device(self.input_combo, self._sources)
        if not dev:
            return
        try:
            audio.set_source_volume(dev.name, int(self.input_scale.get_value()))
        except Exception as e:
            self.status_label.set_label(f"Failed: {e}")

    def _on_output_mute_changed(self, switch, state):
        if self._loading:
            return False
        dev = self._selected_device(self.output_combo, self._sinks)
        if dev:
            try:
                audio.set_sink_mute(dev.name, state)
            except Exception as e:
                self.status_label.set_label(f"Failed: {e}")
        return False

    def _on_input_mute_changed(self, switch, state):
        if self._loading:
            return False
        dev = self._selected_device(self.input_combo, self._sources)
        if dev:
            try:
                audio.set_source_mute(dev.name, state)
            except Exception as e:
                self.status_label.set_label(f"Failed: {e}")
        return False

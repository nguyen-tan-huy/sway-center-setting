"""swayctl-center daemon: owns the settings store and keeps sway in sync with it.

Every change - a D-Bus Set from the UI/CLI, a hand edit of the store file, or
sway reloading its own config - goes through the same path:
validate -> store -> diff against what was last applied -> apply via sway IPC.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from datetime import datetime, timedelta  # noqa: E402

from . import backup, schema, swayconfig, swayipc, themes  # noqa: E402
from .modules import Context, by_section  # noqa: E402
from .modules import appearance  # noqa: E402
from .state import State  # noqa: E402
from .store import Store  # noqa: E402

log = logging.getLogger(__name__)

INTERFACE = "io.github.huyhappy.SwayctlCenter"
# overridable so a second instance (e.g. against a nested/headless sway) can run
BUS_NAME = os.environ.get("SWAYCTL_CENTER_BUS_NAME", INTERFACE)
OBJECT_PATH = "/io/github/huyhappy/SwayctlCenter"
ERROR_INVALID = f"{INTERFACE}.Error.Invalid"
ERROR_FAILED = f"{INTERFACE}.Error.Failed"

# Values travel as JSON strings: every client (Python, shell via busctl/gdbus)
# can produce and parse them without dealing with D-Bus variant typing.
INTROSPECTION = f"""
<node>
  <interface name="{INTERFACE}">
    <method name="GetSchema"><arg type="s" name="schema_json" direction="out"/></method>
    <method name="GetAll"><arg type="s" name="values_json" direction="out"/></method>
    <method name="Get">
      <arg type="s" name="path" direction="in"/>
      <arg type="s" name="value_json" direction="out"/>
    </method>
    <method name="Set">
      <arg type="s" name="path" direction="in"/>
      <arg type="s" name="value_json" direction="in"/>
    </method>
    <method name="Reset"><arg type="s" name="path" direction="in"/></method>
    <method name="ApplyAll"/>
    <method name="GetStatus"><arg type="s" name="status_json" direction="out"/></method>
    <method name="Action"><arg type="s" name="name" direction="in"/></method>
    <method name="Export">
      <arg type="s" name="path" direction="in"/>
      <arg type="s" name="summary_json" direction="out"/>
    </method>
    <method name="Import">
      <arg type="s" name="path" direction="in"/>
      <arg type="s" name="summary_json" direction="out"/>
    </method>
    <signal name="Changed">
      <arg type="s" name="section"/>
      <arg type="as" name="keys"/>
    </signal>
  </interface>
</node>
"""

DEBOUNCE_MS = 200
OUTPUT_SETTLE_MS = 500
SCHEDULE_CHECK_S = 30
NIGHT_LIGHT_STEP = 250
ACTIONS = ("theme.toggle", "night_light.toggle", "night_light.warmer", "night_light.cooler",
           "lock", "notifications.panel", "notifications.dnd")
# sections that existed before first-start import tracked sections one by one;
# a store created back then already reflects the user's setup for these
# keys added to sections that already existed; a store made before them adopts
# the user's current setup for just these keys instead of taking defaults
KEYS_ADDED_LATER = {
    "layout": ("border_style", "focus_follows_mouse", "mouse_warping", "focus_on_window_activation",
               "workspace_auto_back_and_forth"),
    "input.touchpad": ("scroll_factor", "click_method", "tap_button_map", "drag", "drag_lock",
                       "middle_emulation", "left_handed", "events"),
    "input.pointer": ("scroll_factor", "left_handed", "middle_emulation"),
    "bar": ("layer", "spacing", "margin_top", "margin_right", "margin_bottom", "margin_left", "exclusive",
            "clock_format", "clock_format_alt"),
    "notifications": ("layer", "control_center_width", "control_center_height", "fit_to_screen",
                      "timeout_low", "timeout_critical", "grouping", "relative_timestamps",
                      "image_visibility", "hide_on_clear", "hide_on_action", "keyboard_shortcuts"),
    "idle": ("suspend_after", "lock_background", "show_failed_attempts", "ignore_empty_password"),
    "clipboard": ("persist",),
}
LEGACY_SECTIONS = ("layout", "input.touchpad", "input.pointer", "outputs", "appearance", "location",
                   "night_light", "background", "font", "keybindings", "autostart")


def session_marker() -> Path:
    """Per-login marker so autostart runs once even if the daemon restarts.
    SWAYSOCK contains sway's pid, so it's unique per session."""
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/swayctl-center-{os.getuid()}"
    sock = os.environ.get("SWAYSOCK", "")
    tag = hashlib.sha1(sock.encode()).hexdigest()[:12]
    return Path(runtime) / "swayctl-center" / f"session-started-{tag}"


def diff(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    changes: dict[str, set[str]] = {}
    for section, values in new.items():
        before = old.get(section, {})
        keys = {k for k, v in values.items() if before.get(k) != v}
        if keys:
            changes[section] = keys
    return changes


class Daemon:
    def __init__(self, store: Store | None = None, state: State | None = None):
        self.store = store or Store()
        self.state = state or State()
        self.resolved: appearance.Resolved | None = None
        self.errors: dict[str, list[str]] = {}  # last apply errors per section, for GetStatus
        self.modules = by_section()
        self.ipc = swayipc.Connection()
        self.applied: dict[str, dict[str, Any]] = {}
        self.loop = GLib.MainLoop()
        self.conn: Gio.DBusConnection | None = None
        self._debounce_id = 0
        self._outputs_id = 0

    # --- lifecycle -------------------------------------------------------

    def run(self) -> None:
        self.store.load()
        if not self.store.exists:
            self._adopt_current_setup(schema.SECTIONS)
        else:
            adopted = self.state.get("adopted_sections", list(LEGACY_SECTIONS))
            new = [s for s in schema.SECTIONS if s not in adopted]
            if new:
                # sections added by a newer version: adopt the user's current setup for those
                self._adopt_current_setup(new)
            keys_adopted = self.state.get("adopted_keys")
            if keys_adopted is None:  # stores from before per-key tracking
                keys_adopted = [k.path for k in schema.KEYS
                                if k.name not in KEYS_ADDED_LATER.get(k.section, ())]
            new_keys = [k.path for k in schema.KEYS
                        if k.path not in keys_adopted and k.section not in new]
            if new_keys:
                self._adopt_current_setup(sorted({schema.split_path(p)[0] for p in new_keys}),
                                          only_keys=set(new_keys))
        self.state.set("adopted_sections", list(schema.SECTIONS))
        self.state.set("adopted_keys", [k.path for k in schema.KEYS])
        self.apply_all()
        self._session_start()

        self._watch_store()
        self._watch_sway()
        GLib.timeout_add_seconds(SCHEDULE_CHECK_S, self._check_schedule)
        node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION)
        Gio.bus_own_name(
            Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.NONE,
            lambda conn, _name: self._on_bus_acquired(conn, node), None,
            lambda _conn, _name: self._quit("could not own %s (already running?)" % BUS_NAME),
        )
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._quit, "SIGTERM")
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self._quit, "SIGINT")
        self.loop.run()

    def _quit(self, reason: str = "") -> bool:
        if reason:
            log.info("stopping: %s", reason)
        self.loop.quit()
        return GLib.SOURCE_REMOVE

    def _unique_modules(self):
        return {id(m): m for m in self.modules.values()}.values()

    def _ctx(self, old: dict[str, Any] | None = None, live: Any = None,
             values: dict[str, dict[str, Any]] | None = None) -> Context:
        return Context(data_dir=self.store.dir, old=old, live=live, values=values or {},
                       theme=self.resolved.theme if self.resolved else None)

    def _resolve_theme(self, values: dict[str, dict[str, Any]]) -> bool:
        """Work out the active theme; True if it differs from before."""
        now = datetime.now().astimezone()
        override = self.state.get("theme_override")
        if override and datetime.fromisoformat(override["until"]) <= now:
            self.state.set("theme_override", None)
            override = None
        before = self.resolved.theme if self.resolved else None
        self.resolved = appearance.resolve(values, themes.load_all(self.store.dir), now, override)
        if self.resolved.missing:
            log.warning("theme %r not found, using %s", self.resolved.missing, self.resolved.theme.name)
        return before != self.resolved.theme

    def _adopt_current_setup(self, sections, only_keys: set[str] | None = None) -> None:
        """Store what sway runs with now for these sections, so nothing visibly
        changes (first start, or sections new in this version)."""
        imported: dict[str, dict[str, Any]] = {}
        config = swayconfig.load(self.ipc)
        ctx = self._ctx(values=self.store.effective())
        for module in self._unique_modules():
            if not set(module.sections) & set(sections):
                continue
            try:
                found = module.import_current(self.ipc, config, ctx)
            except (swayipc.IPCError, OSError, ValueError) as e:
                log.warning("could not import current %s settings: %s", module.sections, e)
                continue
            for s, v in found.items():
                if s not in sections:
                    continue
                if only_keys is not None:
                    v = {k: x for k, x in v.items() if f"{s}.{k}" in only_keys and not self.store.is_set(s, k)}
                if v:
                    imported[s] = v
        log.info("adopting current setup for %s: %s", ", ".join(sections),
                 ", ".join(f"{s} ({len(v)} keys)" for s, v in imported.items()))
        log.debug("imported values: %s", imported)
        self.store.set_many(imported)
        self.store.load()

    # --- applying --------------------------------------------------------

    def apply_section(self, section: str, values: dict[str, Any], changed: set[str] | None,
                      old: dict[str, Any] | None = None,
                      all_values: dict[str, dict[str, Any]] | None = None) -> list[str]:
        module = self.modules[section]
        errors = []
        live = None
        if hasattr(module, "snapshot"):
            try:
                live = module.snapshot(self.ipc)
            except (swayipc.IPCError, OSError) as e:
                errors.append(f"{section} snapshot: {e}")
        ctx = self._ctx(old=old, live=live, values=all_values or self.store.effective())
        cmds = module.commands(section, values, changed, ctx)
        errors += self._run(cmds, module.tolerated_errors)
        if hasattr(module, "apply_extra"):
            try:
                errors += module.apply_extra(section, values, changed, ctx)
            except Exception as e:
                errors.append(f"{section}: {e}")
        for e in errors:
            log.warning("%s", e)
        self.errors[section] = errors
        return errors

    def _run(self, cmds: list[str], tolerated: tuple[str, ...] = ()) -> list[str]:
        errors = []
        for cmd in cmds:
            try:
                results = self.ipc.command(cmd)
            except (swayipc.IPCError, OSError) as e:
                errors.append(f"{cmd}: {e}")
                continue
            for r in results or []:
                if not r.get("success") and r.get("error") not in tolerated:
                    errors.append(f"sway rejected {cmd}: {r.get('error')}")
        return errors

    def _session_start(self) -> None:
        marker = session_marker()
        if marker.exists():
            return
        values = self.store.effective()
        for section, module in self.modules.items():
            if hasattr(module, "session_start"):
                for e in self._run(module.session_start(section, values[section])):
                    log.warning("%s", e)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()

    def apply_all(self) -> None:
        values = self.store.effective()
        self._resolve_theme(values)
        for section, section_values in values.items():
            self.apply_section(section, section_values, None, all_values=values)
        self.applied = values

    def _apply_changes(self) -> dict[str, set[str]]:
        """Apply whatever differs from what was last applied, plus the sections
        that depend on it (or on the active theme, if that changed)."""
        values = self.store.effective()
        changes = diff(self.applied, values)
        triggers = set(changes)
        if self._resolve_theme(values):
            triggers.add("theme")
            log.info("active theme is now %s (%s)", self.resolved.theme.name, self.resolved.source)
        for section in values:  # schema order: e.g. appearance before background
            if section in changes:
                self.apply_section(section, values[section], changes[section],
                                   old=self.applied.get(section), all_values=values)
            elif triggers & set(getattr(self.modules[section], "depends_on", ())):
                self.apply_section(section, values[section], None, all_values=values)
        self.applied = values
        for section, keys in changes.items():
            self._emit_changed(section, keys)
        if "theme" in triggers and "appearance" not in changes:
            self._emit_changed("appearance", {"_status"})
        return changes

    def _check_schedule(self) -> bool:
        # also expires a toggle override once the schedule catches up
        self._apply_changes()
        return GLib.SOURCE_CONTINUE

    def _stop_components(self) -> None:
        """Programs we run need the Wayland session; stop them before it goes
        so systemd doesn't keep restarting them."""
        values = self.store.effective()
        ctx = self._ctx(values=values)
        for section, module in self.modules.items():
            if hasattr(module, "stop_all"):
                module.stop_all(values[section], ctx)

    # --- actions ---------------------------------------------------------

    def action(self, name: str) -> None:
        if name not in ACTIONS:
            raise KeyError(f"unknown action {name}; available: {', '.join(ACTIONS)}")
        values = self.store.effective()
        if name == "lock":
            import shlex
            from .modules.components import lock_command
            errors = self._run([f"exec {shlex.join(lock_command(self._ctx(values=values)))}"])
            if errors:
                raise RuntimeError(errors[0])
            return
        if name.startswith("notifications."):
            flag = "-t" if name == "notifications.panel" else "-d"
            self._run([f"exec swaync-client {flag} -sw"])
            return
        if name == "theme.toggle":
            r = self.resolved
            opposite = "light" if r.variant == "dark" else "dark"
            if values["appearance"]["mode"] != "auto":
                self.store.set("appearance", "mode", opposite)
            elif r.source == "override":
                self.state.set("theme_override", None)  # back to the schedule
            else:
                now = datetime.now().astimezone()
                until = r.next_change or now + timedelta(hours=12)
                self.state.set("theme_override", {"variant": opposite, "until": until.isoformat()})
        else:
            night = values["night_light"]
            last_mode = self.state.get("night_light_last_mode", "always")
            if name == "night_light.toggle":
                if night["mode"] == "off":
                    self.store.set("night_light", "mode", last_mode)
                else:
                    self.state.set("night_light_last_mode", night["mode"])
                    self.store.set("night_light", "mode", "off")
            else:
                step = -NIGHT_LIGHT_STEP if name == "night_light.warmer" else NIGHT_LIGHT_STEP
                key = schema.lookup("night_light", "temperature")
                temp = min(max(night["temperature"] + step, key.min), key.max)
                self.store.set("night_light", "temperature", temp)
                if night["mode"] == "off":
                    self.store.set("night_light", "mode", last_mode)
        self._apply_changes()

    def status(self) -> dict[str, Any]:
        from . import schedule
        from .modules.night_light import NightLightModule
        values = self.store.effective()
        r = self.resolved
        loc = schedule.resolve_location(values["location"])
        return {
            "appearance": {
                "theme": r.theme.to_json(), "variant": r.variant, "source": r.source,
                "next_change": r.next_change.isoformat() if r.next_change else None,
                "missing_theme": r.missing,
                "themes": [t.to_json() for t in themes.load_all(self.store.dir).values()],
            },
            "location": {"latitude": loc.latitude, "longitude": loc.longitude, "source": loc.source,
                         "timezone": schedule.local_timezone_name()},
            "night_light": NightLightModule().status(),
            "scrolling": self.modules["scrolling"].status(),
            "keyremap": self.modules["keyremap"].status(),
            "components": {s: m.status(values[s], self._ctx(values=values))
                           for s, m in self.modules.items() if hasattr(m, "stop_all")},
            "errors": {s: e for s, e in self.errors.items() if e},
        }

    # --- watchers --------------------------------------------------------

    def _watch_store(self) -> None:
        self.store.dir.mkdir(parents=True, exist_ok=True)
        self._monitor = Gio.File.new_for_path(str(self.store.dir)).monitor_directory(
            Gio.FileMonitorFlags.WATCH_MOVES, None)
        self._monitor.connect("changed", self._on_store_dir_changed)

    def _on_store_dir_changed(self, _monitor, file, other, _event) -> None:
        names = {f.get_basename() for f in (file, other) if f is not None}
        if not names & {p.name for p in self.store.files.values()}:
            return
        if self._debounce_id:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = GLib.timeout_add(DEBOUNCE_MS, self._reload_store)

    def _reload_store(self) -> bool:
        self._debounce_id = 0
        self.store.load()
        # Our own writes diff to nothing here: self.applied already has them.
        changes = self._apply_changes()
        if changes:
            log.info("store changed on disk: %s", {s: sorted(k) for s, k in changes.items()})
        return GLib.SOURCE_REMOVE

    def _watch_sway(self) -> None:
        self._events = swayipc.EventSubscription(["workspace", "output", "shutdown"])
        GLib.io_add_watch(self._events.fileno(), GLib.PRIORITY_DEFAULT,
                          GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self._on_sway_event)

    def _on_sway_event(self, _fd, condition) -> bool:
        # sway going away (exit, crash) often shows up as a closed socket
        # rather than a shutdown event; either way the session is over.
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            self._stop_components()
            self._quit("sway IPC socket closed")
            return GLib.SOURCE_REMOVE
        try:
            name, payload = self._events.read()
        except (swayipc.IPCError, OSError) as e:
            self._stop_components()
            self._quit(f"sway IPC error: {e}")
            return GLib.SOURCE_REMOVE
        if name == "shutdown":
            self._stop_components()
            self._quit("sway is shutting down")
            return GLib.SOURCE_REMOVE
        if name == "workspace" and (payload or {}).get("change") == "reload":
            # `swaymsg reload` re-applied the user's config on top of ours.
            log.info("sway reloaded its config, re-applying settings")
            self.apply_all()
        elif name == "output":
            # monitors come and go in bursts; wait for things to settle
            if self._outputs_id:
                GLib.source_remove(self._outputs_id)
            self._outputs_id = GLib.timeout_add(OUTPUT_SETTLE_MS, self._sync_outputs)
        return GLib.SOURCE_CONTINUE

    def _sync_outputs(self) -> bool:
        """Remember newly connected monitors (as they are now), so they show up
        in the UI and keep their setup; known ones are re-checked."""
        self._outputs_id = 0
        module = self.modules["outputs"]
        try:
            live = module.snapshot(self.ipc)
        except (swayipc.IPCError, OSError) as e:
            log.warning("could not read outputs: %s", e)
            return GLib.SOURCE_REMOVE
        stored = self.store.effective()["outputs"]["config"]
        new = module.new_outputs(stored, live)
        if new:
            log.info("new monitor(s) connected: %s", ", ".join(new))
            self.store.set("outputs", "config", {**stored, **new})
            self._apply_changes()
        else:
            self.apply_section("outputs", self.store.effective()["outputs"], None)
        return GLib.SOURCE_REMOVE

    # --- D-Bus -----------------------------------------------------------

    def _on_bus_acquired(self, conn: Gio.DBusConnection, node: Gio.DBusNodeInfo) -> None:
        self.conn = conn
        conn.register_object(OBJECT_PATH, node.interfaces[0], self._on_method_call, None, None)
        log.info("listening on D-Bus as %s", BUS_NAME)

    def _emit_changed(self, section: str, keys: set[str]) -> None:
        if self.conn is not None:
            self.conn.emit_signal(None, OBJECT_PATH, INTERFACE, "Changed",
                                  GLib.Variant("(sas)", (section, sorted(keys))))

    def _on_method_call(self, _conn, _sender, _path, _iface, method, params, invocation) -> None:
        try:
            result = self._dispatch(method, params.unpack())
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            # str(KeyError) wraps the message in quotes; use the raw message
            msg = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
            invocation.return_dbus_error(ERROR_INVALID, msg)
            return
        except Exception as e:  # never let a client kill the daemon
            log.exception("%s failed", method)
            invocation.return_dbus_error(ERROR_FAILED, str(e))
            return
        invocation.return_value(GLib.Variant("(s)", (result,)) if result is not None else None)

    def _dispatch(self, method: str, args: tuple) -> str | None:
        if method == "GetSchema":
            return json.dumps([k.to_json() for k in schema.KEYS])
        if method == "GetAll":
            return json.dumps(self.store.effective())
        if method == "Get":
            section, name = schema.split_path(args[0])
            schema.lookup(section, name)
            return json.dumps(self.store.effective()[section][name])
        if method == "Set":
            section, name = schema.split_path(args[0])
            schema.lookup(section, name)
            value = json.loads(args[1])
            module = self.modules[section]
            if hasattr(module, "before_set"):
                value = module.before_set(section, name, value, self._ctx())
            related = {}
            if hasattr(module, "related_values"):
                try:
                    related = module.related_values(section, name, value, self._ctx())
                except (OSError, ValueError) as e:
                    raise ValueError(f"{section}.{name}: can't read {value}: {e}") from None
            self.store.set(section, name, value)
            if related:
                self.store.set_many({section: related})
            self._apply_changes()
            return None
        if method == "Reset":
            section, name = schema.split_path(args[0])
            self.store.reset(section, name)
            self._apply_changes()
            return None
        if method == "ApplyAll":
            self.apply_all()
            return None
        if method == "GetStatus":
            return json.dumps(self.status())
        if method == "Action":
            self.action(args[0])
            return None
        if method == "Export":
            return json.dumps(backup.export(self.store, Path(args[0]).expanduser()))
        if method == "Import":
            summary = backup.restore(self.store, Path(args[0]).expanduser())
            self.store.load()
            self._apply_changes()
            log.info("imported backup %s: %s", args[0], summary)
            return json.dumps(summary)
        raise KeyError(f"unknown method {method}")


def main() -> None:
    Daemon().run()

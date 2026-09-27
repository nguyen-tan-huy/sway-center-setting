"""Command-line entry point: `swayctl-center daemon` runs the service, the other
subcommands are thin D-Bus clients of it."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from .client import CallError, Client, DaemonUnavailable


def _client() -> Client:
    return Client()


def _run(fn, *args):
    try:
        return fn(*args)
    except (DaemonUnavailable, CallError) as e:
        sys.exit(f"swayctl-center: {e}")


def _parse_value(text: str):
    """Accept JSON (true, 5, 0.3, "x") and fall back to a bare string (flat)."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def run_binding(binding_id: str) -> int:
    """Run a shortcut's command with its shell quoting intact (see
    keybindings.needs_runner). Reads the settings file directly, so it works
    even while the daemon is down."""
    import subprocess
    from .modules.keybindings import binding_id as make_id, shell_command
    from .store import Store
    store = Store()
    store.load()
    for b in store.effective()["keybindings"]["bindings"]:
        if make_id(b) == binding_id:
            subprocess.Popen(["sh", "-c", shell_command(b["command"])], start_new_session=True)
            return 0
    print(f"swayctl-center: no shortcut with id {binding_id}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="swayctl-center")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("ui", help="open the settings window (default)")
    p.add_argument("--page", help="section to show first, e.g. keybindings")
    p = sub.add_parser("daemon", help="run the settings daemon")
    p.add_argument("-v", "--verbose", action="store_true")
    p = sub.add_parser("get", help="print one setting, a section, or everything")
    p.add_argument("path", nargs="?")
    p = sub.add_parser("set", help="change a setting, e.g. set layout.gaps_inner 8")
    p.add_argument("path")
    p.add_argument("value")
    p = sub.add_parser("reset", help="restore a setting to its default")
    p.add_argument("path")
    sub.add_parser("apply", help="re-apply every setting to sway")
    sub.add_parser("schema", help="print the settings schema as JSON")
    sub.add_parser("status", help="print runtime status (active theme, night light...)")
    p = sub.add_parser("binding", help=argparse.SUPPRESS)  # run by keyboard shortcuts
    p.add_argument("id")
    p = sub.add_parser("export", help="save settings, wallpaper and themes to a .zip")
    p.add_argument("file")
    p = sub.add_parser("import", help="restore settings from a backup .zip")
    p.add_argument("file")
    sub.add_parser("doctor", help="check that everything swayctl-center needs is in place")
    p = sub.add_parser("action", help="theme.toggle, night_light.toggle|warmer|cooler, lock, "
                                      "notifications.panel|dnd, clipboard.history|delete|clear, launcher.open")
    p.add_argument("name")
    args = parser.parse_args(argv)

    c = _client()
    if args.cmd in (None, "ui"):
        from . import ui
        sys.exit(ui.main(getattr(args, "page", None)))
    elif args.cmd == "daemon":
        logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                            format="%(levelname)s %(name)s: %(message)s")
        from . import daemon
        daemon.main()
    elif args.cmd == "get":
        values = _run(c.get_all)
        if args.path:
            values = values[args.path] if args.path in values else _run(c.get, args.path)
        print(json.dumps(values, indent=2))
    elif args.cmd == "set":
        _run(c.set, args.path, _parse_value(args.value))
    elif args.cmd == "reset":
        _run(c.reset, args.path)
    elif args.cmd == "apply":
        _run(c.apply_all)
    elif args.cmd == "schema":
        print(json.dumps(_run(c.get_schema), indent=2))
    elif args.cmd == "status":
        print(json.dumps(_run(c.status), indent=2))
    elif args.cmd == "action" and args.name.startswith("clipboard."):
        from . import clipboard
        what = args.name.split(".", 1)[1]
        if what not in clipboard.ACTIONS:
            sys.exit(f"swayctl-center: unknown action {args.name}")
        clipboard.run(what)
    elif args.cmd == "action" and args.name == "launcher.open":
        from . import clipboard
        clipboard.run("launcher", wait=False)
    elif args.cmd == "action":
        _run(c.action, args.name)
    elif args.cmd == "export":
        print(json.dumps(_run(c.export, os.path.abspath(args.file)), indent=2))
    elif args.cmd == "import":
        print(json.dumps(_run(c.import_, os.path.abspath(args.file)), indent=2))
    elif args.cmd == "binding":
        sys.exit(run_binding(args.id))
    elif args.cmd == "doctor":
        from . import doctor
        ok = True
        for check in doctor.run_checks():
            mark = "ok " if check.ok else ("-- " if check.optional else "!! ")
            ok = ok and (check.ok or check.optional)
            print(f"{mark}{check.label}" + (f": {check.detail}" if check.detail else ""))
            if not check.ok and check.fix_hint:
                print(f"     fix: {check.fix_hint}")
        sys.exit(0 if ok else 1)

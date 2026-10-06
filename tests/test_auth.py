import tempfile
import unittest
from pathlib import Path

from swayctl_center import auth, schema

SUDO = "#%PAM-1.0\nauth\t\tinclude\t\tsystem-auth\naccount\t\tinclude\t\tsystem-auth\nsession\t\tinclude\t\tsystem-auth\n"
LY = "#%PAM-1.0\n\nauth       include      login\n-auth      optional     pam_gnome_keyring.so\naccount    include      login\n"
POLKIT = "#%PAM-1.0\nauth       include      system-auth\naccount    include      system-auth\n"


def dirs():
    etc, vendor = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
    (etc / "sudo").write_text(SUDO)
    (etc / "ly").write_text(LY)
    (vendor / "polkit-1").write_text(POLKIT)
    return etc, vendor


def values(**on):
    return schema.defaults()["auth"] | on


def run(script: str, etc: Path) -> None:
    import subprocess
    subprocess.run(["sh", "-c", script], check=True)


class BlockTest(unittest.TestCase):
    def test_block_goes_before_first_auth(self):
        new = auth.with_block(LY, ["fingerprint"])
        lines = new.splitlines()
        i = lines.index(auth.BEGIN)
        self.assertEqual(lines[i + 1].split()[-1], "pam_fprintd.so")
        self.assertEqual(lines[i + 3], "auth       include      login")  # password still right after
        self.assertEqual(auth.block_methods(new), ["fingerprint"])

    def test_idempotent_and_removable(self):
        once = auth.with_block(SUDO, ["fingerprint"])
        self.assertEqual(auth.with_block(once, ["fingerprint"]), once)
        self.assertEqual(auth.with_block(once, []), SUDO)
        self.assertEqual(once.count(auth.BEGIN), 1)

    def test_no_auth_line_is_refused(self):
        with self.assertRaises(ValueError):
            auth.with_block("#%PAM-1.0\naccount include login\n", ["fingerprint"])


class PlanTest(unittest.TestCase):
    def test_nothing_enabled_only_lock_services(self):
        etc, vendor = dirs()
        names = {c.path.name for c in auth.plan(values(), etc, vendor)}
        self.assertEqual(names, {"swayctl-lock-password", "swayctl-lock-fingerprint"})

    def test_apply_then_restore_round_trip(self):
        etc, vendor = dirs()
        v = values(fingerprint_sudo=True, fingerprint_polkit=True, fingerprint_login=True)
        run(auth.apply_script(auth.plan(v, etc, vendor)), etc)
        self.assertEqual(auth.block_methods((etc / "sudo").read_text()), ["fingerprint"])
        self.assertEqual(auth.block_methods((etc / "polkit-1").read_text()), ["fingerprint"])  # copied from vendor
        self.assertEqual(auth.block_methods((etc / "ly").read_text()), ["fingerprint"])
        self.assertEqual((etc / "sudo.swayctl-backup").read_text(), SUDO)
        self.assertFalse((etc / "polkit-1.swayctl-backup").exists())
        self.assertIn("pam_fprintd.so", (etc / "swayctl-lock-fingerprint").read_text())
        self.assertEqual(auth.plan(v, etc, vendor), [])  # applied: nothing pending
        # turning one off rewrites just that file, backup kept from the first time
        run(auth.apply_script(auth.plan(values(fingerprint_polkit=True), etc, vendor)), etc)
        self.assertEqual((etc / "sudo").read_text(), SUDO)
        run(auth.restore_script(etc), etc)
        self.assertEqual((etc / "sudo").read_text(), SUDO)
        self.assertEqual((etc / "ly").read_text(), LY)
        self.assertEqual(auth.block_methods((etc / "polkit-1").read_text()), [])
        self.assertFalse((etc / "swayctl-lock-fingerprint").exists())

    def test_password_line_can_never_go(self):
        with self.assertRaises(ValueError):
            auth._check_kept(SUDO, SUDO.replace("auth\t\tinclude\t\tsystem-auth\n", ""))

    def test_status(self):
        etc, vendor = dirs()
        st = auth.status(values(fingerprint_sudo=True), etc, vendor, module_dir=etc, readers=[])
        self.assertTrue(st["pending"])
        self.assertEqual(st["applied"]["sudo"], [])
        self.assertFalse(st["fingerprint"]["installed"])
        self.assertNotIn("face", st)


class LockCommandTest(unittest.TestCase):
    def test_swayctl_lock_by_default_swaylock_still_possible(self):
        from swayctl_center import themes
        from swayctl_center.modules import Context
        from swayctl_center.modules.components import lock_command
        v = schema.defaults()
        c = Context(Path("/app"), values=v, theme=themes.BUILTIN["dark"])
        v["auth"].update(lock_screen="swaylock")
        self.assertEqual(lock_command(c)[0], "swaylock")
        v["auth"].update(lock_screen="swayctl-lock")
        self.assertNotIn("--fingerprint", lock_command(c))
        v["auth"].update(fingerprint_lock=True)
        argv = lock_command(c)
        self.assertEqual(argv[:2], ["swayctl-lock", "--daemonize"])
        self.assertIn("--fingerprint", argv)
        self.assertIn("/app/generated/bar/style.css", argv)


if __name__ == "__main__":
    unittest.main()

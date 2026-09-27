import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from swayctl_center import backup, doctor, schema
from swayctl_center.store import Store


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src = Store(root / "a")
        self.src.load()
        (root / "a/wallpapers").mkdir(parents=True)
        (root / "a/wallpapers/abc-sea.jpg").write_bytes(b"jpeg")
        (root / "a/themes").mkdir()
        (root / "a/themes/mine.json").write_text('{"bg":"#000000","fg":"#ffffff","accent":"#ff0000","muted":"#777777"}')
        self.src.set("layout", "gaps_inner", 8)
        self.src.set("background", "image", "wallpapers/abc-sea.jpg")
        self.src.set("appearance", "dark_theme", "mine")
        self.src.set("outputs", "config", {"Dell X 1": {"scale": 1.5}})   # machine-specific
        self.zip = root / "backup.zip"

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip(self):
        summary = backup.export(self.src, self.zip)
        self.assertIn("layout", summary["sections"])
        self.assertNotIn("outputs", summary["sections"])
        self.assertEqual(sorted(summary["files"]), ["themes/mine.json", "wallpapers/abc-sea.jpg"])

        dst = Store(Path(self.tmp.name) / "b")
        dst.load()
        dst.set("outputs", "config", {"Laptop panel": {"scale": 2.0}})
        dst.set("layout", "border", 9)   # not in the backup: replaced away
        result = backup.restore(dst, self.zip)
        dst.load()
        eff = dst.effective()
        self.assertEqual(eff["layout"]["gaps_inner"], 8)
        self.assertEqual(eff["layout"]["border"], 2)
        self.assertEqual(eff["background"]["image"], "wallpapers/abc-sea.jpg")
        self.assertTrue((dst.dir / "wallpapers/abc-sea.jpg").is_file())
        self.assertTrue((dst.dir / "themes/mine.json").is_file())
        self.assertIn("Laptop panel", eff["outputs"]["config"])   # this machine's displays kept
        self.assertEqual(result["skipped"], [])

    def test_rejects_bad_files(self):
        self.zip.write_text("not a zip")
        with self.assertRaises(backup.BackupError):
            backup.read(self.zip)
        with zipfile.ZipFile(self.zip, "w") as z:
            z.writestr("manifest.json", json.dumps({"format": "other"}))
            z.writestr("settings.json", "{}")
        with self.assertRaises(backup.BackupError):
            backup.read(self.zip)
        with zipfile.ZipFile(self.zip, "w") as z:
            z.writestr("manifest.json", json.dumps({"format": backup.FORMAT, "version": 99}))
            z.writestr("settings.json", "{}")
        with self.assertRaisesRegex(backup.BackupError, "newer"):
            backup.read(self.zip)

    def test_invalid_values_and_path_tricks_are_skipped(self):
        with zipfile.ZipFile(self.zip, "w") as z:
            z.writestr("manifest.json", json.dumps({"format": backup.FORMAT, "version": 1}))
            z.writestr("settings.json", json.dumps({
                "layout": {"gaps_inner": -4, "border": 3},
                "outputs": {"config": {}},
                "nope": {"x": 1},
            }))
            z.writestr("../evil.sh", "rm -rf ~")
            z.writestr("wallpapers/../../evil.sh", "x")
            z.writestr("themes/ok.json", "{}")
        dst = Store(Path(self.tmp.name) / "c")
        dst.load()
        result = backup.restore(dst, self.zip)
        self.assertEqual(result["files"], ["themes/ok.json"])
        self.assertIn("layout.gaps_inner", result["skipped"])
        self.assertIn("outputs.config", result["skipped"])
        self.assertFalse((Path(self.tmp.name) / "evil.sh").exists())
        dst.load()
        self.assertEqual(dst.effective()["layout"]["border"], 3)


class DoctorTest(unittest.TestCase):
    def test_missing_include_offers_fix(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config"
            cfg.write_text("set $mod Mod4\n# include /etc/sway/config.d/* is commented\n")
            with mock.patch.object(doctor.swayconfig, "main_config_path", return_value=cfg):
                self.assertFalse(doctor._user_config_includes_snippet())
                self.assertIsNone(doctor.apply_fix("add_include"))
                self.assertTrue(doctor._user_config_includes_snippet())
                self.assertIn("include /etc/sway/config.d/*", cfg.read_text())

    def test_checks_shape(self):
        checks = doctor.run_checks()
        ids = {c.id for c in checks}
        self.assertIn("program:waybar", ids)
        self.assertIn("service:NetworkManager.service", ids)


if __name__ == "__main__":
    unittest.main()

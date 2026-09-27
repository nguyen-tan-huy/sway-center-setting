import json
import tempfile
import unittest
from pathlib import Path

from swayctl_center import schema
from swayctl_center.store import Store


class SchemaTest(unittest.TestCase):
    def test_validate(self):
        key = schema.lookup("layout", "gaps_inner")
        self.assertEqual(key.validate(8), 8)
        for bad in (True, "8", -1, 500, 1.5):
            with self.assertRaises(ValueError):
                key.validate(bad)
        self.assertEqual(schema.lookup("input.touchpad", "pointer_accel").validate(1), 1.0)
        with self.assertRaises(ValueError):
            schema.lookup("layout", "smart_gaps").validate("maybe")

    def test_split_path(self):
        self.assertEqual(schema.split_path("input.touchpad.tap"), ("input.touchpad", "tap"))
        with self.assertRaises(KeyError):
            schema.split_path("tap")


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = Store(self.dir)
        self.store.load()

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_when_empty(self):
        self.assertFalse(self.store.exists)
        self.assertEqual(self.store.effective()["layout"]["border"], 2)

    def test_set_persists_and_reset(self):
        self.store.set("layout", "border", 5)
        other = Store(self.dir)
        other.load()
        self.assertEqual(other.effective()["layout"]["border"], 5)
        self.assertTrue(other.is_set("layout", "border"))
        other.reset("layout", "border")
        self.assertEqual(other.effective()["layout"]["border"], 2)
        self.assertEqual(json.loads((self.dir / "settings.json").read_text())["values"], {})

    def test_set_rejects_invalid(self):
        with self.assertRaises(ValueError):
            self.store.set("layout", "border", "wide")
        with self.assertRaises(KeyError):
            self.store.set("layout", "nope", 1)
        self.assertFalse(self.store.exists)

    def test_invalid_stored_value_falls_back_to_default(self):
        (self.dir / "settings.json").write_text(json.dumps(
            {"version": 1, "values": {"layout": {"border": "huge", "gaps_inner": 4}, "bogus": {"x": 1}}}))
        self.store.load()
        eff = self.store.effective()
        self.assertEqual(eff["layout"]["border"], 2)
        self.assertEqual(eff["layout"]["gaps_inner"], 4)

    def test_corrupt_file_keeps_last_good(self):
        self.store.set("layout", "border", 7)
        (self.dir / "settings.json").write_text("{not json")
        self.store.load()
        self.assertEqual(self.store.effective()["layout"]["border"], 7)

    def test_set_many_skips_invalid(self):
        self.store.set_many({"layout": {"border": 3, "gaps_inner": -5}, "input.touchpad": {"tap": True}})
        eff = self.store.effective()
        self.assertEqual(eff["layout"]["border"], 3)
        self.assertEqual(eff["layout"]["gaps_inner"], 0)
        self.assertTrue(eff["input.touchpad"]["tap"])


if __name__ == "__main__":
    unittest.main()

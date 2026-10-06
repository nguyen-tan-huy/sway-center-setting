import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from swayctl_center import schedule, schema, themes
from swayctl_center.modules import Context
from swayctl_center.modules.appearance import AppearanceModule, client_colors, resolve
from swayctl_center.modules.night_light import wlsunset_args

HCMC = schedule.Location(10.75, 106.667, "timezone")
ICT = timezone(timedelta(hours=7))


class ScheduleTest(unittest.TestCase):
    def test_zone_table_parsing(self):
        with tempfile.TemporaryDirectory() as d:
            tab = Path(d) / "zone1970.tab"
            tab.write_text("# comment\nVN\t+1045+10640\tAsia/Ho_Chi_Minh\nNO\t+5955+01045\tEurope/Oslo\n"
                           "US\t+404251-0740023\tAmerica/New_York\n")
            self.assertEqual(schedule.timezone_location("Asia/Ho_Chi_Minh", (tab,)), (10.75, 106 + 40 / 60))
            lat, lon = schedule.timezone_location("America/New_York", (tab,))
            self.assertAlmostEqual(lat, 40.714, places=3)
            self.assertAlmostEqual(lon, -74.0064, places=3)
            self.assertIsNone(schedule.timezone_location("Mars/Base", (tab,)))

    def test_sun_times_hcmc(self):
        rise, set_ = schedule.sun_times(date(2026, 9, 24), HCMC.latitude, HCMC.longitude)
        rise, set_ = rise.astimezone(ICT), set_.astimezone(ICT)
        # published: 05:42 / 17:49
        self.assertLess(abs((rise.hour * 60 + rise.minute) - (5 * 60 + 42)), 3)
        self.assertLess(abs((set_.hour * 60 + set_.minute) - (17 * 60 + 49)), 3)

    def test_polar(self):
        self.assertIsNone(schedule.sun_times(date(2026, 6, 21), 69.65, 18.96))
        v, nxt = schedule.variant_at(datetime(2026, 6, 21, 12, tzinfo=timezone.utc), "sun",
                                     schedule.Location(69.65, 18.96, "manual"))
        self.assertEqual(v, "light")

    def test_variant_sun(self):
        v, nxt = schedule.variant_at(datetime(2026, 9, 24, 12, tzinfo=ICT), "sun", HCMC)
        self.assertEqual((v, nxt.hour), ("light", 17))
        v, nxt = schedule.variant_at(datetime(2026, 9, 24, 21, tzinfo=ICT), "sun", HCMC)
        self.assertEqual((v, nxt.day, nxt.hour), ("dark", 25, 5))
        v, nxt = schedule.variant_at(datetime(2026, 9, 24, 3, tzinfo=ICT), "sun", HCMC)
        self.assertEqual((v, nxt.day, nxt.hour), ("dark", 24, 5))

    def test_variant_custom_and_wrap(self):
        at = lambda h: datetime(2026, 9, 24, h, tzinfo=ICT)
        self.assertEqual(schedule.variant_at(at(8), "custom", HCMC, "07:00", "19:00")[0], "light")
        self.assertEqual(schedule.variant_at(at(20), "custom", HCMC, "07:00", "19:00")[0], "dark")
        # light at night (e.g. for a night-shift worker)
        self.assertEqual(schedule.variant_at(at(23), "custom", HCMC, "20:00", "06:00")[0], "light")
        self.assertEqual(schedule.variant_at(at(12), "custom", HCMC, "20:00", "06:00")[0], "dark")


def values(**appearance):
    v = schema.defaults()
    v["appearance"].update(appearance)
    v["location"].update(source="manual", latitude=HCMC.latitude, longitude=HCMC.longitude)
    return v


class ResolveTest(unittest.TestCase):
    noon = datetime(2026, 9, 24, 12, tzinfo=ICT)

    def test_fixed(self):
        r = resolve(values(mode="dark", dark_theme="dark"), themes.BUILTIN, self.noon)
        self.assertEqual((r.theme.name, r.variant, r.source, r.next_change), ("dark", "dark", "fixed", None))

    def test_schedule_and_override(self):
        r = resolve(values(), themes.BUILTIN, self.noon)
        self.assertEqual((r.theme.name, r.source), ("light", "schedule"))
        override = {"variant": "dark", "until": r.next_change.isoformat()}
        r2 = resolve(values(), themes.BUILTIN, self.noon, override)
        self.assertEqual((r2.theme.name, r2.source), ("dark", "override"))
        # expired override is ignored
        r3 = resolve(values(), themes.BUILTIN, r.next_change + timedelta(minutes=1), override)
        self.assertEqual(r3.source, "schedule")

    def test_missing_theme_falls_back(self):
        r = resolve(values(mode="light", light_theme="nope"), themes.BUILTIN, self.noon)
        self.assertEqual((r.theme.name, r.missing), ("light", "nope"))

    def test_user_theme(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "themes").mkdir()
            (Path(d) / "themes/mine.json").write_text('{"bg":"#000000","fg":"#ffffff","accent":"#ff0000","muted":"#777777"}')
            (Path(d) / "themes/broken.json").write_text('{"bg":"black"}')
            available = themes.load_all(Path(d))
        self.assertIn("mine", available)
        self.assertNotIn("broken", available)
        self.assertTrue(available["mine"].dark)

    def test_sway_colors(self):
        t = themes.BUILTIN["dark"]
        self.assertEqual(client_colors(t)[0], "client.focused #0a84ff #1c1c1e #f5f5f7 #0a84ff #0a84ff")
        self.assertEqual(AppearanceModule().commands("appearance", {}, None, Context(Path("/x"), theme=t)),
                         client_colors(t))


class NightLightTest(unittest.TestCase):
    def test_args(self):
        v = schema.defaults()["night_light"]
        self.assertIsNone(wlsunset_args(v, HCMC))
        self.assertEqual(wlsunset_args(v | {"mode": "always", "temperature": 3500}, HCMC),
                         ["-S", "00:00", "-s", "00:00", "-t", "3500", "-T", "6501"])
        self.assertEqual(wlsunset_args(v | {"mode": "sun"}, HCMC)[:4], ["-l", "10.7500", "-L", "106.6670"])
        self.assertEqual(wlsunset_args(v | {"mode": "custom", "start": "21:00", "end": "06:30"}, HCMC)[:4],
                         ["-S", "06:30", "-s", "21:00"])

    def test_schema_limits(self):
        key = schema.lookup("night_light", "temperature")
        with self.assertRaises(ValueError):
            key.validate(6500)  # must stay below wlsunset's day temperature
        with self.assertRaises(ValueError):
            schema.lookup("night_light", "start").validate("25:00")
        self.assertEqual(schema.lookup("background", "color").validate(""), "")


if __name__ == "__main__":
    unittest.main()

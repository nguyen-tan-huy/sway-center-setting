"""Time-of-day logic: sunrise/sunset, the location they're computed for, and
which half of a light/dark schedule a moment falls in. All pure functions of
their arguments (plus zoneinfo files on disk), so they're unit tested.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ZONE_TABLES = (Path("/usr/share/zoneinfo/zone1970.tab"), Path("/usr/share/zoneinfo/zone.tab"))


# --- location --------------------------------------------------------------

def local_timezone_name() -> str | None:
    tz = os.environ.get("TZ", "").lstrip(":")
    if tz and "/" in tz:
        return tz
    try:
        target = os.readlink("/etc/localtime")
    except OSError:
        return None
    marker = "zoneinfo/"
    return target.split(marker, 1)[1] if marker in target else None


def _iso6709(coord: str) -> tuple[float, float]:
    """"+1045+10640" / "+104500+1064000" -> (10.75, 106.667)."""
    m = re.fullmatch(r"([+-]\d+)([+-]\d+)", coord)
    if not m:
        raise ValueError(coord)

    def conv(part: str, deg_digits: int) -> float:
        sign = -1 if part[0] == "-" else 1
        digits = part[1:]
        deg = int(digits[:deg_digits])
        mins = int(digits[deg_digits:deg_digits + 2])
        secs = int(digits[deg_digits + 2:] or 0)
        return sign * (deg + mins / 60 + secs / 3600)

    return conv(m.group(1), 2), conv(m.group(2), 3)


def timezone_location(zone: str | None, tables=ZONE_TABLES) -> tuple[float, float] | None:
    """Approximate coordinates of a timezone's reference city - good enough for
    sunrise/sunset (a few minutes off at worst)."""
    if not zone:
        return None
    for table in tables:
        try:
            lines = table.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            if line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) >= 3 and cols[2] == zone:
                try:
                    return _iso6709(cols[1])
                except ValueError:
                    return None
    return None


@dataclass(frozen=True)
class Location:
    latitude: float
    longitude: float
    source: str  # "timezone" | "manual" | "default"


def resolve_location(values: dict) -> Location:
    if values["source"] == "manual":
        return Location(values["latitude"], values["longitude"], "manual")
    found = timezone_location(local_timezone_name())
    if found:
        return Location(found[0], found[1], "timezone")
    return Location(values["latitude"], values["longitude"], "default")


# --- sun -------------------------------------------------------------------

def sun_times(day: date, lat: float, lon: float) -> tuple[datetime, datetime] | None:
    """UTC sunrise and sunset for a calendar day, or None during polar day/night.
    The standard "sunrise equation" (accurate to about a minute)."""
    rad, deg = math.radians, math.degrees
    n = day.toordinal() + 1721425 - 2451545 + 0.0008  # days since J2000 at local noon-ish
    j_star = n - lon / 360
    m = (357.5291 + 0.98560028 * j_star) % 360
    c = 1.9148 * math.sin(rad(m)) + 0.02 * math.sin(rad(2 * m)) + 0.0003 * math.sin(rad(3 * m))
    lam = (m + c + 180 + 102.9372) % 360
    j_transit = 2451545.0 + j_star + 0.0053 * math.sin(rad(m)) - 0.0069 * math.sin(rad(2 * lam))
    sin_decl = math.sin(rad(lam)) * math.sin(rad(23.4397))
    cos_decl = math.cos(math.asin(sin_decl))
    cos_w0 = (math.sin(rad(-0.833)) - math.sin(rad(lat)) * sin_decl) / (math.cos(rad(lat)) * cos_decl)
    if not -1 <= cos_w0 <= 1:
        return None
    w0 = deg(math.acos(cos_w0))

    def to_dt(j: float) -> datetime:
        return datetime.fromtimestamp((j - 2440587.5) * 86400, tz=timezone.utc)

    return to_dt(j_transit - w0 / 360), to_dt(j_transit + w0 / 360)


# --- light/dark schedule ---------------------------------------------------

def parse_hhmm(text: str) -> time:
    h, m = text.split(":")
    return time(int(h), int(m))


def _day_bounds(day: date, schedule: str, loc: Location, light_at: str, dark_at: str,
                tz) -> tuple[datetime, datetime] | None:
    """(start of the light period, start of the dark period) for a local day."""
    if schedule == "sun":
        times = sun_times(day, loc.latitude, loc.longitude)
        if times is None:
            return None
        return times[0].astimezone(tz), times[1].astimezone(tz)
    return (datetime.combine(day, parse_hhmm(light_at), tz),
            datetime.combine(day, parse_hhmm(dark_at), tz))


def variant_at(now: datetime, schedule: str, loc: Location, light_at: str = "07:00",
               dark_at: str = "19:00") -> tuple[str, datetime | None]:
    """("light" | "dark", when that next changes) for an aware local datetime."""
    tz = now.tzinfo
    today = now.date()
    bounds = _day_bounds(today, schedule, loc, light_at, dark_at, tz)
    if bounds is None:
        # polar day/night: pick by season (summer half = light), re-check tomorrow
        summer = (today.month in range(4, 10)) == (loc.latitude >= 0)
        tomorrow = datetime.combine(today + timedelta(days=1), time(0, 0), tz)
        return ("light" if summer else "dark"), tomorrow
    light_start, dark_start = bounds
    if light_start <= dark_start:
        if now < light_start:
            return "dark", light_start
        if now < dark_start:
            return "light", dark_start
        nxt = _day_bounds(today + timedelta(days=1), schedule, loc, light_at, dark_at, tz)
        return "dark", nxt[0] if nxt else None
    # custom schedule where "light" wraps past midnight (e.g. light_at 20:00, dark_at 06:00)
    if now < dark_start:
        return "light", dark_start
    if now < light_start:
        return "dark", light_start
    nxt = _day_bounds(today + timedelta(days=1), schedule, loc, light_at, dark_at, tz)
    return "light", nxt[1] if nxt else None

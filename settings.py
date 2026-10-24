"""Settings changed while the dash runs (on the SYSTEM screen or the web page's Settings), kept in the data folder
as settings.json so they survive restarts and software updates. Today: the temperature units.

The default comes from config.toml ([temperature] units); once changed here, settings.json wins.
Everything is stored in C; only what's shown changes.
"""
import logging

from service import read_json, write_json

log = logging.getLogger("settings")

FILE = "settings.json"
_dir = None
_units = "F"
_saved = False        # units came from settings.json (a choice made on the dash / web page)
_clock = "12h"        # "12h", "24h" or "off" (the menu bar clock)


def init(cfg, directory):
    global _dir, _units, _saved, _clock
    _dir = directory
    _units = cfg.get("temperature", {}).get("units", "F").upper()
    _clock = cfg.get("display", {}).get("clock", "12h")
    saved = read_json(directory, FILE) or {}
    if saved.get("units") in ("C", "F"):
        _units, _saved = saved["units"], True
    if saved.get("clock") in ("12h", "24h", "off"):
        _clock = saved["clock"]


def default_units(u):
    """config.toml's units, unless a choice was saved (used before init(), e.g. by the --temps tool)."""
    global _units
    if not _saved and u and u.upper() in ("C", "F"):
        _units = u.upper()


def units():
    return _units


def set_units(u):
    global _units, _saved
    u = u.upper()
    if u not in ("C", "F") or u == _units:
        return
    _units, _saved = u, True
    log.info("temperature units: %s", u)
    if _dir:
        try:
            saved = read_json(_dir, FILE) or {}
            saved["units"] = u
            write_json(_dir, FILE, saved)
        except OSError as e:
            log.error("can't save %s: %s", FILE, e)


def _save(key, value):
    if _dir:
        try:
            saved = read_json(_dir, FILE) or {}
            saved[key] = value
            write_json(_dir, FILE, saved)
        except OSError as e:
            log.error("can't save %s: %s", FILE, e)


def clock_fmt():
    return _clock


def set_clock_fmt(f):
    """'12h' / '24h' / 'off' (off: no clock in the menu bar; times elsewhere stay 12-hour)."""
    global _clock
    if f in ("12h", "24h", "off") and f != _clock:
        _clock = f
        log.info("clock: %s", f)
        _save("clock", f)


def hhmm(t=None, seconds=False):
    """A time of day as chosen: '3:42 PM' or '15:42' (t: a struct_time or epoch; None = now)."""
    import time as _t
    t = _t.localtime(t) if t is None or isinstance(t, (int, float)) else t
    if _clock == "24h":
        return _t.strftime("%H:%M:%S" if seconds else "%H:%M", t)
    return _t.strftime("%I:%M:%S %p" if seconds else "%I:%M %p", t).lstrip("0")


PROBE_NAMES = {"CAB": "Cabin Temp", "OUT": "Outside Temp", "AMB": "Outside Temp"}


def probe_label(name):
    """A temperature probe's config name as shown: 'OUT' -> 'Outside Temp', 'SEAT' -> 'Seat Temp'."""
    return PROBE_NAMES.get(name.upper(), name.title() + " Temp")


def to_units(c, u=None):
    return c * 9 / 5 + 32 if (u or _units) == "F" else c


def fmt(c, digits=0, space=False, u=None):
    """A C reading shown in the chosen units: '104°F', '61.2 °C' (space=True), '--' for None."""
    u = u or _units
    if c is None:
        return "--"
    return f"{to_units(c, u):.{digits}f}{' ' if space else ''}°{u}"


# ---------------------------------------------------------------- time zone (daylight saving comes with it)
# The Pi keeps UTC and shows local time through a named zone from the time-zone database, which knows each place's
# daylight-saving rules: pick the place, never "DST on/off". Arizona (America/Phoenix) never changes; Mountain
# (America/Denver) moves an hour in March and November by itself.
TIME_ZONES = (("America/Phoenix", "Arizona"), ("America/Los_Angeles", "Pacific"), ("America/Denver", "Mountain"),
              ("America/Chicago", "Central"), ("America/New_York", "Eastern"), ("America/Anchorage", "Alaska"),
              ("Pacific/Honolulu", "Hawaii"), ("America/Puerto_Rico", "Puerto Rico"), ("UTC", "UTC"))
# (Most of Arizona never changes; the Navajo Nation does, so it's Mountain. Hawaii and Puerto Rico never change.)


def zone_name():
    """The system time zone's name ('America/Phoenix'), or '' if it can't be told."""
    import os
    try:
        with open("/etc/timezone") as f:
            name = f.read().strip()
            if name:
                return name
    except OSError:
        pass
    try:
        target = os.path.realpath("/etc/localtime")
        return target.split("zoneinfo/", 1)[1] if "zoneinfo/" in target else ""
    except OSError:
        return ""


def zone_has_dst():
    """True if the current zone moves its clocks during the year (January and July offsets differ)."""
    import time
    y = time.localtime().tm_year
    jan = time.localtime(time.mktime((y, 1, 15, 12, 0, 0, 0, 0, -1)))
    jul = time.localtime(time.mktime((y, 7, 15, 12, 0, 0, 0, 0, -1)))
    return jan.tm_gmtoff != jul.tm_gmtoff


def zone_text():
    """'America/Phoenix (MST): no daylight saving' or 'America/Denver (MDT): daylight saving, changes by itself'."""
    import time
    name = zone_name() or "unknown zone"
    label = dict(TIME_ZONES).get(name)
    head = f"{label}, {name}" if label and label != name else name
    return f"{head} ({time.strftime('%Z')}): " + ("daylight saving, changes by itself" if zone_has_dst()
                                                 else "no daylight saving")


def zone_dst(zone):
    """True if that zone moves its clocks during the year (any zone, without touching this process's own)."""
    import datetime
    try:
        from zoneinfo import ZoneInfo
        z = ZoneInfo(zone)
    except Exception:                   # no tz database here
        return False
    y = datetime.date.today().year
    return datetime.datetime(y, 1, 15, 12, tzinfo=z).utcoffset() != datetime.datetime(y, 7, 15, 12, tzinfo=z).utcoffset()

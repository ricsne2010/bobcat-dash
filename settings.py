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


# ---------------------------------------------------------------- installed equipment (web page: Settings)
# What's fitted on this machine, switched on / off on the web page instead of in config.toml. Saved in
# settings.json as {"equipment": {key: true / false}} and applied over config.toml when the dash starts
# (apply_equipment), so a change takes effect with the restart the web page does after saving.
CHT_ADDR = (0x60, 0x65, 0x66, 0x67)          # CHT board sockets 1-4 = cylinders 1-4

EQUIPMENT = [   # (key, group, label, what it is)
    ("cht", "Engine", "Cylinder head temperatures (CHT)", "Thermocouples under the spark plugs, on the CHT board"),
    ("cht_1", "Engine", "Cylinder 1", "MCP9601 in CHT board socket 1"),
    ("cht_2", "Engine", "Cylinder 2", "socket 2"),
    ("cht_3", "Engine", "Cylinder 3", "socket 3"),
    ("cht_4", "Engine", "Cylinder 4", "socket 4"),
    ("warn_hyd_filter", "Engine", "Hydraulic filter switch", "HYDRAULIC FILTER warning light"),
    ("warn_hyd_temp", "Engine", "Hydraulic oil temperature switch", "HYDRAULIC OIL TEMP warning light"),
    ("park_brake", "Machine", "Parking brake switch", "(P) BRAKE light and its reminders"),
    ("tilt", "Machine", "Machine angle sensor", "Roll and pitch (TILT plug)"),
    ("lights", "Machine", "Light switch sensing", "Light tell-tales and LIGHTS STILL ON"),
    ("light_front", "Machine", "Front lights", "LIGHTS plug, FRONT"),
    ("light_rear", "Machine", "Rear lights", "LIGHTS plug, REAR"),
    ("light_work", "Machine", "Work light", "LIGHTS plug, WORK"),
    ("horn", "Machine", "Alarm horn", "External 12 V horn for red alarms"),
    ("temperature", "Electronics box", "Temperature sensors", "E-box sensor and cab / outside probes"),
    ("fan", "Electronics box", "Pod exhaust fan", "Button pod fan, switched by the Pi"),
]
EQUIPMENT_KEYS = {k for k, *_ in EQUIPMENT}


def equipment_state(cfg):
    """{key: on / off} as the configuration stands."""
    names = {str(c.get("name")) for c in cfg.get("cht", {}).get("cylinders", [])}
    lights = cfg.get("lights", {})
    out = {"cht": bool(names), "park_brake": bool(cfg.get("park_brake", {}).get("enabled")),
           "lights": bool(lights.get("enabled"))}
    for n in range(1, 5):
        out[f"cht_{n}"] = str(n) in names
    for name in ("front", "rear", "work"):
        out[f"light_{name}"] = isinstance(lights.get(name), dict)
    for name in ("hyd_filter", "hyd_temp"):
        out[f"warn_{name}"] = name in cfg.get("warnings", {})
    for sec in ("tilt", "horn", "temperature", "fan"):
        out[sec] = bool(cfg.get(sec, {}).get("enabled", True))
    return out


def apply_equipment(cfg, directory):
    """At start-up: settings.json's equipment choices over config.toml (cfg is changed in place).
    Returns the choices applied ({} = none saved)."""
    eq = {k: bool(v) for k, v in ((read_json(directory, FILE) or {}).get("equipment") or {}).items()
          if k in EQUIPMENT_KEYS}
    if not eq:
        return {}
    now = equipment_state(cfg)
    on = lambda k: eq.get(k, now[k])
    cc = cfg.setdefault("cht", {})
    cyls = [n for n in range(1, 5) if on(f"cht_{n}")] if on("cht") else []
    cc["cylinders"] = [{"name": str(n), "address": CHT_ADDR[n - 1]} for n in cyls]
    cc["sim"] = bool(cyls)                       # the simulator follows the choice too
    pb = cfg.setdefault("park_brake", {})
    pb["enabled"] = pb["sim"] = on("park_brake")
    lights = cfg.setdefault("lights", {})
    lights["enabled"] = on("lights")
    for name in ("front", "rear", "work"):
        if not on(f"light_{name}"):
            lights.pop(name, None)
    for name in ("hyd_filter", "hyd_temp"):
        if not on(f"warn_{name}"):
            cfg.get("warnings", {}).pop(name, None)
    for sec in ("tilt", "horn", "temperature", "fan"):
        cfg.setdefault(sec, {})["enabled"] = on(sec)
    log.info("installed equipment (web page): %s", ", ".join(f"{k} {'on' if v else 'off'}" for k, v in eq.items()))
    return eq


def save_equipment(choices):
    """The web page's choices ({key: bool}); the dash restarts to use them. Only known keys are kept."""
    choices = {k: bool(v) for k, v in choices.items() if k in EQUIPMENT_KEYS}
    _save("equipment", choices)
    return choices

"""Cylinder head temperatures (CHT): a Type K thermocouple under each spark plug, read by MCP9601 thermocouple
amplifiers on the Pi's I2C bus (the CHT board, wired to the breakout board's CHT plug, rev 3.0).

Each MCP9601 does its own cold-junction compensation and reports the hot-junction temperature in °C. The CHT
board's four sockets give the modules (Adafruit 5165) four addresses by their ADDR pin: socket 1 to GND = 0x60,
2 through 22k = 0x65, 3 through 43k = 0x66, 4 open = 0x67, so they share the bus with the ADS1115 (0x48) and the
tilt sensor (0x6A). The MCP9601 also flags an open thermocouple (a broken or unplugged lead): that cylinder shows NO SIGNAL.
Fit as many as you have: [cht] cylinders lists only the ones installed.

Limits are in °F in config.toml (the factory head-temperature switches on early Bobcat 700 engines stop the
engine over 570 °F: service manual 7A-3). M.O.S.S. never stops the engine itself; it warns and alarms only.
  warn_f    a cylinder this hot: amber CHT HIGH
  alarm_f   this hot: red, horn
  spread_f  with the engine warmed up and running, one cylinder this much cooler than the average of the others:
            amber CHT SPREAD
            (a fouled plug, a misfire or a bad plug wire)
"""
import logging
import threading
import time

import settings

log = logging.getLogger("cht")

OK, WARN, ALARM, UNKNOWN = "ok", "warn", "alarm", "unknown"
SOCKET_ADDR = settings.CHT_ADDR             # CHT board sockets 1-4 (cylinders 1-4)

# MCP9601 registers (Microchip DS20006350). Checked against the datasheet when the first board is built.
REG_HOT = 0x00          # hot-junction temperature, 16 bits signed, 0.0625 °C per bit
REG_STATUS = 0x04       # bit 4: open circuit (MCP9601), bit 5: short circuit
REG_SENSOR = 0x05       # thermocouple type (bits 6..4: 000 = K) and filter (bits 2..0)
OPEN_BIT, SHORT_BIT = 0x10, 0x20
FILTER = 2              # light digital filter: smooths ignition noise, still answers within a second


def f_to_c(f):
    return (f - 32) * 5 / 9


class MCP9601:
    def __init__(self, bus, address):
        self.bus, self.address = bus, address
        self.bus.write_byte_data(address, REG_SENSOR, (0 << 4) | FILTER)        # Type K

    def read_c(self):
        """Degrees C, or None for an open / shorted thermocouple."""
        status = self.bus.read_byte_data(self.address, REG_STATUS)
        if status & (OPEN_BIT | SHORT_BIT):
            return None
        hi, lo = self.bus.read_i2c_block_data(self.address, REG_HOT, 2)
        raw = (hi << 8) | lo
        if raw & 0x8000:
            raw -= 1 << 16
        t = raw * 0.0625
        return t if -50.0 <= t <= 1000.0 else None


class CHTSensors:
    """Reads every configured cylinder once a second in a thread. .snapshot() -> [(name, deg C or None), ...]"""

    def __init__(self, cfg, start=True):
        cc = cfg.get("cht", {})
        self.bus_n = cfg.get("adc", {}).get("i2c_bus", 1)
        self.cyls = [(str(c.get("name", i + 1)), int(c.get("address", SOCKET_ADDR[i % 4])))
                     for i, c in enumerate(cc.get("cylinders", []))]
        self.every = cc.get("read_every", 1.0)
        self._values = {name: None for name, _ in self.cyls}
        self._devs = {}
        self._bus = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._logged = set()
        if self.cyls and start:
            threading.Thread(target=self._run, name="cht", daemon=True).start()

    def _read_one(self, name, addr):
        try:
            if self._bus is None:
                from smbus2 import SMBus
                self._bus = SMBus(self.bus_n)
            if name not in self._devs:
                self._devs[name] = MCP9601(self._bus, addr)
            t = self._devs[name].read_c()
            if t is None and (name, "open") not in self._logged:
                log.warning("CHT cylinder %s: thermocouple open or shorted", name)
                self._logged.add((name, "open"))
            elif t is not None:
                self._logged.discard((name, "open"))
                self._logged.discard((name, "gone"))
            return t
        except (OSError, ImportError) as e:
            self._devs.pop(name, None)
            if (name, "gone") not in self._logged:
                log.warning("CHT cylinder %s (0x%02x) not answering: %s", name, addr, e)
                self._logged.add((name, "gone"))
            return None

    def _run(self):
        while not self._stop.is_set():
            vals = {name: self._read_one(name, addr) for name, addr in self.cyls}
            with self._lock:
                self._values = vals
            self._stop.wait(self.every)

    def snapshot(self):
        with self._lock:
            return [(name, self._values.get(name)) for name, _ in self.cyls]

    def close(self):
        self._stop.set()


class CHTStatus:
    """Per-cylinder OK / WARN / ALARM / UNKNOWN (with 10 °F hysteresis) and the spread check.
    update(snap, running, now) -> {"cyls": [(name, state, deg C or None)], "hot": (name, deg C) or None,
    "state", "text", "spread": (state, text) or None} or None when CHT is off."""

    def __init__(self, cfg, sim=False):
        cc = cfg.get("cht", {})
        self.enabled = bool(cc.get("cylinders")) or (sim and cc.get("sim", True))
        self.warn = f_to_c(cc.get("warn_f", 500))
        self.alarm = f_to_c(cc.get("alarm_f", 550))
        self.spread = cc.get("spread_f", 100) * 5 / 9
        self.spread_after = cc.get("spread_after_s", 300)       # warmed up: running this long
        self.spread_min = f_to_c(cc.get("spread_min_f", 250))   # and the hottest at least this hot
        self.hyst = 10 * 5 / 9
        self.states = {}
        self.spread_state = OK
        self.run_since = None

    def _state(self, name, t):
        prev = self.states.get(name, OK)
        if t is None:
            s = UNKNOWN
        elif t >= self.alarm or (prev == ALARM and t > self.alarm - self.hyst):
            s = ALARM
        elif t >= self.warn or (prev in (WARN, ALARM) and t > self.warn - self.hyst):
            s = WARN
        else:
            s = OK
        self.states[name] = s
        return s

    def update(self, snap, running, now=None):
        if not self.enabled or snap is None:
            return None
        now = time.monotonic() if now is None else now
        if not running:
            self.run_since = None
        elif self.run_since is None:
            self.run_since = now
        cyls = [(name, self._state(name, t), t) for name, t in snap]
        got = [(name, t) for name, _, t in cyls if t is not None]
        hot = max(got, key=lambda g: g[1]) if got else None
        rank = {OK: 0, UNKNOWN: 1, WARN: 2, ALARM: 3}
        state = max((s for _, s, _ in cyls), key=rank.get, default=OK)
        if hot is None:
            text = "CHT --"
        else:
            text = f"CHT {settings.fmt(hot[1])}"
        spread = None
        warmed = self.run_since is not None and now - self.run_since >= self.spread_after
        if warmed and hot and len(got) > 1 and hot[1] >= self.spread_min:
            # each cylinder against the average of the others (a hot one mustn't make a healthy one look cold)
            gaps = [(name, sum(t2 for n2, t2 in got if n2 != name) / (len(got) - 1) - t) for name, t in got]
            cold, gap = max(gaps, key=lambda g: g[1])
            cold = (cold,)
            if gap >= self.spread or (self.spread_state == WARN and gap > self.spread - self.hyst):
                self.spread_state = WARN
                u = settings.units()
                spread = (WARN, f"CYL {cold[0]} {gap * 9 / 5 if u == 'F' else gap:.0f}°{u} COOLER")
            else:
                self.spread_state = OK
                spread = (OK, "EVEN")
        else:
            self.spread_state = OK
            spread = (OK, "EVEN") if got else (UNKNOWN, "--")
        return {"cyls": cyls, "hot": hot, "state": state, "text": text, "spread": spread}

    def detail(self, info):
        """'CYL 3 HIGH 512°F' for the alarm history (the worst cylinder), or 'NO SIGNAL CYL 2'."""
        worst = None
        for name, s, t in info["cyls"]:
            if s in (ALARM, WARN) and (worst is None or t > worst[2]):
                worst = (name, s, t)
        if worst:
            return f"CYL {worst[0]} HIGH {settings.fmt(worst[2])}"
        gone = [name for name, s, _ in info["cyls"] if s == UNKNOWN]
        if gone:
            return "NO SIGNAL CYL " + ", ".join(gone)
        return info["text"]

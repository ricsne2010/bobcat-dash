"""Raspberry Pi health: CPU temperature and low-supply warnings.

  * PI HOT    the CPU is at or above [pi_health] temp_warn (80 C), or the Pi is already slowing itself
              down for heat. A sealed box in summer sun is the usual cause.
  * LOW 5V    the Pi has seen its 5 V supply sag (weak buck converter, thin wire, or the battery dipping
              while cranking). Shown for low_5v_hold seconds after each dip, so a short sag is still seen.

Both come from the Pi itself: /sys/class/thermal (temperature) and `vcgencmd get_throttled` (flags).
They're read in a background thread every check_every seconds, so the dash never waits on them.
On a computer that isn't a Pi neither exists, and this stays quiet.
"""
import logging
import subprocess
import threading
import time

import settings

log = logging.getLogger("pihealth")

TEMP_FILE = "/sys/class/thermal/thermal_zone0/temp"
UNDERVOLT_NOW, THROTTLED_NOW, SOFT_TEMP_NOW, UNDERVOLT_SEEN = 0x1, 0x4, 0x8, 0x10000


def read_temp():
    try:
        with open(TEMP_FILE) as f:
            return int(f.read().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def read_throttled():
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2).stdout
        return int(out.strip().split("=")[1], 16)          # "throttled=0x50005"
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


class PiHealth:
    def __init__(self, cfg, sim=False):
        c = cfg.get("pi_health", {})
        self.enabled = c.get("enabled", True)
        self.temp_warn = c.get("temp_warn", 80.0)
        self.every = c.get("check_every", 2.0)
        self.hold = c.get("low_5v_hold", 10.0)
        self.sim = sim
        self.temp = None
        self.flags = 0
        self.low_until = 0.0
        self._seen = False            # the "has happened since boot" flag was already set
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.sim_temp = 48.0           # simulator: I toggles a hot Pi, U toggles a low 5 V supply
        self.sim_low = False
        if self.enabled and not sim:
            threading.Thread(target=self._run, name="pihealth", daemon=True).start()

    def _run(self):
        while not self._stop.is_set():
            t, fl = read_temp(), read_throttled()
            with self._lock:
                self.temp = t
                if fl is not None:
                    self._flags_in(fl, time.monotonic())
            self._stop.wait(self.every)

    def _flags_in(self, fl, now):
        self.flags = fl
        new_dip = bool(fl & UNDERVOLT_SEEN) and not self._seen
        self._seen = bool(fl & UNDERVOLT_SEEN)
        if fl & UNDERVOLT_NOW or new_dip:
            self.low_until = now + self.hold
            log.warning("Pi supply under-voltage (throttled=0x%x)", fl)

    def sim_key(self, key, now):
        if key == "i":
            self.sim_temp = 84.0 if self.sim_temp < self.temp_warn else 48.0
        elif key == "u":
            self.sim_low = not self.sim_low

    def status(self, now):
        """[(source, text)] for each warning that's active now."""
        if not self.enabled:
            return []
        with self._lock:
            temp = self.sim_temp if self.sim else self.temp
            flags = 0 if self.sim else self.flags
            low = self.sim_low if self.sim else now < self.low_until
        out = []
        if (temp is not None and temp >= self.temp_warn) or flags & (THROTTLED_NOW | SOFT_TEMP_NOW):
            out.append(("pi_temp", f"PI HOT {temp:.0f}°C" if temp is not None else "PI HOT"))
        if low:
            out.append(("pi_5v", "LOW 5V"))
        return out

    def describe(self):
        with self._lock:
            temp = self.sim_temp if self.sim else self.temp
            return settings.fmt(temp, 1, space=True) if temp is not None else "no sensor"

    def close(self):
        self._stop.set()

"""Machine usage, day by day, for the performance reports (service web page and USB stick export).

Per day (the local date; "no-date" while the clock isn't set) it adds up:
  key_s      key on (dash powered and showing the gauges)
  run_s      engine running, split by throttle band:
               idle_s  below idle_below_rpm      (warming up / cooling down)
               work_s  idle_below .. full_throttle_rpm: PART THROTTLE (for warming a cold engine, pump priming or
                       setting the timing: the reports flag a lot of time here)
               full_s  full_throttle_rpm and up   (normal working: the governor holds the speed)
               over_s  above the tach's amber_above (overspeed: the governor losing control)
  hist       seconds in each rpm_bin-wide rpm band, e.g. {"2750": 4210.5} = 2750-2999 rpm
  starts     engine starts; cranks = starter attempts (cranks - starts = attempts that didn't start)
  crank_s    total time on the starter
  stops      engine stops; hot_stops = stopped while the cool-down reminder still wanted idle time
  h0, h1     engine hour meter at the first and last moment seen that day
  box_min, box_max, amb_min, amb_max, pi_min, pi_max, v_run_min, v_run_max   (temperatures in C, battery volts)
  p_<NAME>_min, p_<NAME>_max   each probe on its own (p_OUT_max, p_CAB_min); amb_* = all probes together
             each with <name>_t: when it happened (wall clock, only while the clock is set)

Kept in the data folder as usage.json, written safely every save_every_s, at key-off and at exit.
"""
import logging
import time

from service import clock_valid, read_json, write_json

log = logging.getLogger("usage")

FILE = "usage.json"
NO_DATE = "no-date"
SUMS = ("key_s", "run_s", "idle_s", "work_s", "full_s", "over_s", "crank_s", "starts", "cranks", "stops", "hot_stops")


def day_key(wall):
    return time.strftime("%Y-%m-%d", time.localtime(wall)) if clock_valid(wall) else NO_DATE


class UsageLog:
    def __init__(self, cfg, directory):
        uc = cfg.get("usage", {})
        self.enabled = uc.get("enabled", True)
        self.idle_below = uc.get("idle_below_rpm", 1400)
        self.full_at = uc.get("full_throttle_rpm", 2600)
        self.over_at = cfg.get("tach", {}).get("amber_above", 3050)
        self.bin = uc.get("rpm_bin", 250)
        self.keep_days = uc.get("keep_days", 1100)
        self.save_every = uc.get("save_every_s", 60)
        self.dir = directory
        self.days = (read_json(directory, FILE) or {}).get("days", {})
        self.last = None              # monotonic time of the last update
        self.last_save = 0.0
        self.was_running = False
        self.was_cranking = False
        self.crank_end = -99.0
        self.cool_pending = False     # the cool-down reminder wanted more idle time (last update)
        self.dirty = False
        self.save_error = None

    def bands(self):
        return {"idle_below": self.idle_below, "full_at": self.full_at, "over_at": self.over_at, "bin": self.bin}

    def _rec(self, key):
        r = self.days.get(key)
        if r is None:
            r = self.days[key] = {k: 0 for k in SUMS}
            r["hist"] = {}
        return r

    def update(self, now, key_on, running, cranking, rpm, volts=None, temps=None, pi_temp=None, hours=None,
               cool_pending=False, speed=1.0, wall=None):
        """Call every frame. temps: the temperature snapshot {"box": C, "probes": [(name, C)]} or None.
        cool_pending: the cool-down reminder is still counting (COOL DOWN / IDLE TO COOL DOWN).
        speed: the simulator's time x60 (so a simulated hour shows as an hour)."""
        if not self.enabled:
            return
        dt = 0.0 if self.last is None else min(max(now - self.last, 0.0), 5.0) * speed    # a long gap isn't use
        self.last = now
        if not key_on:
            self.was_running = self.was_cranking = False
            self.cool_pending = False
            return
        r = self._rec(day_key(time.time() if wall is None else wall))
        r["key_s"] += dt
        if hours is not None:
            r.setdefault("h0", round(hours, 2))
            r["h1"] = round(hours, 2)
        if cranking:
            r["crank_s"] += dt
            if not self.was_cranking and now - self.crank_end > 1.0:    # a new go on the starter
                r["cranks"] += 1
        elif self.was_cranking:
            self.crank_end = now
        self.was_cranking = cranking
        if running and not self.was_running:
            r["starts"] += 1
        if not running and self.was_running:
            r["stops"] += 1
            if self.cool_pending:
                r["hot_stops"] += 1
        self.was_running = running
        self.cool_pending = cool_pending and running
        if running and rpm is not None:
            r["run_s"] += dt
            band = "over_s" if rpm > self.over_at else "full_s" if rpm >= self.full_at else \
                "work_s" if rpm >= self.idle_below else "idle_s"
            r[band] += dt
            b = str(int(rpm // self.bin * self.bin))
            r["hist"][b] = r["hist"].get(b, 0.0) + dt
            if volts is not None:
                self._extreme(r, "v_run_min", volts, min, wall, 2)
                self._extreme(r, "v_run_max", volts, max, wall, 2)
        if temps:
            if temps.get("box") is not None:
                self._extreme(r, "box_max", temps["box"], max, wall)
                self._extreme(r, "box_min", temps["box"], min, wall)
            for name, t in temps.get("probes", []):
                if t is not None:
                    self._extreme(r, "amb_max", t, max, wall)
                    self._extreme(r, "amb_min", t, min, wall)
                    self._extreme(r, f"p_{name.upper()}_max", t, max, wall)
                    self._extreme(r, f"p_{name.upper()}_min", t, min, wall)
        if pi_temp is not None:
            self._extreme(r, "pi_max", pi_temp, max, wall)
            self._extreme(r, "pi_min", pi_temp, min, wall)
        self.dirty = True
        if now - self.last_save >= self.save_every:
            self.save(now)

    @staticmethod
    def _extreme(r, key, v, pick, wall, digits=1):
        """Keep the day's highest / lowest value, and the time of a new one."""
        v = round(v, digits)
        if key not in r or pick(r[key], v) == v and v != r[key]:
            r[key] = v
            w = time.time() if wall is None else wall
            if clock_valid(w):
                r[key + "_t"] = round(w)

    def save(self, now=None):
        self.last_save = time.monotonic() if now is None else now
        if not self.dirty:
            return
        dated = sorted(k for k in self.days if k != NO_DATE)
        for k in dated[:-self.keep_days] if len(dated) > self.keep_days else []:
            del self.days[k]
        out = {}
        for k, r in self.days.items():
            out[k] = {n: (round(v, 1) if isinstance(v, float) else v) for n, v in r.items() if n != "hist"}
            out[k]["hist"] = {b: round(s, 1) for b, s in r["hist"].items()}
        try:
            write_json(self.dir, FILE, {"bands": self.bands(), "days": out})
            self.save_error = None
            self.dirty = False
        except OSError as e:
            if not self.save_error:
                log.error("can't save %s: %s", FILE, e)
            self.save_error = str(e)

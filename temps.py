"""Temperatures: the breakout box's air (DS18B20 on the board, rev 2.7) and external probes (cab, outside air).

All DS18B20s share the Pi's 1-Wire bus on GPIO 4 (dtoverlay=w1-gpio). Each has a fixed ID like 28-0000012345ab;
`python3 dash.py --temps` lists them so you can tell [temperature] which is which. Read every few seconds in a
background thread: a reading takes ~0.75 s per sensor, so it never holds up the gauges.

Like the tilt sensor, it never makes a value up: a sensor that's missing or reading nonsense shows "--".
The DS18B20's power-on value (exactly 85.0 C) and the driver's error value are thrown away.
"""
import glob
import logging
import os
import threading
import time

log = logging.getLogger("temps")

W1_DIR = "/sys/bus/w1/devices"
OK, WARN, ALARM, UNKNOWN = "ok", "warn", "alarm", "unknown"


def read_ds18b20(path):
    """Degrees C from one sensor's sysfs folder, or None."""
    try:
        with open(os.path.join(path, "temperature")) as f:         # newer kernels: millidegrees
            t = int(f.read().strip()) / 1000.0
    except (OSError, ValueError):
        try:
            with open(os.path.join(path, "w1_slave")) as f:       # older kernels: "... YES\n... t=23125"
                lines = f.read().splitlines()
            if len(lines) < 2 or not lines[0].endswith("YES"):
                return None
            t = int(lines[1].split("t=")[1]) / 1000.0
        except (OSError, ValueError, IndexError):
            return None
    if t == 85.0 or t <= -55.0 or t > 125.0:                      # power-on value / driver error / out of range
        return None
    return t


def to_units(c, units):
    return c * 9 / 5 + 32 if units == "F" else c


class TempSensors:
    """.snapshot() -> {"box": deg C or None, "probes": [(name, deg C or None), ...]}"""

    def __init__(self, cfg, base=W1_DIR, start=True):
        tc = cfg.get("temperature", {})
        self.enabled = tc.get("enabled", True)
        self.board_id = tc.get("board_id", "")
        self.probes = [(p.get("id", ""), p.get("name", "PROBE")) for p in tc.get("probes", [])]
        self.every = tc.get("read_every", 5.0)
        self.base = base
        self._values = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._hinted = False
        if self.enabled and start:
            threading.Thread(target=self._run, name="temps", daemon=True).start()

    def ids(self):
        return sorted(os.path.basename(p) for p in glob.glob(os.path.join(self.base, "28-*")))

    def read_all(self):
        vals = {i: read_ds18b20(os.path.join(self.base, i)) for i in self.ids()}
        with self._lock:
            self._values = vals
        return vals

    def _run(self):
        while not self._stop.is_set():
            self.read_all()
            self._stop.wait(self.every)

    def roles(self, vals=None):
        """Which sensor is the board's and which are probes: from [temperature], or worked out when obvious."""
        with self._lock:
            vals = dict(self._values) if vals is None else vals
        ids = sorted(vals)
        probe_ids = [i for i, _ in self.probes if i]
        board = self.board_id
        if not board:
            spare = [i for i in ids if i not in probe_ids]
            if len(spare) == 1 and len(ids) - len(probe_ids) == 1:
                board = spare[0]                       # only one unassigned sensor: that's the board's
            elif len(spare) > 1 and not self._hinted:
                log.warning("several temperature sensors and no board_id in [temperature]; run "
                            "python3 dash.py --temps to see which is which")
                self._hinted = True
        probes = list(self.probes)
        if not probes:                                 # none named: show any others as T1, T2...
            probes = [(i, f"T{n + 1}") for n, i in enumerate(i for i in ids if i != board)]
        return board, probes, vals

    def snapshot(self):
        board, probes, vals = self.roles()
        return {"box": vals.get(board) if board else None,
                "probes": [(name, vals.get(i)) for i, name in probes]}

    def close(self):
        self._stop.set()


class TempStatus:
    """BOX temperature -> OK / WARN / ALARM (with 2 C hysteresis); the ambient readout text."""

    def __init__(self, cfg):
        tc = cfg.get("temperature", {})
        self.enabled = tc.get("enabled", True)
        self.units = tc.get("units", "F").upper()
        self.warn = tc.get("box_warn", 50.0)
        self.alarm = tc.get("box_alarm", 65.0)
        self.ambient = tc.get("ambient", "each")
        self.state = OK

    def fmt(self, c):
        return "--" if c is None else f"{to_units(c, self.units):.0f}°{self.units}"

    def update(self, snap):
        """snap: TempSensors.snapshot(). Returns {"box": (state, text), "ambient": [text, ...]} or None."""
        if not self.enabled or snap is None:
            return None
        box = snap.get("box")
        if box is None:
            self.state = UNKNOWN
        else:
            hyst = 2.0
            if box >= self.alarm or (self.state == ALARM and box > self.alarm - hyst):
                self.state = ALARM
            elif box >= self.warn or (self.state in (WARN, ALARM) and box > self.warn - hyst):
                self.state = WARN
            else:
                self.state = OK
        word = {OK: "BOX", WARN: "BOX HOT", ALARM: "BOX HOT", UNKNOWN: "BOX"}[self.state]
        probes = snap.get("probes", [])
        if self.ambient == "average":
            got = [t for _, t in probes if t is not None]
            amb = [f"AMB {self.fmt(sum(got) / len(got)) if got else '--'}"] if probes else []
        else:
            amb = [f"{name} {self.fmt(t)}" for name, t in probes]
        return {"box": (self.state, f"{word} {self.fmt(box)}"), "ambient": amb}


def list_cli(cfg):
    """python3 dash.py --temps: every DS18B20 found, its reading and its role."""
    s = TempSensors(cfg, start=False)
    if not os.path.isdir(s.base):
        print("No 1-Wire bus. Add  dtoverlay=w1-gpio  to /boot/firmware/config.txt and reboot.")
        return 1
    vals = s.read_all()
    if not vals:
        print("No DS18B20 sensors found on the 1-Wire bus (GPIO 4). Check the board sensor U11 and the probe plug.")
        return 1
    board, probes, _ = s.roles(vals)
    names = dict(probes)
    st = TempStatus(cfg)
    print("Temperature sensors on the 1-Wire bus:")
    for i, t in vals.items():
        role = "BOARD (box air)" if i == board else f"probe '{names[i]}'" if i in names else "not assigned"
        print(f"  {i}   {st.fmt(t):>7}   {role}")
    print("\nTo tell them apart, hold one in your fingers for 20 s and run this again: its reading rises.")
    print("Then name them in config.toml, [temperature]:  board_id = \"28-...\"  and")
    print("  probes = [ { id = \"28-...\", name = \"OUT\" }, { id = \"28-...\", name = \"CAB\" } ]")
    return 0

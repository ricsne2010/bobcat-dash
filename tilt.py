"""Machine angle: roll (side to side) and pitch (nose up / down), from a small accelerometer + gyro board.

Sensor: an LSM6DSOX (Adafruit 4438) or LSM6DS3TR-C (Adafruit 4503) breakout on the Pi's I2C bus, next to the
ADS1115 (different address, so they share the bus). Mount it RIGIDLY to the machine, not on a rubber-mounted
box, with its X arrow pointing forward (or set the axes in [tilt]).

An accelerometer alone reads "tilt" every time the machine accelerates, brakes or bounces. So the angle comes
from a complementary filter: the gyro tracks quick changes, and the accelerometer slowly pulls it back to true
level. Read ~100 times a second in a background thread.

Limits ([tilt] in config.toml) are conservative defaults, NOT figures from Bobcat: Bobcat's manuals say to keep
the heavy end uphill and not to work across slopes, but give no angles. Zero it once on level ground:
    python3 dash.py --zero-tilt
"""
import json
import logging
import math
import os
import threading
import time

log = logging.getLogger("tilt")

OK, WARN, ALARM, UNKNOWN = "ok", "warn", "alarm", "unknown"

# LSM6DSOX / LSM6DS3TR-C registers
WHO_AM_I, CTRL1_XL, CTRL2_G, OUTX_L_G = 0x0F, 0x10, 0x11, 0x22
IDS = {0x6C: "LSM6DSOX", 0x6A: "LSM6DS3TR-C", 0x69: "LSM6DS3"}
ACCEL_G_PER_LSB = 0.122e-3      # +-4 g
GYRO_DPS_PER_LSB = 8.75e-3      # +-250 deg/s


def zero_file(cfg):
    d = os.path.expanduser(cfg.get("hourmeter", {}).get("data_dir", "~/bobcat-dash-data"))
    return os.path.join(d, "tilt_zero.json")


def accel_angles(ax, ay, az):
    """Roll and pitch (degrees) from gravity alone. X forward, Y left, Z up (the board's own axes).
    Roll > 0 = right side down. Pitch > 0 = nose up."""
    roll = math.degrees(math.atan2(ay, az))         # right side down tips the left (+Y) axis up: +ay
    pitch = math.degrees(math.atan2(ax, math.hypot(ay, az)))
    return roll, pitch


class ComplementaryFilter:
    """tau: seconds over which the accelerometer pulls the angle back to true level. Longer = bumps and
    braking move it less; the gyro still follows real tilting at once."""

    def __init__(self, tau=3.0, settle=1.0):
        self.tau = tau
        self.settle = settle             # seconds of readings averaged before the first angle is given
        self.roll = self.pitch = None
        self._t = 0.0                    # time spent settling
        self._turned = [0.0, 0.0]        # rotation the gyro saw while settling
        self._turned_sum = [0.0, 0.0]
        self._acc = [0.0, 0.0, 0.0]      # summed gravity readings
        self._n = 0

    def update(self, accel, gyro, dt):
        """accel: (ax, ay, az) in g. gyro: (gx, gy, gz) in deg/s. Returns (roll, pitch), or None while it settles.

        Start-up: no stored position is needed: gravity gives the true angle wherever the machine is parked.
        The first `settle` seconds of gravity readings are averaged (the raw readings first, then the angle,
        which doesn't skew under vibration the way averaging angles does). Rotation the gyro sees meanwhile is
        allowed for, so even a machine already moving starts at the right angle."""
        ar, ap = accel_angles(*accel)
        if self.roll is None:
            if self._n:
                self._turned[0] += gyro[0] * dt
                self._turned[1] -= gyro[1] * dt
                self._t += dt
            self._acc = [a + b for a, b in zip(self._acc, accel)]
            self._turned_sum = [a + b for a, b in zip(self._turned_sum, self._turned)]
            self._n += 1
            if self._t < self.settle:
                return None
            mr, mp = accel_angles(*self._acc)            # angle of the averaged gravity
            self.roll = mr - self._turned_sum[0] / self._n + self._turned[0]
            self.pitch = mp - self._turned_sum[1] / self._n + self._turned[1]
        else:
            a = self.tau / (self.tau + dt)
            # right-hand rule: right side down = +rotation about X (forward); nose up = -rotation about Y (left)
            self.roll = a * (self.roll + gyro[0] * dt) + (1 - a) * ar
            self.pitch = a * (self.pitch - gyro[1] * dt) + (1 - a) * ap
        return self.roll, self.pitch


class TiltSensor:
    """Hardware reader. .angles() -> (roll, pitch) in degrees, or None if there's no sensor answering."""

    def __init__(self, cfg):
        tc = cfg.get("tilt", {})
        self.enabled = tc.get("enabled", True)
        self.bus_n = cfg.get("adc", {}).get("i2c_bus", 1)
        self.address = tc.get("address", 0x6A)
        self.axes = tc.get("axes", "x_forward")          # x_forward | y_forward | x_back | y_back
        self.flip = tc.get("upside_down", False)
        self.filter = ComplementaryFilter(tc.get("filter_seconds", 3.0))
        self.offsets, self.gyro_bias = self._load_offsets(cfg)
        self._gyro_sum, self._gyro_n = [0.0, 0.0, 0.0], 0
        self._latest = None
        self._last_ok = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        if self.enabled:
            threading.Thread(target=self._run, name="tilt", daemon=True).start()

    @staticmethod
    def _load_offsets(cfg):
        try:
            with open(zero_file(cfg)) as f:
                z = json.load(f)
            return (float(z["roll"]), float(z["pitch"])), tuple(z.get("gyro_bias", (0.0, 0.0, 0.0)))
        except (OSError, ValueError, KeyError):
            return (0.0, 0.0), (0.0, 0.0, 0.0)

    def _orient(self, x, y, z):
        """Board axes -> machine axes (X forward, Y left, Z up)."""
        if self.flip:
            y, z = -y, -z
        return {"x_forward": (x, y, z), "x_back": (-x, -y, z),
                "y_forward": (y, -x, z), "y_back": (-y, x, z)}[self.axes]

    def _run(self):
        try:
            from smbus2 import SMBus
            bus = SMBus(self.bus_n)
            who = bus.read_byte_data(self.address, WHO_AM_I)
            if who not in IDS:
                raise OSError(f"unexpected chip id 0x{who:02x} at 0x{self.address:02x}")
            bus.write_byte_data(self.address, CTRL1_XL, 0x48)     # accel 104 Hz, +-4 g
            bus.write_byte_data(self.address, CTRL2_G, 0x40)      # gyro 104 Hz, +-250 deg/s
            log.info("tilt sensor %s at 0x%02x", IDS[who], self.address)
        except Exception as e:
            log.warning("no tilt sensor (%s): the angle panel shows NO SIGNAL", e)
            return
        t = time.monotonic()
        while not self._stop.is_set():
            try:
                raw = bus.read_i2c_block_data(self.address, OUTX_L_G, 12)
                v = [int.from_bytes(bytes(raw[i:i + 2]), "little", signed=True) for i in range(0, 12, 2)]
                g_raw = self._orient(*(n * GYRO_DPS_PER_LSB for n in v[:3]))
                self._gyro_sum = [a + b for a, b in zip(self._gyro_sum, g_raw)]
                self._gyro_n += 1
                gyro = tuple(a - b for a, b in zip(g_raw, self.gyro_bias))
                accel = self._orient(*(n * ACCEL_G_PER_LSB for n in v[3:]))
                now = time.monotonic()
                out = self.filter.update(accel, gyro, min(0.05, now - t))
                t = now
                if out is None:              # still settling (first half second)
                    continue
                roll, pitch = out
                with self._lock:
                    self._latest = (roll - self.offsets[0], pitch - self.offsets[1])
                    self._last_ok = now
            except OSError as e:
                log.debug("tilt read failed: %s", e)
            self._stop.wait(0.01)

    def angles(self):
        with self._lock:
            if self._latest is None or time.monotonic() - self._last_ok > 1.0:
                return None
            return self._latest

    def mean_gyro(self):
        """Average raw gyro rate since the last call (for --zero-tilt: the bias while parked)."""
        with self._lock:
            n = max(1, self._gyro_n)
            m = tuple(a / n for a in self._gyro_sum)
            self._gyro_sum, self._gyro_n = [0.0, 0.0, 0.0], 0
        return m

    def raw_angles(self):
        """Without the zero offsets (for --zero-tilt)."""
        a = self.angles()
        return None if a is None else (a[0] + self.offsets[0], a[1] + self.offsets[1])

    def close(self):
        self._stop.set()


class TiltStatus:
    """Turns angles into OK / WARN / ALARM. A level must hold for `hold` seconds before it shows (a bump
    isn't a slope), and drops back only once the angle is `hysteresis` degrees inside the limit."""

    def __init__(self, cfg):
        tc = cfg.get("tilt", {})
        self.enabled = tc.get("enabled", True)
        # pitch has its own limits each way: backing up a steep incline points the nose down, which a skid
        # steer tolerates better (heavy end uphill) than nose up
        self.lim = {"roll": (tc.get("roll_warn", 8.0), tc.get("roll_alarm", 15.0)),
                    "nose_up": (tc.get("pitch_up_warn", 15.0), tc.get("pitch_up_alarm", 20.0)),
                    "nose_down": (tc.get("pitch_down_warn", 20.0), tc.get("pitch_down_alarm", 25.0))}
        self.hold = tc.get("hold", 0.5)
        self.hyst = tc.get("hysteresis", 1.0)
        self.level = {"roll": OK, "pitch": OK}
        self.pending = {"roll": (OK, None), "pitch": (OK, None)}

    def limits(self, name, angle):
        if name == "roll":
            return self.lim["roll"]
        return self.lim["nose_up" if angle >= 0 else "nose_down"]

    def _axis(self, name, angle, now):
        warn, alarm = self.limits(name, angle)
        a = abs(angle)
        target = ALARM if a >= alarm else WARN if a >= warn else OK
        cur = self.level[name]
        rank = {OK: 0, WARN: 1, ALARM: 2}
        if rank[target] < rank[cur]:                        # going down: only once clearly inside the limit
            edge = alarm if cur == ALARM else warn
            if a > edge - self.hyst:
                target = cur
        if target == cur:
            self.pending[name] = (cur, None)
        elif rank[target] > rank[cur]:                      # going up: must hold
            p, since = self.pending[name]
            if p != target:
                self.pending[name] = (target, now)
            elif now - since >= self.hold:
                self.level[name] = target
        else:
            self.level[name] = target
        return self.level[name]

    def update(self, angles, now):
        """angles: (roll, pitch) or None. Returns {"state", "text", "roll": state, "pitch": state, "angles"}."""
        if not self.enabled:
            return None
        if angles is None:
            return {"state": UNKNOWN, "text": "NO SIGNAL", "roll": UNKNOWN, "pitch": UNKNOWN, "angles": None}
        rs, ps = self._axis("roll", angles[0], now), self._axis("pitch", angles[1], now)
        worst = max((rs, ps), key=lambda s: {OK: 0, WARN: 1, ALARM: 2}[s])
        text = {OK: "LEVEL" if max(abs(angles[0]), abs(angles[1])) < 3 else "OK",
                WARN: "STEEP", ALARM: "TIP RISK"}[worst]
        return {"state": worst, "text": text, "roll": rs, "pitch": ps, "angles": angles}


MAX_ZERO_OFF = 5.0       # degrees: a sensor reading more than this off level is on a slope (or mounted crooked)
MAX_ZERO_WOBBLE = 0.5    # degrees: readings moving more than this = the machine isn't still


def zero_check(samples, force=False):
    """Can these readings be saved as level? Returns (ok, message)."""
    import statistics
    r = [a[0] for a in samples]
    p = [a[1] for a in samples]
    mr, mp = sum(r) / len(r), sum(p) / len(p)
    wobble = max(max(r) - min(r), max(p) - min(p))
    if wobble > MAX_ZERO_WOBBLE and not force:
        return False, (f"Not saved: the readings moved by {wobble:.1f} deg while measuring. Stop the engine, get off "
                       "the machine, and run it again with nothing moving.")
    if (abs(mr) > MAX_ZERO_OFF or abs(mp) > MAX_ZERO_OFF) and not force:
        return False, (f"Not saved: the sensor reads roll {mr:+.1f} deg, pitch {mp:+.1f} deg, more than "
                       f"{MAX_ZERO_OFF:.0f} deg from level. Either the machine isn't on level ground (check with a "
                       "spirit level on the frame), or the sensor is mounted crooked (straighten it). If you're sure "
                       "the machine IS level, run:  python3 dash.py --zero-tilt --force")
    return True, ""


def zero_cli(cfg, force=False):
    """Park on level ground, then: python3 dash.py --zero-tilt. Averages 3 s and saves the offsets.
    Refuses on a slope (> 5 deg) or while the machine is moving, unless force=True."""
    s = TiltSensor(cfg)
    time.sleep(1.5)
    s.mean_gyro()                       # start the gyro average fresh
    samples = []
    for _ in range(30):
        a = s.raw_angles()
        if a:
            samples.append(a)
        time.sleep(0.1)
    bias = s.mean_gyro()
    s.close()
    if not samples:
        print("No tilt sensor answering. Check its wiring and the address in [tilt].")
        return 1
    ok, msg = zero_check(samples, force)
    if not ok:
        print(msg)
        return 1
    r = sum(a[0] for a in samples) / len(samples)
    p = sum(a[1] for a in samples) / len(samples)
    path = zero_file(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"roll": r, "pitch": p, "gyro_bias": bias, "saved": time.strftime("%Y-%m-%d %H:%M")}, f)
    print(f"Level saved: the sensor read roll {r:+.1f} deg, pitch {p:+.1f} deg here; that's now zero. ({path})")
    return 0

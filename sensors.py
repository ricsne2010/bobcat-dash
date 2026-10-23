"""Sensor inputs for the Bobcat dash.

Hardware (Raspberry Pi):
  * ADS1115 16-bit ADC on I2C   -> battery voltage, fuel sender, and the filter
                                   and temp switches (monitored: 4.7k end-of-line resistor)
  * Optocoupled GPIO inputs     -> tach pulses, oil pressure switch

Every reading is either a number/bool or None. None means "no signal"
(sensor missing, wire broken, ADC not answering) and is shown in grey.
"""
import logging
import math
import threading
import time
from collections import deque

log = logging.getLogger("sensors")


class Smoother:
    """Exponential moving average. Resets when the input goes missing."""

    def __init__(self, alpha):
        self.alpha = alpha
        self.value = None

    def update(self, x):
        if x is None:
            self.value = None
        elif self.value is None:
            self.value = x
        else:
            self.value += self.alpha * (x - self.value)
        return self.value


class Debounce:
    """A switch must hold its new state for on_delay/off_delay seconds before
    it counts. Stops the oil light flickering at idle, but still reacts fast."""

    def __init__(self, on_delay, off_delay):
        self.on_delay = on_delay
        self.off_delay = off_delay
        self.state = False
        self.pending_since = None

    def update(self, raw, now):
        if raw == self.state:
            self.pending_since = None
            return self.state
        if self.pending_since is None:
            self.pending_since = now
        delay = self.on_delay if raw else self.off_delay
        if now - self.pending_since >= delay:
            self.state = raw
            self.pending_since = None
        return self.state


def classify_monitored(volts, wc):
    """A switch with a 4.7k end-of-line resistor, read through the ADC:
    ~0 V = switch closed (True), ~1.65 V = open and wiring OK (False),
    3.3 V = wire broken or sensor unplugged (None)."""
    if volts is None or volts > wc.get("open_above", 2.6):
        return None
    return volts < wc.get("active_below", 0.8)


class TriDebounce:
    """Like Debounce, but for True / False / None (wire fault). A new state
    must hold for its delay before it counts, so a loose connector can't flicker."""

    NOTHING = object()      # "no change pending" (None is a real state: wire fault)

    def __init__(self, on_delay, off_delay, fault_delay=1.0):
        self.delays = {True: on_delay, False: off_delay, None: fault_delay}
        self.state = self.NOTHING
        self.pending = self.NOTHING
        self.pending_since = 0.0

    def update(self, raw, now):
        if self.state is self.NOTHING:          # first reading counts straight away
            self.state = raw
        if raw == self.state:
            self.pending = self.NOTHING
            return self.state
        if self.pending is self.NOTHING or raw != self.pending:
            self.pending, self.pending_since = raw, now
        if now - self.pending_since >= self.delays[raw]:
            self.state, self.pending = raw, self.NOTHING
        return self.state


class ADS1115:
    """Minimal single-shot driver for the ADS1115, ±4.096 V range."""

    def __init__(self, bus, address):
        try:
            from smbus2 import SMBus
        except ImportError:
            from smbus import SMBus
        self.bus = SMBus(bus)
        self.address = address

    def read_volts(self, channel):
        config = (
            0x8000                      # start a conversion
            | ((4 + channel) << 12)     # AINx vs GND
            | (1 << 9)                  # PGA ±4.096 V
            | (1 << 8)                  # single-shot
            | (4 << 5)                  # 128 samples/s
            | 0x03                      # comparator off
        )
        self.bus.write_i2c_block_data(self.address, 0x01, [(config >> 8) & 0xFF, config & 0xFF])
        time.sleep(0.009)
        hi, lo = self.bus.read_i2c_block_data(self.address, 0x00, 2)
        raw = (hi << 8) | lo
        if raw & 0x8000:
            raw -= 1 << 16
        return raw * 4.096 / 32768


class Tach:
    """Counts pulses on a GPIO and turns the pulse rate into RPM.

    min_gap: pulses closer together than this (seconds) are ignored. An ignition coil rings
    for a moment after each spark, which can look like extra pulses; real sparks on a
    4-cylinder at 3500 rpm are 8.6 ms apart, so ignoring 3 ms after each one loses nothing."""

    def __init__(self, gpio, pulses_per_rev, timeout=1.0, min_gap=0.0):
        from gpiozero import DigitalInputDevice

        self.ppr = pulses_per_rev
        self.timeout = timeout
        self.min_gap = min_gap
        self.edges = deque(maxlen=64)
        self.lock = threading.Lock()
        self.dev = DigitalInputDevice(gpio, pull_up=True)  # optocoupler pulls the pin low
        self.dev.when_activated = self._edge

    def _edge(self):
        now = time.monotonic()
        with self.lock:
            if self.edges and now - self.edges[-1] < self.min_gap:
                return                      # ringing after a spark, not a new spark
            self.edges.append(now)

    def rpm(self):
        with self.lock:
            edges = list(self.edges)
        now = time.monotonic()
        if len(edges) < 2 or now - edges[-1] > self.timeout:
            return 0.0
        recent = [t for t in edges if now - t <= 0.5]
        if len(recent) < 2:
            recent = edges[-2:]
        span = recent[-1] - recent[0]
        if span <= 0:
            return 0.0
        hz = (len(recent) - 1) / span
        return hz * 60.0 / self.ppr


def make_tach(cfg):
    tc = cfg["tach"]
    return Tach(tc["gpio"], tc["pulses_per_rev"], min_gap=tc.get("min_pulse_gap_ms", 0.0) / 1000.0)


def fuel_percent(volts, table, fault_margin):
    """Interpolate the calibration table [[volts, percent], ...].
    Readings well outside the table mean an open or shorted sender -> None."""
    if volts is None:
        return None
    pts = sorted(table)
    if volts < pts[0][0] - fault_margin or volts > pts[-1][0] + fault_margin:
        return None
    if volts <= pts[0][0]:
        pct = pts[0][1]
    elif volts >= pts[-1][0]:
        pct = pts[-1][1]
    else:
        for (v0, p0), (v1, p1) in zip(pts, pts[1:]):
            if v0 <= volts <= v1:
                pct = p0 + (p1 - p0) * (volts - v0) / (v1 - v0)
                break
    return max(0.0, min(100.0, pct))


class HardwareSensors:
    """Reads the real sensors on a background thread, 20 times a second."""

    def __init__(self, cfg):
        from gpiozero import DigitalInputDevice

        self.cfg = cfg
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._failing = set()
        self._snapshot = {
            "volts": None,
            "fuel_pct": None,
            "rpm": None,
            "warnings": {name: None for name in cfg["warnings"]},
            "key": None,
            "lights": {},
        }

        try:
            self.adc = ADS1115(cfg["adc"]["i2c_bus"], cfg["adc"]["address"])
        except Exception as e:
            log.error("ADC not available: %s", e)
            self.adc = None

        self.volts = Smoother(cfg["voltage"]["smoothing"])
        self.fuel = Smoother(cfg["fuel"]["smoothing"])
        self.rpm = Smoother(cfg["tach"]["smoothing"])
        self.tach = make_tach(cfg)

        # key switch, through the board's optocoupler: pin pulled low = key on
        pc = cfg.get("power", {})
        self.key = DigitalInputDevice(pc["key_gpio"], pull_up=True) if pc.get("enabled") else None

        # light switches, through the board's optocouplers: pin pulled low = that light is on
        self.lights = {}
        lc = cfg.get("lights", {})
        if lc.get("enabled"):
            for name, sc in light_inputs(cfg).items():
                deb = lc.get("debounce", 0.2)
                self.lights[name] = (DigitalInputDevice(sc["gpio"], pull_up=True), Debounce(deb, deb))

        from gpiozero import LED

        self.switches = {}      # plain on/off switches on a GPIO (through an optocoupler)
        self.monitored = {}     # switches with an end-of-line resistor, read on an ADC channel
        self.leds = {}          # board status LEDs driven by the Pi for monitored switches
        for name, wc in cfg["warnings"].items():
            delays = (wc.get("on_delay", 0.3), wc.get("off_delay", 1.0))
            if "adc_channel" in wc:
                self.monitored[name] = TriDebounce(*delays, wc.get("fault_delay", 1.0))
                if "led_gpio" in wc:
                    self.leds[name] = [LED(wc["led_gpio"]), "unset"]
            else:
                dev = DigitalInputDevice(wc["gpio"], pull_up=wc.get("active_low", True))
                self.switches[name] = (dev, Debounce(*delays))

        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self._stop.set()
        for led, _ in self.leds.values():
            led.off()

    def handle_key(self, key):
        pass

    def _show_led(self, name, state):
        """Status LED: on = active, off = OK, blinking = wire fault."""
        entry = self.leds.get(name)
        if entry is None or entry[1] == state:
            return
        led = entry[0]
        if state is None:
            led.blink(on_time=0.25, off_time=0.25)
        elif state:
            led.on()
        else:
            led.off()
        entry[1] = state

    def read(self):
        with self.lock:
            return dict(self._snapshot)

    def _adc(self, channel):
        if self.adc is None:
            return None
        try:
            v = self.adc.read_volts(channel)
            if channel in self._failing:
                log.info("ADC channel %d recovered", channel)
                self._failing.discard(channel)
            return v
        except OSError as e:
            if channel not in self._failing:
                log.warning("ADC channel %d read failed: %s", channel, e)
                self._failing.add(channel)
            return None

    def _run(self):
        vc, fc = self.cfg["voltage"], self.cfg["fuel"]
        while not self._stop.is_set():
            now = time.monotonic()

            raw_v = self._adc(vc["adc_channel"])
            volts = self.volts.update(None if raw_v is None else raw_v * vc["divider_ratio"])

            raw_f = self._adc(fc["adc_channel"])
            fuel = self.fuel.update(fuel_percent(raw_f, fc["table"], fc["fault_margin"]))

            rpm = self.rpm.update(self.tach.rpm())

            warnings = {
                name: deb.update(dev.is_active, now)
                for name, (dev, deb) in self.switches.items()
            }
            for name, deb in self.monitored.items():
                wc = self.cfg["warnings"][name]
                warnings[name] = deb.update(classify_monitored(self._adc(wc["adc_channel"]), wc), now)
                self._show_led(name, warnings[name])

            with self.lock:
                lights = {name: deb.update(dev.is_active, now) for name, (dev, deb) in self.lights.items()}
                self._snapshot = {"volts": volts, "fuel_pct": fuel, "rpm": rpm, "warnings": warnings,
                                  "key": None if self.key is None else self.key.is_active, "lights": lights}
            self._stop.wait(0.05)


class SimSensors:
    """A fake engine so the display can be tested on any computer.
    Press H on the dash to see the keys (listed in HELP below)."""

    HELP = [
        ("S", "start (cranks ~2.5 s, battery dips) / stop engine"),
        ("C", "cold engine: longer crank, deeper dip"),
        ("W", "engine won't start (S again = let go of the key)"),
        ("K", "key on / off (the sim starts with the key off)"),
        ("7, 8, 9", "front light switch / rear / work (3-way switch)"),
        ("Y", "lights wired to the battery, not the key (test warning)"),
        ("Up / Down", "throttle (idle to governed speed)"),
        ("1, 2, 3", "toggle oil / filter / temp warning"),
        ("4, 5, 6", "unplug / replug oil / filter / temp sensor"),
        ("B", "cycle battery: auto, 12.5, 12.0, 11.2, 0, 15.0, 16.2 V"),
        ("[ / ]", "battery voltage down / up 0.2 V"),
        ("V", "unplug / replug voltage sensor"),
        ("F / G", "fuel down / up 5%"),
        ("L / E / R", "fuel low 10% / empty 0% / refill 100%"),
        ("N", "unplug / replug fuel sender"),
        ("O", "oil pump fails / works (pressure never builds)"),
        ("T", "tach sensor fails / works (reads 0 rpm)"),
        ("Z", "governor fails / works (engine overspeeds)"),
        ("D", "engine bogs to ~700 rpm / recovers (low idle)"),
        ("Left / Right", "roll the machine 3 deg (right = right side down)"),
        (", / .  / 0", "pitch nose down / nose up 3 deg; 0 = level ground"),
        ("P / X", "hour meter +10 h / hours + cool-down 60x faster"),
        ("I / U", "Pi too hot / 5 V supply low (each on / off)"),
        ("J", "light display: big tiles / small icons"),
        ("A", "reset all overrides"),
        ("M / click", "silence alarm (new alarms sound again)"),
        ("H", "show / hide this help"),
        ("Esc / Q", "quit"),
    ]

    BATTERY_PRESETS = [
        ("auto", None),
        ("resting", 12.5),
        ("low", 12.0),
        ("very low", 11.2),
        ("dead", 0.0),
        ("high", 15.0),
        ("overcharge", 16.2),
    ]

    def __init__(self, cfg):
        self.cfg = cfg
        self.names = list(cfg["warnings"])
        self.running = False         # the engine has been started (cranking or running)
        self.crank_left = 0.0        # seconds of cranking left before it catches
        self.run_time = 0.0          # seconds since it caught
        self.off_time = 1e6          # seconds since it stopped
        self.cold = False            # C: cold engine (longer crank, deeper battery dip)
        self.tilt_target = [0.0, 0.0]   # Left / Right = roll, , / . = pitch, 0 = level
        self.tilt = [0.0, 0.0]
        self.no_start = False        # W: it won't catch (no fuel / no spark): cranks until you let go
        self.ran = False             # it ran (and charged) since the last start attempt
        self.volts = 12.6            # battery model: dips while cranking, charges once running
        sc = cfg.get("sim", {})
        self.crank_s, self.crank_v = sc.get("crank_seconds", 2.5), sc.get("crank_volts", 10.2)
        self.key_on = False          # start like a parked machine: press K to turn the key on
        self.front_switch = False    # front light switch: on / off
        self.rear_switch = "off"     # 3-position switch: "rear", "off" or "work"
        self.lights_on_battery = False   # True = lights stay powered with the key off (to test the warning)
        self.light_names = list(light_inputs(cfg))
        self.throttle = 0.3
        self.rpm = 0.0
        self.oil_pressure = 0.0      # 0 = none, 1 = full; the switch opens at full pressure
        self.t = time.monotonic()
        self.reset()                 # test overrides only; engine state above is left alone

    def reset(self):
        self.fuel = 68.0
        self.forced = set()
        self.unplugged = set()       # warning switches with a broken wire (reads None)
        self.volts_unplugged = False
        self.fuel_unplugged = False
        self.oil_pump_failed = False
        self.tach_failed = False
        self.governor_failed = False
        self.idle_sag = False        # D: idle drops toward a stall (LOW IDLE warning)
        self.battery_preset = 0
        self.volts_override = None   # fixed battery voltage, or None for the realistic model

    def start(self):
        pass

    def stop(self):
        pass

    def _battery(self, now, dt, cranking):
        """Battery voltage. Cranking: the starter pulls it down to ~10 V, with a ripple from each
        compression stroke. Caught: it recovers for a moment, then the 10SI brings it up to ~14.1 V
        over a couple of seconds. Stopped: it settles back to its resting 12.6 V."""
        if cranking:
            dip = self.crank_v - (0.5 if self.cold else 0.0)
            target, tau = dip + 0.35 * math.sin(2 * math.pi * 7.0 * now), 0.15
        elif self.running and self.rpm >= self.cfg["tach"]["running_rpm"]:
            target, tau = (12.3, 0.4) if self.run_time < 1.0 else (14.1 + 0.08 * math.sin(now * 1.3), 1.5)
        else:   # alternator output stops at once; surface charge (or, after a failed start, the drain) fades
            target, tau = 12.6 + (0.3 if self.ran else -0.15) * math.exp(-self.off_time / 60.0), 0.5
        self.volts += (target - self.volts) * min(1.0, dt / tau)
        return self.volts

    def handle_key(self, key):
        if key in ("left", "right"):          # roll: right = right side down
            self.tilt_target[0] = max(-30.0, min(30.0, self.tilt_target[0] + (3.0 if key == "right" else -3.0)))
            return
        if key in (",", "."):                 # pitch: . = nose up
            self.tilt_target[1] = max(-30.0, min(30.0, self.tilt_target[1] + (3.0 if key == "." else -3.0)))
            return
        if key == "0":
            self.tilt_target = [0.0, 0.0]
            return
        if key == "s":
            self.running = not self.running and self.key_on   # no ignition, no start
            self.crank_left = (self.crank_s * (2.2 if self.cold else 1.0)) if self.running else 0.0
            if self.running and self.no_start:
                self.crank_left = float("inf")
            if self.running:
                self.ran = False
            self.run_time = 0.0
            self.off_time = 0.0 if not self.running else self.off_time
        elif key == "c":
            self.cold = not self.cold
        elif key == "w":
            self.no_start = not self.no_start
            if self.no_start and self.running and self.crank_left > 0:
                self.crank_left = float("inf")
        elif key == "7":
            self.front_switch = not self.front_switch
        elif key == "8":
            self.rear_switch = "off" if self.rear_switch == "rear" else "rear"
        elif key == "9":
            self.rear_switch = "off" if self.rear_switch == "work" else "work"
        elif key == "y":
            self.lights_on_battery = not self.lights_on_battery
        elif key == "k":
            self.key_on = not self.key_on
            if not self.key_on:
                self.running = False         # the ignition loses power, so the engine stops
        elif key == "up":
            self.throttle = min(1.0, self.throttle + 0.1)
        elif key == "down":
            self.throttle = max(0.0, self.throttle - 0.1)
        elif key.isdigit() and 1 <= int(key) <= len(self.names):
            self.forced ^= {self.names[int(key) - 1]}
        elif key.isdigit() and len(self.names) < int(key) <= 2 * len(self.names):
            self.unplugged ^= {self.names[int(key) - len(self.names) - 1]}
        # battery
        elif key == "b":
            self.battery_preset = (self.battery_preset + 1) % len(self.BATTERY_PRESETS)
            self.volts_override = self.BATTERY_PRESETS[self.battery_preset][1]
        elif key in ("[", "]"):
            base = self.volts_override if self.volts_override is not None else self.volts
            step = 0.2 if key == "]" else -0.2
            self.volts_override = round(max(0.0, min(18.0, base + step)), 1)
            self.battery_preset = -1    # manual
        elif key == "v":
            self.volts_unplugged = not self.volts_unplugged
        # fuel
        elif key == "f":
            self.fuel = max(0.0, self.fuel - 5)
        elif key == "g":
            self.fuel = min(100.0, self.fuel + 5)
        elif key == "l":
            self.fuel = 10.0
        elif key == "e":
            self.fuel = 0.0
        elif key == "r":
            self.fuel = 100.0
        elif key == "n":
            self.fuel_unplugged = not self.fuel_unplugged
        elif key == "o":
            self.oil_pump_failed = not self.oil_pump_failed
        elif key == "t":
            self.tach_failed = not self.tach_failed
        elif key == "z":
            self.governor_failed = not self.governor_failed
        elif key == "d":
            self.idle_sag = not self.idle_sag
        elif key == "a":
            self.reset()

    def status(self):
        """Short description of active test overrides, shown in the header."""
        parts = []
        if not self.key_on:
            parts.append("KEY OFF")
        if self.lights_on_battery:
            parts.append("lights on battery")
        if self.volts_unplugged:
            parts.append("batt: unplugged")
        elif self.volts_override is not None:
            name = self.BATTERY_PRESETS[self.battery_preset][0] if self.battery_preset >= 0 else "manual"
            parts.append(f"batt: {name} {self.volts_override:.1f}V")
        if self.fuel_unplugged:
            parts.append("fuel: unplugged")
        if self.oil_pump_failed:
            parts.append("oil pump: FAILED")
        if self.tach_failed:
            parts.append("tach: FAILED")
        if self.governor_failed:
            parts.append("governor: FAILED")
        if self.cold:
            parts.append("cold engine")
        if self.no_start:
            parts.append("won't start")
        if self.idle_sag:
            parts.append("idle: SAGGING")
        gone = [n.replace("hyd_", "").replace("_pressure", "").replace("_", " ") for n in self.names if n in self.unplugged]
        if gone:
            parts.append("unplugged: " + ", ".join(gone))
        return "SIM  " + "  ".join(parts) if parts else "SIM  (H = keys)"

    def read(self):
        now = time.monotonic()
        dt, self.t = now - self.t, now
        tc = self.cfg["tach"]

        target, rate = 0.0, 2.5
        cranking = self.running and self.crank_left > 0
        if cranking:                            # starter turning it over: ~200 rpm, uneven
            self.crank_left -= dt
            target, rate = 200 + 30 * math.sin(2 * math.pi * 3.5 * now), 6.0
        elif self.running:
            self.run_time += dt
            self.ran = True
            idle, governed = tc.get("idle_rpm", 1000), tc.get("governed_rpm", tc["max_rpm"])
            target = idle + self.throttle * (governed - idle)
            if self.governor_failed:
                target = governed + 450         # runaway: past the red line
            elif self.idle_sag:
                target = 700                    # bogging / running rough, close to stalling
        else:
            self.off_time += dt
        self.rpm += (target - self.rpm) * min(1.0, dt * rate)
        if self.running:
            self.fuel = max(0.0, self.fuel - dt * 0.05)

        auto = self._battery(now, dt, cranking)
        for i in (0, 1):                      # the machine eases onto a new slope, with a little vibration
            self.tilt[i] += (self.tilt_target[i] - self.tilt[i]) * min(1.0, dt * 1.5)
        shake = 0.4 * math.sin(now * 23.0) if self.running and self.crank_left <= 0 else 0.0
        volts = self.volts_override if self.volts_override is not None else auto
        engine_turning = self.rpm >= tc["running_rpm"]

        # Oil pressure takes about 2.5 s to build after start-up and drops quickly at shutdown.
        if engine_turning and not self.oil_pump_failed:
            self.oil_pressure = min(1.0, self.oil_pressure + dt / 2.5)
        else:
            self.oil_pressure = max(0.0, self.oil_pressure - dt * 2.0)

        warnings = {}
        for name in self.names:
            wc = self.cfg["warnings"][name]
            # A real oil-pressure switch stays closed until the pressure is up.
            no_pressure = wc.get("ignore_when_engine_off", False) and self.oil_pressure < 1.0
            warnings[name] = None if name in self.unplugged else (name in self.forced or no_pressure)

        return {
            "volts": None if self.volts_unplugged else volts,
            "fuel_pct": None if self.fuel_unplugged else self.fuel,
            "rpm": 0.0 if self.tach_failed else self.rpm,
            "warnings": warnings,
            "key": self.key_on,
            "lights": self.light_states(),
            "tilt": (self.tilt[0] + shake, self.tilt[1] + 0.5 * shake),
        }

    def light_states(self):
        """Lamp side of each switch: the lights are fed through the key (a relay), so with the
        key off they're dark whatever the switch says, unless Y says they're on the battery."""
        powered = self.key_on or self.lights_on_battery
        on = {"front": self.front_switch, "rear": self.rear_switch == "rear", "work": self.rear_switch == "work"}
        return {name: bool(powered and on.get(name, False)) for name in self.light_names}


def light_inputs(cfg):
    """{name: settings} for each [lights.*] input (front, rear, work)."""
    return {k: v for k, v in cfg.get("lights", {}).items() if isinstance(v, dict)}


def make_sensors(cfg, sim=False):
    return SimSensors(cfg) if sim else HardwareSensors(cfg)


def calibrate(cfg):
    """Print raw readings so you can fill in config.toml. Ctrl-C to stop."""
    from gpiozero import DigitalInputDevice

    adc = ADS1115(cfg["adc"]["i2c_bus"], cfg["adc"]["address"])
    tach = make_tach(cfg)
    switches = {
        name: DigitalInputDevice(wc["gpio"], pull_up=wc.get("active_low", True))
        for name, wc in cfg["warnings"].items() if "adc_channel" not in wc
    }
    monitored = {name: wc for name, wc in cfg["warnings"].items() if "adc_channel" in wc}
    pc = cfg.get("power", {})
    key = DigitalInputDevice(pc["key_gpio"], pull_up=True) if pc.get("enabled") else None
    lights = {n: DigitalInputDevice(sc["gpio"], pull_up=True) for n, sc in light_inputs(cfg).items()} \
        if cfg.get("lights", {}).get("enabled") else {}
    vc = cfg["voltage"]
    print("Raw readings (Ctrl-C to stop)")
    try:
        while True:
            chans = []
            for ch in range(4):
                try:
                    chans.append(f"A{ch}={adc.read_volts(ch):6.3f}V")
                except OSError:
                    chans.append(f"A{ch}=  ERR  ")
            try:
                batt = adc.read_volts(vc["adc_channel"]) * vc["divider_ratio"]
                batt_txt = f"{batt:5.2f}V"
            except OSError:
                batt_txt = "  ERR"
            sw = " ".join(f"{n}={'ON ' if d.is_active else 'off'}" for n, d in switches.items())
            for n, wc in monitored.items():
                try:
                    v = adc.read_volts(wc["adc_channel"])
                    state = {True: "ON", False: "ok", None: "WIRE OPEN"}[classify_monitored(v, wc)]
                    sw += f" {n}={v:.2f}V {state}"
                except OSError:
                    sw += f" {n}=ERR"
            if key is not None:
                sw += f" key={'ON' if key.is_active else 'OFF'}"
            for n, dev in lights.items():
                sw += f" {n}={'ON' if dev.is_active else 'off'}"
            print(f"{' '.join(chans)} | battery~{batt_txt} | rpm={tach.rpm():6.0f} | {sw}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass

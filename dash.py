#!/usr/bin/env python3
"""Digital dash for a 1978 Bobcat skid steer, for Raspberry Pi with pygame.

  python3 dash.py                    real sensors, fullscreen (on the Pi)
  python3 dash.py --sim --windowed   fake engine, in a window (any computer)
  python3 dash.py --calibrate        print raw sensor readings for setup
  python3 dash.py --boot-splash      save the splash screen (picture + version) for the Pi's boot
  python3 dash.py --version          print the software version

Esc or Q quits when a keyboard is plugged in.
"""
import argparse
import logging
import math
import os
import time

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

import pygame
import pygame.gfxdraw

from audio import Alerts
from cooldown import COOLING, DONE, IDLE_NEEDED, CoolDown
from hourmeter import HourMeter, set_hours_cli
from pihealth import PiHealth
from starter import StarterGuard
from tilt import TiltSensor, TiltStatus, zero_cli
from power import COUNTDOWN, ON, SHUTDOWN, PowerManager
from sensors import calibrate, light_inputs, make_sensors
from version import BUILD_DATE, VERSION

log = logging.getLogger("dash")

BG = (8, 11, 16)
HEADER = (16, 20, 27)
PANEL = (22, 27, 35)
TRACK = (48, 55, 66)
TEXT = (236, 239, 244)
DIM = (150, 158, 170)
GREEN = (34, 197, 94)
AMBER = (245, 166, 35)
RED = (239, 68, 68)
RED_DARK = (110, 14, 14)
GRAY = (95, 103, 115)

OK, WARN, ALARM, UNKNOWN, IDLE = "ok", "warn", "alarm", "unknown", "idle"
STARTING = "starting"   # amber like a warning, but expected: no beep, no horn, not counted in the header
COLOR = {OK: GREEN, WARN: AMBER, ALARM: RED, UNKNOWN: GRAY, IDLE: DIM, STARTING: AMBER}
TILE_BG = {OK: (10, 60, 32), WARN: (90, 58, 8), ALARM: RED, UNKNOWN: (38, 42, 50), IDLE: (38, 42, 50),
           STARTING: (90, 58, 8)}

# Layout is drawn on a 1024x768 grid and scaled to whatever the screen is.
DESIGN_W, DESIGN_H = 1024, 768


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


# ---------------------------------------------------------------- status logic

def voltage_limits(cfg, running):
    """The battery thresholds that apply right now. The status and the colour
    bar both come from here, so they always agree."""
    return cfg["voltage"]["engine_running" if running else "engine_off"]


def voltage_zones(lim, lo, hi):
    """Colour bands for the battery bar: [(from_volts, to_volts, colour), ...]."""
    return [(lo, lim["red_low"], RED), (lim["red_low"], lim["amber_low"], AMBER),
            (lim["amber_low"], lim["amber_high"], GREEN), (lim["amber_high"], lim["red_high"], AMBER),
            (lim["red_high"], hi, RED)]


def evaluate(r, cfg, running_for=None, tach_fault_latched=False, low_for=0.0, just_stopped=False, dip_for=None,
             crank_ago=None):
    """Turn raw readings into (state, text) pairs for every gauge and light.
    running_for: seconds since the engine started (None if not known).
    tach_fault_latched: the previous call reported st["tach_fault"] (see main).
    low_for: seconds the rpm has been in the low-idle band (see low_idle_band).
    just_stopped: the engine stopped a moment ago (its rpm falling through the cranking band isn't a start).
    dip_for: seconds since the battery suddenly fell below its engine-off low limit (None = it didn't).
    crank_ago: seconds since cranking was last seen (None = not recently)."""
    vc, fc, tc = cfg["voltage"], cfg["fuel"], cfg["tach"]
    volts, rpm, fuel = r["volts"], r["rpm"], r["fuel_pct"]

    # Is the engine running? The tach decides. If it reads 0 rpm but the
    # battery is at charging voltage, either a charger is connected (engine
    # off) or the tach has failed (engine running). The oil pressure switch
    # tells them apart: a running engine has oil pressure, a parked one doesn't.
    #
    # Once a dead tach has been seen on a running engine, it stays latched
    # until the voltage drops (engine stopped) or the tach reads again, so a
    # later loss of oil pressure is still a real alarm, not "parked + charger".
    charging = volts is not None and volts >= vc["charging_min"]
    tach_running = rpm is not None and rpm >= tc["running_rpm"]
    pressure = [r["warnings"].get(n) for n, wc in cfg["warnings"].items() if wc.get("ignore_when_engine_off")]
    has_pressure = bool(pressure) and all(p is False for p in pressure)
    no_pressure = bool(pressure) and any(p is True for p in pressure)

    tach_fault = False
    if tach_running:
        running, off = True, False
    elif rpm is not None and not charging:
        running, off = False, True
    elif charging and has_pressure:                       # running on a dead tach
        running, off, tach_fault = True, False, True
    elif charging and no_pressure and tach_fault_latched:  # dead tach, then oil pressure lost
        running, off, tach_fault = True, False, True
    elif charging and no_pressure:                        # parked with a battery charger
        running, off = False, True
    else:                                                 # can't tell (no tach or no oil switch signal)
        running, off = False, False
    uncertain = not running and not off

    # Cranking: the starter is turning the engine (the coil fires, so the tach reads ~150-300 rpm) but it
    # hasn't caught yet. The battery sags to ~10 V under the starter: that's expected, not an alarm.
    cranking = (rpm is not None and tc.get("cranking_rpm", 80) <= rpm < tc["running_rpm"] and not just_stopped)
    st = {"running": running, "off": off, "uncertain": uncertain, "tach_fault": tach_fault, "cranking": cranking}

    lim = voltage_limits(cfg, running)
    low_text = "NOT CHARGING" if running else "LOW"
    if volts is None:
        st["volts"] = (UNKNOWN, "NO SIGNAL")
    elif cranking:
        st["volts"] = (WARN, "WEAK CRANK") if volts < vc.get("crank_low", 9.6) else (STARTING, "CRANKING")
    elif not running and dip_for is not None and dip_for < vc.get("crank_detect", 1.5):
        # the starter has just engaged: the battery drops at once, but the tach needs a few sparks first
        st["volts"] = (STARTING, "CRANKING")
    elif (not running and crank_ago is not None and crank_ago < vc.get("crank_recover", 2.0)
          and volts < lim["amber_low"]):
        # the key was let go without a start: the battery takes a moment to come back up from ~10 V
        st["volts"] = (STARTING, "RECOVERING")
    elif volts < lim["red_low"]:
        st["volts"] = (ALARM, low_text)
    elif volts > lim["red_high"]:
        st["volts"] = (ALARM, "HIGH")
    elif volts > lim["amber_high"]:
        st["volts"] = (WARN, "HIGH")
    elif volts < lim["amber_low"]:
        st["volts"] = (WARN, low_text)
    else:
        st["volts"] = (OK, "CHARGING" if running or charging else "OK")
    # just caught: the battery is still recovering from the starter and the alternator is coming up
    if (running and running_for is not None and running_for < vc.get("start_grace", 10.0)
            and st["volts"][1] == low_text):
        st["volts"] = (STARTING, "STARTING UP")

    if rpm is None:
        st["rpm"] = (UNKNOWN, "NO SIGNAL")
    elif rpm >= tc["red_above"]:
        st["rpm"] = (ALARM, "OVERSPEED")
    elif rpm >= tc["amber_above"]:
        st["rpm"] = (WARN, "HIGH")
    elif uncertain or tach_fault:
        st["rpm"] = (WARN, "CHECK SENSOR")   # 0 rpm, but the engine is (or may be) running
    elif (running and rpm < tc.get("low_idle_below", 0) and low_for >= tc.get("low_idle_seconds", 1.0)
          and running_for is not None and running_for >= tc.get("low_idle_after_start", 5.0)):
        st["rpm"] = (WARN, "LOW IDLE")       # idle sagging: a stall may be coming
    elif running:
        st["rpm"] = (OK, "RUNNING")
    elif cranking:
        st["rpm"] = (STARTING, "CRANKING")
    else:
        st["rpm"] = (IDLE, "ENGINE OFF")

    if fuel is None:
        st["fuel"] = (UNKNOWN, "NO SIGNAL")
    elif fuel <= fc["red_below"]:
        st["fuel"] = (ALARM, "LOW FUEL")
    elif fuel <= fc["amber_below"]:
        st["fuel"] = (WARN, "LOW")
    else:
        st["fuel"] = (OK, "OK")

    st["warnings"] = {}
    for name, wc in cfg["warnings"].items():
        active = r["warnings"].get(name)
        if active is None:
            st["warnings"][name] = (UNKNOWN, "NO SIGNAL")
        elif active and wc.get("ignore_when_engine_off") and off:
            st["warnings"][name] = (IDLE, "ENGINE OFF")
        elif active and wc.get("ignore_when_engine_off") and uncertain:
            st["warnings"][name] = (WARN, wc["alarm_text"] + "?")   # can't tell if the engine is running
        elif active and running and running_for is not None and running_for < wc.get("start_delay", 0):
            st["warnings"][name] = (STARTING, "BUILDING")   # oil pressure still coming up
        elif active:
            st["warnings"][name] = (ALARM, wc["alarm_text"])
        else:
            st["warnings"][name] = (OK, wc["ok_text"])
    return st


def low_idle_band(rpm, cfg):
    """Running, but below the low-idle line (main times how long it stays there)."""
    tc = cfg["tach"]
    return rpm is not None and tc["running_rpm"] <= rpm < tc.get("low_idle_below", 0)


class Splash:
    """Start-up picture (splash/splash.png): shown for [splash] seconds, then fades into the dash.
    Fitted to whatever screen it's on, so any picture size works; tools/fit_splash.py makes one
    at the screen's exact size, which also suits the Pi's boot splash."""

    def __init__(self, screen, cfg, base_dir):
        self.screen, self.cfg, self.base_dir = screen, cfg, base_dir
        self.extra = 0.0            # simulator: extra time standing in for the Pi's own boot splash
        self.load()

    def load(self):
        """(Re)load the picture. The simulator calls this at every simulated boot, so a new
        splash picture shows up without restarting it.
        With a caption (the default), the bottom of the screen is kept for two lines of text,
        "Bobcat Custom Display" and the version + build date, and the picture fits above them."""
        screen, cfg, base_dir = self.screen, self.cfg, self.base_dir
        sc = cfg.get("splash", {})
        self.seconds = sc.get("seconds", 3.0) if sc.get("enabled", True) else 0.0
        self.fade = sc.get("fade_seconds", 0.6)
        self.surface = None
        path = os.path.join(base_dir, sc.get("file", "splash/splash.png"))
        if self.seconds <= 0:
            return
        try:
            img = pygame.image.load(path).convert_alpha()
        except (pygame.error, FileNotFoundError) as e:
            log.info("no splash picture (%s): starting straight into the dash", e)
            self.seconds = 0.0
            return
        W, H = screen.get_size()
        k = min(W / DESIGN_W, H / DESIGN_H)
        title = sc.get("caption", "Bobcat Custom Display")
        band = round(112 * k) if title else 0            # caption strip under the picture
        mode = sc.get("fit", "contain")
        scale = (max if mode == "cover" else min)(W / img.get_width(), (H - band) / img.get_height())
        size = (max(1, round(img.get_width() * scale)), max(1, round(img.get_height() * scale)))
        img = pygame.transform.smoothscale(img, size)
        bg = sc.get("background", "auto")
        if bg == "auto":                                  # colour of the picture's own edge
            edge = [img.get_at((x, y)) for x in range(0, size[0], max(1, size[0] // 50)) for y in (0, size[1] - 1)]
            bg = tuple(sorted(c[i] for c in edge)[len(edge) // 2] for i in range(3))
        # A plain 24-bit surface with no alpha channel: on some displays (e.g. a macOS window) the
        # screen format has an alpha channel, and a surface copied from it came out fully transparent.
        self.surface = pygame.Surface((W, H), 0, 24)
        self.surface.fill(pygame.Color(bg) if isinstance(bg, str) else bg)
        self.surface.blit(img, ((W - size[0]) // 2, (H - band - size[1]) // 2))
        if title:
            bgc = self.surface.get_at((0, H - 1))
            light_bg = 0.299 * bgc[0] + 0.587 * bgc[1] + 0.114 * bgc[2] > 140
            fg, dim = ((20, 24, 30), (80, 88, 100)) if light_bg else (TEXT, DIM)
            f1, f2 = pygame.font.Font(None, round(46 * k)), pygame.font.Font(None, round(30 * k))
            t1 = f1.render(title, True, fg)
            t2 = f2.render(f"Version {VERSION}   \u00b7   Built {BUILD_DATE}", True, dim)
            y = H - band + (band - t1.get_height() - t2.get_height() - round(8 * k)) // 2
            self.surface.blit(t1, t1.get_rect(midtop=(W // 2, y)))
            self.surface.blit(t2, t2.get_rect(midtop=(W // 2, y + t1.get_height() + round(8 * k))))

    def hold(self):
        """How long the picture stays fully up (before the fade)."""
        return self.extra + self.seconds if self.surface else 0.0

    def total(self):
        return self.hold() + (self.fade if self.surface else 0.0)

    def draw(self, screen, elapsed):
        """Draw over the dash. Returns False once the splash is finished."""
        if self.surface is None or elapsed >= self.total():
            return False
        hold = self.hold()
        alpha = 255 if elapsed < hold else int(255 * (1 - (elapsed - hold) / self.fade))
        self.surface.set_alpha(alpha)
        screen.blit(self.surface, (0, 0))
        return True


def flat_states(st):
    """{source_name: state} for every gauge and warning light (and the Pi's own health warnings)."""
    out = {"volts": st["volts"][0], "rpm": st["rpm"][0], "fuel": st["fuel"][0]}
    out.update({name: s for name, (s, _) in st["warnings"].items()})
    out.update({src: WARN for src, _ in st.get("system", [])})
    if st.get("tilt"):
        out["tilt"] = st["tilt"]["state"]
    return out


# ---------------------------------------------------------------- drawing

class Dash:
    def __init__(self, screen, cfg):
        self.screen = screen
        self.cfg = cfg
        w, h = screen.get_size()
        self.sx, self.sy = w / DESIGN_W, h / DESIGN_H
        self.k = min(self.sx, self.sy)
        self._fonts = {}
        self.sim_text = None    # simulator status, shown in the header
        self.help = None        # [(key, description)] shown when show_help is on
        self.show_help = False
        self.muted = False      # alarms present but silenced by the operator
        self.hourmeter = None
        lc = cfg.get("lights", {})
        # "tiles": big FRONT / REAR / WORK tiles under half-height warning tiles. "icons": small symbols
        # in the RPM panel (the original layout). Simulator key J switches between them.
        self.light_style = lc.get("display", "icons") if lc.get("enabled") else "icons"
        self.tilt_on = cfg.get("tilt", {}).get("enabled", True)

    def R(self, x, y, w, h):
        return pygame.Rect(round(x * self.sx), round(y * self.sy), round(w * self.sx), round(h * self.sy))

    def px(self, n):
        return max(1, round(n * self.k))

    def font(self, size):
        size = max(8, round(size * self.k))
        if size not in self._fonts:
            self._fonts[size] = pygame.font.Font(None, size)
        return self._fonts[size]

    def text(self, s, size, color, max_w=None, **anchor):
        surf = self.font(size).render(s, True, color)
        while max_w and surf.get_width() > max_w and size > 12:
            size -= 4
            surf = self.font(size).render(s, True, color)
        rect = surf.get_rect(**anchor)
        self.screen.blit(surf, rect)
        return rect

    def pill(self, s, size, color, **anchor):
        fg = BG if color in (GREEN, AMBER, DIM) else TEXT
        surf = self.font(size).render(s, True, fg)
        rect = surf.get_rect().inflate(self.px(30), self.px(14))
        for key, value in anchor.items():
            setattr(rect, key, value)
        pygame.draw.rect(self.screen, color, rect, border_radius=rect.h // 2)
        self.screen.blit(surf, surf.get_rect(center=rect.center))
        return rect

    def panel(self, rect, title):
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=self.px(14))
        self.text(title, 34, DIM, topleft=(rect.x + self.px(20), rect.y + self.px(16)))

    def arc_band(self, color, center, r_in, r_out, a0, a1):
        """Filled ring segment between angles a0 and a1 (degrees, 0 = right, CCW positive)."""
        if abs(a1 - a0) < 0.3:
            return
        n = max(2, int(abs(a1 - a0) / 2) + 1)
        cx, cy = center
        angles = [math.radians(a0 + (a1 - a0) * i / (n - 1)) for i in range(n)]
        pts = [(round(cx + r_out * math.cos(a)), round(cy - r_out * math.sin(a))) for a in angles]
        pts += [(round(cx + r_in * math.cos(a)), round(cy - r_in * math.sin(a))) for a in reversed(angles)]
        pygame.gfxdraw.aapolygon(self.screen, pts, color)
        pygame.gfxdraw.filled_polygon(self.screen, pts, color)

    # -- whole screen

    def draw(self, r, st, now, lamp_test):
        flash = int(now * 4) % 2 == 0  # 2 Hz blink for alarms
        self.screen.fill(BG)
        self.draw_header(st, lamp_test, flash)
        tiles = self.light_style == "tiles" and self.cfg.get("lights", {}).get("enabled")
        if self.tilt_on:        # machine angle panel: battery + fuel share one panel, warning tiles shorter
            self.draw_tach(self.R(12, 66, 492, 500), r["rpm"], *st["rpm"], note=st.get("cooldown"))
            self.draw_batt_fuel(self.R(516, 66, 496, 184), r, st)
            self.draw_tilt(self.R(516, 262, 496, 304), st.get("tilt"), flash, lamp_test)
            wy, wh = 578, 178
        else:                   # the original layout
            self.draw_tach(self.R(12, 66, 492, 420), r["rpm"], *st["rpm"], note=st.get("cooldown"))
            self.draw_volts(self.R(516, 66, 496, 204), r["volts"], *st["volts"], st["running"])
            self.draw_fuel(self.R(516, 282, 496, 204), r["fuel_pct"], *st["fuel"])
            wy, wh = 498, 258
        if not tiles:
            self.draw_lights(r.get("lights") or {}, lamp_test)

        names = list(self.cfg["warnings"])
        gap = 16
        tile_w = (1000 - gap * (len(names) - 1)) / len(names)
        th = (wh - 10) * 0.5 if tiles else wh
        for i, name in enumerate(names):
            rect = self.R(12 + i * (tile_w + gap), wy, tile_w, th)
            self.draw_warning(rect, self.cfg["warnings"][name]["label"], *st["warnings"][name], flash, design_h=th)
        if tiles:
            self.draw_light_tiles(r.get("lights") or {}, lamp_test, top=wy + th + 10, height=wh - th - 10)

        if self.show_help and self.help:
            self.draw_help()

    def draw_power(self, state, remaining, error, sim, lights_on=()):
        """Key-off overlay: countdown, then 'shutting down' (or a blank 'power off' in the simulator)."""
        if state == SHUTDOWN and sim:
            self.screen.fill((0, 0, 0))
            c = self.R(0, 0, DESIGN_W, DESIGN_H).center
            self.text("KEY OFF - POWER OFF (simulated)", 44, DIM, center=(c[0], c[1] - self.px(24)))
            self.text("Press K to turn the key on: the Pi boots (splash picture), then the dash starts",
                      26, TRACK, center=(c[0], c[1] + self.px(28)))
            return
        shade = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 170))
        self.screen.blit(shade, (0, 0))
        box = self.R(212, 244 - (40 if lights_on else 0), 600, 280 + (80 if lights_on else 0))
        pygame.draw.rect(self.screen, BG, box, border_radius=self.px(14))
        pygame.draw.rect(self.screen, AMBER if state == COUNTDOWN else DIM, box, width=self.px(3), border_radius=self.px(14))
        cx = box.centerx
        if state == COUNTDOWN:
            self.text("KEY OFF", 52, AMBER, midtop=(cx, box.y + self.px(28)))
            self.text(f"Shutting down in {max(1, math.ceil(remaining))}", 40, TEXT, center=(cx, box.centery + self.px(6)))
            self.text("Turn the key back on to cancel", 28, DIM, midbottom=(cx, box.bottom - self.px(28)))
        else:
            self.text("SHUTTING DOWN", 52, TEXT, midtop=(cx, box.y + self.px(28)))
            self.text(f"Engine hours saved: {self.hourmeter.display()}", 32, GREEN, center=(cx, box.centery + self.px(6)))
            if error:
                self.text("Power-off command failed. The board", 26, AMBER, midbottom=(cx, box.bottom - self.px(52)))
                self.text("timer turns the power off within 3 minutes.", 26, AMBER, midbottom=(cx, box.bottom - self.px(24)))
            else:
                self.text("The power turns off by itself", 28, DIM, midbottom=(cx, box.bottom - self.px(28)))
        if lights_on:                   # drawn last, on top of the box
            self.text("LIGHTS STILL ON: " + ", ".join(lights_on), 32, AMBER,
                      center=(cx, box.bottom - self.px(108)))

    # ---- light tell-tales (board rev 2.1): top-right corner of the RPM panel, only while a light is on

    LIGHT_COLOR = {"front": GREEN, "rear": GREEN, "work": AMBER}

    def draw_lights(self, lights, lamp_test):
        lc = self.cfg.get("lights", {})
        if not lc.get("enabled"):
            return
        inputs = light_inputs(self.cfg)
        slot = 60
        x = 504 - 14 - slot * len(inputs)                 # right-aligned in the RPM panel (design units)
        for name, sc in inputs.items():
            if lights.get(name) or lamp_test:
                color = self.LIGHT_COLOR.get(name, GREEN)
                box = self.R(x + 8, 76, 44, 26)
                {"front": self._icon_front, "rear": self._icon_rear}.get(name, self._icon_work)(box, color)
                self.text(sc.get("label", name.upper()), 15, color, midtop=(box.centerx, box.bottom + self.px(3)))
            x += slot

    def _lamp(self, box, color, facing, lw=3):
        """A 'D' lamp: flat side toward the beams, round side away (ISO tell-tale style)."""
        w = self.px(lw)
        lamp = pygame.Rect(box.x + box.w * 0.48, box.y + 1, box.w * 0.52, box.h - 2) if facing == "left" else \
            pygame.Rect(box.x, box.y + 1, box.w * 0.52, box.h - 2)
        old = self.screen.get_clip()
        self.screen.set_clip(lamp.inflate(2, 2))
        oval = pygame.Rect(lamp.x - (lamp.w if facing == "left" else 0), lamp.y, lamp.w * 2, lamp.h)
        pygame.draw.ellipse(self.screen, color, oval, w)
        self.screen.set_clip(old)
        flat_x = lamp.x if facing == "left" else lamp.right - 1
        pygame.draw.line(self.screen, color, (flat_x, lamp.y), (flat_x, lamp.bottom - 1), w)
        return lamp

    def _icon_front(self, box, color, lw=3):
        """Headlamp: lamp on the right, straight beams to the left."""
        lamp = self._lamp(box, color, "left", lw)
        for i in range(4):
            y = box.y + box.h * (0.2 + 0.2 * i)
            pygame.draw.line(self.screen, color, (box.x, y), (lamp.x - self.px(4), y), self.px(lw))

    def _icon_rear(self, box, color, lw=3):
        """Tail lamp: lamp on the left, short rays to the right."""
        lamp = self._lamp(box, color, "right", lw)
        cy = box.centery
        for dy in (-0.32, 0.0, 0.32):
            y0 = cy + box.h * dy * 0.6
            pygame.draw.line(self.screen, color, (lamp.right + self.px(4), y0),
                             (box.right, cy + box.h * dy * 1.2), self.px(lw))

    def _icon_work(self, box, color, lw=3):
        """Work light: a floodlight head on a bracket, rays fanning out."""
        w = self.px(lw)
        head = [(box.x + box.w * 0.08, box.y + box.h * 0.12), (box.x + box.w * 0.42, box.y + box.h * 0.02),
                (box.x + box.w * 0.42, box.y + box.h * 0.98), (box.x + box.w * 0.08, box.y + box.h * 0.82)]
        pygame.draw.polygon(self.screen, color, head, w)
        pygame.draw.line(self.screen, color, (box.x + box.w * 0.25, box.y + box.h * 0.9),
                         (box.x + box.w * 0.25, box.bottom + self.px(2)), w)          # bracket
        sx = box.x + box.w * 0.5
        for dy0, dy1 in ((0.2, 0.0), (0.5, 0.5), (0.8, 1.0)):
            pygame.draw.line(self.screen, color, (sx, box.y + box.h * dy0), (box.right, box.y + box.h * dy1), w)

    def draw_help(self):
        box = self.R(112, 100, 800, 580)
        pygame.draw.rect(self.screen, BG, box, border_radius=self.px(14))
        pygame.draw.rect(self.screen, AMBER, box, width=self.px(3), border_radius=self.px(14))
        self.text("SIMULATOR KEYS", 40, AMBER, midtop=(box.centerx, box.y + self.px(20)))
        y = box.y + self.px(72)
        row = (box.h - self.px(90)) / len(self.help)
        size = 30 if len(self.help) <= 21 else 26
        for key, desc in self.help:
            self.text(key, size, TEXT, midleft=(box.x + self.px(36), y + row / 2))
            self.text(desc, size, DIM, midleft=(box.x + self.px(220), y + row / 2))
            y += row

    def draw_header(self, st, lamp_test, flash):
        rect = self.R(0, 0, DESIGN_W, 56)
        pygame.draw.rect(self.screen, HEADER, rect)
        logo = self.text("BOBCAT", 44, TEXT, midleft=(rect.x + self.px(20), rect.centery))
        left_edge = logo.right
        if self.sim_text:
            left_edge = self.text(self.sim_text, 24, AMBER, max_w=self.px(250),
                                  midleft=(logo.right + self.px(14), rect.centery)).right

        # the Pi's own warnings sit left of the status pill; the engine text moves left to make room
        free_right = rect.right - self.px(170)
        if not lamp_test:
            for _, label in reversed(st.get("system", [])):
                free_right = self.pill(label, 26, AMBER, midright=(free_right, rect.centery)).left - self.px(10)
        words, color = (("ENGINE RUNNING", GREEN) if st["running"] else st["header_note"] if st.get("header_note") else
                        ("CRANKING", AMBER) if st.get("cranking") else
                        ("ENGINE OFF", DIM) if st["off"] else ("ENGINE ?", AMBER))
        half = self.font(38).size(words)[0] / 2
        cx = min(rect.centerx, free_right - self.px(14) - half)
        cx = max(cx, left_edge + self.px(14) + half)              # never under the logo / simulator text
        self.text(words, 38, color, max_w=int(free_right - left_edge - self.px(28)), center=(cx, rect.centery))

        states = [st["volts"][0], st["rpm"][0], st["fuel"][0]] + [s for s, _ in st["warnings"].values()]
        states += [WARN for _ in st.get("system", [])]
        if st.get("tilt"):
            states.append(st["tilt"]["state"])
        alarms, warns = states.count(ALARM), states.count(WARN) + states.count(UNKNOWN)
        right = (rect.right - self.px(16), rect.centery)
        if lamp_test:
            self.pill("LAMP TEST", 34, AMBER, midright=right)
        elif alarms:
            text = f"{alarms} ALARM{'S' if alarms > 1 else ''}"
            if self.muted:
                self.pill(text + " - SILENCED", 34, RED, midright=right)
            else:
                self.pill(text, 34, RED if flash else RED_DARK, midright=right)
        elif warns:
            self.pill(f"CHECK {warns}", 34, AMBER, midright=right)
        else:
            self.pill("ALL OK", 34, GREEN, midright=right)

    def draw_tach(self, rect, rpm, state, label, note=None):
        """note: (text, colour) shown in the status pill instead of plain RUNNING (the cool-down)."""
        tc = self.cfg["tach"]
        top = tc["max_rpm"]
        self.panel(rect, "ENGINE RPM")

        r = rect.h * 0.42
        cx, cy = rect.centerx, rect.y + rect.h * 0.54
        start, sweep = 210, 240

        def ang(v):
            return start - sweep * max(0.0, min(1.0, v / top))

        low = tc.get("low_idle_below", 0)
        run = tc["running_rpm"]
        zones = [(0, run, TRACK)] + ([(run, low, AMBER)] if low > run else []) + [
            (max(low, run), tc["amber_above"], GREEN), (tc["amber_above"], tc["red_above"], AMBER), (tc["red_above"], top, RED)]
        for a, b, color in zones:
            self.arc_band(color, (cx, cy), r * 0.95, r, ang(a), ang(b))
        self.arc_band(TRACK, (cx, cy), r * 0.76, r * 0.91, ang(0), ang(top))
        if rpm:
            self.arc_band(COLOR[state], (cx, cy), r * 0.76, r * 0.91, ang(0), ang(rpm))

        for v in range(0, top + 1, 250):
            major = v % 500 == 0
            a = math.radians(ang(v))
            r0, r1 = (r * 0.62, r * 0.72) if major else (r * 0.67, r * 0.72)
            p0 = (cx + r0 * math.cos(a), cy - r0 * math.sin(a))
            p1 = (cx + r1 * math.cos(a), cy - r1 * math.sin(a))
            pygame.draw.line(self.screen, TEXT if major else DIM, p0, p1, self.px(3 if major else 2))
            if major:
                rl = r * 0.55
                self.text(str(v // 100), 30, DIM, center=(cx + rl * math.cos(a), cy - rl * math.sin(a)))

        digits = "----" if rpm is None else f"{rpm:.0f}"
        color = TEXT if state in (OK, IDLE) else COLOR[state]
        self.text(digits, 96, color, center=(cx, cy + r * 0.02))
        self.text("x100 RPM", 26, DIM, center=(cx, cy + r * 0.36))
        if note and state == OK:
            self.pill(note[0], 34, note[1], center=(cx, cy + r * 0.62))
        else:
            self.pill(label, 34, COLOR[state], center=(cx, cy + r * 0.62))
        if self.hourmeter:
            self.draw_hours(rect.centerx, rect.bottom - self.px(30))
        # software version: bottom-left corner of the RPM panel, small and dim
        self.text(f"v{VERSION}", 21, GRAY, bottomleft=(rect.x + self.px(14), rect.bottom - self.px(10)))

    def draw_hours(self, cx, cy):
        """Hobbs-style counter: four white-on-black wheels, then the tenths wheel inverted."""
        hm = self.hourmeter
        text = hm.display()                       # "1234.5"
        digits = text.replace(".", "")
        w, h, gap = self.px(26), self.px(38), self.px(3)
        total = 5 * w + 4 * gap + self.px(10)     # 10 px for the decimal point
        x = cx - total / 2 + self.px(26)          # leave room for the label on the left
        self.text("HOURS" if hm.saves_ok else "HOURS NOT SAVED", 22, DIM if hm.saves_ok else AMBER,
                  midright=(x - self.px(12), cy))
        for i, ch in enumerate(digits):
            last = i == 4
            if last:
                x += self.px(10)                  # decimal point
                pygame.draw.circle(self.screen, TEXT, (round(x - self.px(6)), round(cy + h / 2 - self.px(5))), self.px(2))
            box = pygame.Rect(round(x), round(cy - h / 2), w, h)
            pygame.draw.rect(self.screen, TEXT if last else (4, 6, 9), box, border_radius=self.px(3))
            pygame.draw.rect(self.screen, TRACK, box, width=1, border_radius=self.px(3))
            if last:
                # The tenths wheel turns continuously, like a mechanical Hobbs meter: one digit
                # every 6 minutes, so you can see it creep while the engine runs.
                roll = hm.tenths_fraction() * h
                old_clip = self.screen.get_clip()
                self.screen.set_clip(box.inflate(-2, -2))
                self.text(ch, 40, BG, center=(box.centerx, box.centery - roll))
                self.text(str((int(ch) + 1) % 10), 40, BG, center=(box.centerx, box.centery + h - roll))
                self.screen.set_clip(old_clip)
            else:
                self.text(ch, 40, TEXT, center=box.center)
            x += w + gap
        # counting indicator: pulses while the engine is running, like a Hobbs meter's spinner
        on = hm.running and int(time.monotonic() * 2) % 2 == 0
        pygame.draw.circle(self.screen, GREEN if on else TRACK, (round(x + self.px(10)), round(cy)), self.px(6))

    def _bar_labels(self, bar, items):
        for frac, s in items:
            self.text(s, 26, DIM, midtop=(bar.x + bar.w * frac, bar.bottom + self.px(6)))

    def draw_volts(self, rect, v, state, label, running):
        vc = self.cfg["voltage"]
        lim = voltage_limits(self.cfg, running)
        lo, hi = vc["bar_min"], vc["bar_max"]
        self.panel(rect, "BATTERY / CHARGING")
        self.text("RUNNING LIMITS" if running else "ENGINE-OFF LIMITS", 24, DIM,
                  topright=(rect.right - self.px(20), rect.y + self.px(20)))

        value = self.text("--.-" if v is None else f"{v:.1f}", 130, COLOR[state],
                          midleft=(rect.x + self.px(22), rect.y + rect.h * 0.48))
        self.text("V", 64, DIM, bottomleft=(value.right + self.px(8), value.bottom - self.px(8)))
        self.pill(label, 36, COLOR[state], midright=(rect.right - self.px(22), value.centery))

        bar = pygame.Rect(rect.x + self.px(24), rect.bottom - self.px(58), rect.w - self.px(48), self.px(14))

        def x(volts):
            return bar.x + bar.w * (max(lo, min(hi, volts)) - lo) / (hi - lo)

        for a, b, color in voltage_zones(lim, lo, hi):
            seg = pygame.Rect(round(x(a)), bar.y, max(0, round(x(b) - x(a))), bar.h)
            pygame.draw.rect(self.screen, mix(PANEL, color, 0.75), seg)
        if v is not None:
            mx = x(v)
            pygame.draw.line(self.screen, TEXT, (mx, bar.y - self.px(6)), (mx, bar.bottom + self.px(2)), self.px(4))
            t = self.px(9)
            pygame.draw.polygon(self.screen, TEXT, [(mx - t, bar.y - self.px(16)), (mx + t, bar.y - self.px(16)), (mx, bar.y - self.px(4))])
        steps = int(hi - lo)
        self._bar_labels(bar, [(i / steps, f"{lo + i:.0f}") for i in range(steps + 1)])

    def draw_fuel(self, rect, pct, state, label):
        self.panel(rect, "FUEL")

        value = self.text("--" if pct is None else f"{pct:.0f}", 130, COLOR[state],
                          midleft=(rect.x + self.px(22), rect.y + rect.h * 0.48))
        self.text("%", 64, DIM, bottomleft=(value.right + self.px(8), value.bottom - self.px(8)))
        self.pill(label, 36, COLOR[state], midright=(rect.right - self.px(22), value.centery))

        bar = pygame.Rect(rect.x + self.px(24), rect.bottom - self.px(64), rect.w - self.px(48), self.px(24))
        radius = self.px(6)
        pygame.draw.rect(self.screen, TRACK, bar, border_radius=radius)
        if pct:
            fill = bar.copy()
            fill.w = max(radius * 2, round(bar.w * pct / 100))
            pygame.draw.rect(self.screen, COLOR[state], fill, border_radius=radius)
        for q in (0.25, 0.5, 0.75):
            qx = bar.x + bar.w * q
            pygame.draw.line(self.screen, PANEL, (qx, bar.y), (qx, bar.bottom - 1), self.px(3))
        self._bar_labels(bar, [(0, "E"), (0.25, "1/4"), (0.5, "1/2"), (0.75, "3/4"), (1, "F")])

    def draw_batt_fuel(self, rect, r, st):
        """Battery and fuel side by side in one panel (used when the machine angle panel is on)."""
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=self.px(14))
        half = rect.w // 2
        pygame.draw.line(self.screen, TRACK, (rect.x + half, rect.y + self.px(14)), (rect.x + half, rect.bottom - self.px(14)), self.px(2))
        vc = self.cfg["voltage"]
        for i in range(2):
            col = pygame.Rect(rect.x + i * half, rect.y, half, rect.h)
            x0 = col.x + self.px(18)
            if i == 0:
                v, (state, label) = r["volts"], st["volts"]
                self.text("BATTERY", 26, DIM, topleft=(x0, col.y + self.px(12)))
                self.text("RUNNING" if st["running"] else "ENGINE OFF", 18, DIM,
                          topright=(col.right - self.px(16), col.y + self.px(16)))
                val = self.text("--.-" if v is None else f"{v:.1f}", 80, COLOR[state], midleft=(x0, col.y + self.px(72)))
                self.text("V", 40, DIM, bottomleft=(val.right + self.px(6), val.bottom - self.px(6)))
            else:
                v, (state, label) = r["fuel_pct"], st["fuel"]
                self.text("FUEL", 26, DIM, topleft=(x0, col.y + self.px(12)))
                val = self.text("--" if v is None else f"{v:.0f}", 80, COLOR[state], midleft=(x0, col.y + self.px(72)))
                self.text("%", 40, DIM, bottomleft=(val.right + self.px(6), val.bottom - self.px(6)))
            self.pill(label, 24, COLOR[state], midleft=(x0, col.y + self.px(120)))
            bar = pygame.Rect(x0, col.bottom - self.px(40), col.w - self.px(36), self.px(10))
            if i == 0:
                lo, hi = vc["bar_min"], vc["bar_max"]
                lim = voltage_limits(self.cfg, st["running"])

                def x(volts):
                    return bar.x + bar.w * (max(lo, min(hi, volts)) - lo) / (hi - lo)
                for a, b, color in voltage_zones(lim, lo, hi):
                    pygame.draw.rect(self.screen, mix(PANEL, color, 0.75),
                                     pygame.Rect(round(x(a)), bar.y, max(0, round(x(b) - x(a))), bar.h))
                if v is not None:
                    mx = x(v)
                    pygame.draw.line(self.screen, TEXT, (mx, bar.y - self.px(6)), (mx, bar.bottom + self.px(2)), self.px(4))
                ends = [(0, f"{lo:.0f}"), (0.5, f"{(lo + hi) / 2:.0f}"), (1, f"{hi:.0f} V")]
            else:
                pygame.draw.rect(self.screen, TRACK, bar, border_radius=self.px(4))
                if v:
                    fill = bar.copy()
                    fill.w = max(self.px(8), round(bar.w * v / 100))
                    pygame.draw.rect(self.screen, COLOR[state], fill, border_radius=self.px(4))
                for q in (0.25, 0.5, 0.75):
                    qx = bar.x + bar.w * q
                    pygame.draw.line(self.screen, PANEL, (qx, bar.y), (qx, bar.bottom - 1), self.px(2))
                ends = [(0, "E"), (0.5, "1/2"), (1, "F")]
            for frac, s in ends:
                self.text(s, 20, DIM, midtop=(bar.x + bar.w * frac, bar.bottom + self.px(4)))

    # skid steer outlines (design units, origin at the middle of the ground contact, y up = negative)
    REAR_VIEW = {
        "tyres": [[(-64, 0), (-40, 0), (-40, -42), (-64, -42)], [(40, 0), (64, 0), (64, -42), (40, -42)]],
        "body": [(-46, -10), (46, -10), (46, -50), (-46, -50)],
        "cab": [(-36, -50), (36, -50), (30, -104), (-30, -104)],
        "window": [(-23, -60), (23, -60), (19, -94), (-19, -94)],
        "arms": [[(-52, -40), (-44, -40), (-44, -100), (-52, -100)], [(44, -40), (52, -40), (52, -100), (44, -100)]],
    }
    SIDE_VIEW = {
        "wheels": [(-32, -18, 18), (32, -18, 18)],
        "body": [(-56, -14), (52, -14), (52, -46), (-56, -46)],
        "cab": [(-30, -46), (26, -46), (20, -100), (-26, -100)],
        "window": [(-18, -56), (16, -56), (12, -90), (-15, -90)],
        "engine": [(-56, -46), (-34, -46), (-34, -66), (-56, -66)],
        "arm": [(-42, -90), (-37, -94), (58, -49), (55, -44)],
        "bucket": [(52, -52), (76, -52), (82, -4), (56, -2), (50, -20)],
    }

    def _rot(self, pts, ang, origin, scale):
        """Rotate design points clockwise on screen by ang degrees about the ground point, then place them."""
        c, s_ = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        ox, oy = origin
        return [(ox + (x * c - y * s_) * scale, oy + (x * s_ + y * c) * scale) for x, y in pts]

    def _machine(self, kind, ang, origin, scale, color):
        w = max(1, self.px(3))
        fill = mix(PANEL, color, 0.18)
        if kind == "rear":
            v = self.REAR_VIEW
            for t in v["tyres"]:
                pygame.draw.polygon(self.screen, color, self._rot(t, ang, origin, scale))
            for poly in (v["body"], v["cab"]):
                pts = self._rot(poly, ang, origin, scale)
                pygame.draw.polygon(self.screen, fill, pts)
                pygame.draw.polygon(self.screen, color, pts, w)
            for a in v["arms"]:
                pygame.draw.polygon(self.screen, color, self._rot(a, ang, origin, scale))
            pygame.draw.polygon(self.screen, color, self._rot(v["window"], ang, origin, scale), w)
        else:
            v = self.SIDE_VIEW
            for poly in (v["body"], v["engine"], v["cab"]):
                pts = self._rot(poly, ang, origin, scale)
                pygame.draw.polygon(self.screen, fill, pts)
                pygame.draw.polygon(self.screen, color, pts, w)
            pygame.draw.polygon(self.screen, color, self._rot(v["window"], ang, origin, scale), w)
            pygame.draw.polygon(self.screen, color, self._rot(v["arm"], ang, origin, scale))
            pts = self._rot(v["bucket"], ang, origin, scale)
            pygame.draw.polygon(self.screen, fill, pts)
            pygame.draw.polygon(self.screen, color, pts, w)
            for x, y, rad in v["wheels"]:
                (cx, cy), = self._rot([(x, y)], ang, origin, scale)
                pygame.draw.circle(self.screen, color, (round(cx), round(cy)), round(rad * scale))
                pygame.draw.circle(self.screen, PANEL, (round(cx), round(cy)), round(rad * scale * 0.4))

    def draw_tilt(self, rect, t, flash, lamp_test):
        """MACHINE ANGLE: roll (rear view) and pitch (side view). The outlines tilt with the machine."""
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=self.px(14))
        self.text("MACHINE ANGLE", 26, DIM, topleft=(rect.x + self.px(18), rect.y + self.px(12)))
        tc = self.cfg.get("tilt", {})
        if lamp_test:
            t = {"state": ALARM, "text": "TEST", "roll": ALARM, "pitch": ALARM, "angles": (0.0, 0.0)}
        if t is None:
            return
        state = t["state"]
        pill_c = RED if state == ALARM and flash else RED_DARK if state == ALARM else COLOR[state]
        self.pill(t["text"], 24, pill_c, topright=(rect.right - self.px(14), rect.y + self.px(8)))
        half = rect.w // 2
        for i, (axis, kind, name) in enumerate([("roll", "rear", "ROLL"), ("pitch", "side", "PITCH")]):
            col = pygame.Rect(rect.x + i * half, rect.y, half, rect.h)
            ground = (col.centerx, col.y + self.px(186))
            scale = self.k * 0.95
            a_state = t[axis]
            color = {OK: TEXT, WARN: AMBER, ALARM: RED if flash else mix(RED, PANEL, 0.35), UNKNOWN: GRAY}[a_state]
            self.text(name, 22, DIM, midtop=(col.centerx, col.y + self.px(40)))
            # level reference (dashed) and the ground under the machine
            for k in range(-6, 6):
                x = col.centerx + k * self.px(16)
                pygame.draw.line(self.screen, TRACK, (x, ground[1]), (x + self.px(8), ground[1]), self.px(2))
            if t["angles"] is None:
                self._machine(kind, 0, ground, scale, GRAY)
                self.text("NO SIGNAL", 34, GRAY, midtop=(col.centerx, col.y + self.px(200)))
                continue
            ang = t["angles"][0] if axis == "roll" else -t["angles"][1]   # nose up turns the side view anticlockwise
            g = self._rot([(-96, 0), (96, 0)], ang, ground, scale)
            pygame.draw.line(self.screen, mix(PANEL, color, 0.6), g[0], g[1], self.px(4))
            self._machine(kind, ang, ground, scale, color)
            a = t["angles"][0 if axis == "roll" else 1]
            if abs(a) < 0.5:
                where = "LEVEL"
            elif axis == "roll":
                where = "RIGHT DOWN" if a > 0 else "LEFT DOWN"
            else:
                where = "NOSE UP" if a > 0 else "NOSE DOWN"
            num = self.text(f"{abs(a):.0f}\u00b0", 54, color if a_state != OK else TEXT,
                            midtop=(col.centerx - self.px(34), col.y + self.px(204)))
            self.text(where, 22, DIM, midleft=(num.right + self.px(10), num.centery))
            if axis == "roll":
                lims = f"limits {tc.get('roll_warn', 8):.0f}\u00b0 / {tc.get('roll_alarm', 15):.0f}\u00b0"
            else:
                lims = (f"up {tc.get('pitch_up_warn', 15):.0f}/{tc.get('pitch_up_alarm', 20):.0f}\u00b0   "
                        f"down {tc.get('pitch_down_warn', 20):.0f}/{tc.get('pitch_down_alarm', 25):.0f}\u00b0")
            self.text(lims, 18, DIM, midtop=(col.centerx, col.bottom - self.px(28)))

    def draw_warning(self, rect, label, state, status, flash, compact=False, design_h=258):
        bg = TILE_BG[state]
        if state == ALARM and not flash:
            bg = RED_DARK
        radius = self.px(16)
        pygame.draw.rect(self.screen, bg, rect, border_radius=radius)
        pygame.draw.rect(self.screen, COLOR[state], rect, width=self.px(4), border_radius=radius)
        color = {ALARM: TEXT, UNKNOWN: DIM}.get(state, COLOR[state])
        if compact or design_h < 140:   # short tile: label on one line
            self.text(label.replace("\n", " "), min(30, design_h * 0.27), TEXT, max_w=rect.w - self.px(24),
                      midtop=(rect.centerx, rect.y + self.px(min(12, design_h * 0.1))))
            self.text(status, min(70, design_h * 0.56), color, max_w=rect.w - self.px(28),
                      center=(rect.centerx, rect.y + rect.h * 0.64))
            return
        if design_h < 220:              # medium tile (machine angle panel shown)
            y = rect.y + self.px(14)
            for line in label.split("\n"):
                y = self.text(line, 34, TEXT, max_w=rect.w - self.px(24), midtop=(rect.centerx, y)).bottom + self.px(1)
            self.text(status, 80, color, max_w=rect.w - self.px(28), center=(rect.centerx, rect.y + rect.h * 0.71))
            return

        y = rect.y + self.px(22)
        for line in label.split("\n"):
            y = self.text(line, 44, TEXT, max_w=rect.w - self.px(24), midtop=(rect.centerx, y)).bottom + self.px(2)

        self.text(status, 104, color, max_w=rect.w - self.px(28), center=(rect.centerx, rect.y + rect.h * 0.68))

    def draw_light_tiles(self, lights, lamp_test, top, height):
        """FRONT / REAR / WORK as big tiles, always shown: dark when off, lit solid when on."""
        inputs = light_inputs(self.cfg)
        gap = 16
        w = (1000 - gap * (len(inputs) - 1)) / len(inputs)
        for i, (name, sc) in enumerate(inputs.items()):
            rect = self.R(12 + i * (w + gap), top, w, height)
            on = bool(lights.get(name)) or lamp_test
            lit = self.LIGHT_COLOR.get(name, GREEN)
            radius = self.px(16)
            pygame.draw.rect(self.screen, lit if on else PANEL, rect, border_radius=radius)
            pygame.draw.rect(self.screen, lit if on else TRACK, rect, width=self.px(4), border_radius=radius)
            ink = BG if on else GRAY
            box = pygame.Rect(0, 0, self.px(92), self.px(54))
            box.midleft = (rect.x + self.px(26), rect.centery)
            {"front": self._icon_front, "rear": self._icon_rear}.get(name, self._icon_work)(box, ink, lw=6)
            tx = box.right + (rect.right - box.right) // 2
            self.text(sc.get("label", name.upper()), 40, ink, max_w=rect.right - box.right - self.px(20),
                      center=(tx, rect.centery - self.px(20)))
            self.text("ON" if on else "OFF", 44 if on else 34, ink, center=(tx, rect.centery + self.px(22)))


# ---------------------------------------------------------------- main

def save_boot_splash(cfg, here, out):
    """The dash's own splash screen, saved as a picture at the display's size. Used as the Pi's boot
    splash (Plymouth), the boot and the dash's start show the same screen with no jump between them."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    d = cfg["display"]
    size = (d.get("width") or DESIGN_W, d.get("height") or DESIGN_H)
    pygame.init()
    screen = pygame.display.set_mode(size)
    splash = Splash(screen, cfg, here)
    if splash.surface is None:
        print("no splash picture found (or [splash] is disabled): nothing saved")
        return 1
    pygame.image.save(splash.surface, out)
    print(f"saved {out} ({size[0]}x{size[1]}, version {VERSION}, built {BUILD_DATE})")
    return 0


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Bobcat skid steer digital dash")
    ap.add_argument("--config", default=os.path.join(here, "config.toml"))
    ap.add_argument("--sim", action="store_true", help="simulated sensors (no hardware needed)")
    ap.add_argument("--windowed", action="store_true", help="run in a 1024x768 window")
    ap.add_argument("--calibrate", action="store_true", help="print raw sensor readings and exit")
    ap.add_argument("--version", action="version", version=f"Bobcat Custom Display {VERSION} (built {BUILD_DATE})")
    ap.add_argument("--boot-splash", nargs="?", const=os.path.join(here, "splash", "boot-splash.png"), metavar="PNG",
                    help="save the splash screen (picture + caption) at the display size, for the Pi's boot splash")
    ap.add_argument("--zero-tilt", action="store_true", help="park on level ground, then run this to zero the angle sensor")
    ap.add_argument("--force", action="store_true", help="with --zero-tilt: save even if it reads >5 deg off level or moving")
    ap.add_argument("--set-hours", type=float, metavar="HOURS",
                    help="change the engine hour meter total (asks for confirmation; the dash must be stopped)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with open(args.config, "rb") as f:
        cfg = tomllib.load(f)

    if args.set_hours is not None:
        raise SystemExit(set_hours_cli(cfg, args.set_hours, sim=args.sim))
    if args.calibrate:
        calibrate(cfg)
        return
    if args.zero_tilt:
        raise SystemExit(zero_cli(cfg, force=args.force))
    log.info("Bobcat Custom Display %s (built %s)", VERSION, BUILD_DATE)
    if args.boot_splash:
        raise SystemExit(save_boot_splash(cfg, here, args.boot_splash))

    d = cfg["display"]
    pygame.mixer.pre_init(44100, -16, 1, 1024)
    pygame.init()
    if args.windowed or not d["fullscreen"]:
        screen = pygame.display.set_mode((d["width"] or DESIGN_W, d["height"] or DESIGN_H))
    else:
        screen = pygame.display.set_mode((d["width"], d["height"]), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
    pygame.display.set_caption("Bobcat Dash")

    sensors = make_sensors(cfg, sim=args.sim)
    sensors.start()
    dash = Dash(screen, cfg)
    dash.help = getattr(sensors, "HELP", None)
    if dash.help:
        print("Simulator keys:\n" + "\n".join(f"  {k:<10} {v}" for k, v in dash.help))
    alerts = Alerts(cfg, sim=args.sim, base_dir=here)
    hourmeter = HourMeter(cfg, sim=args.sim)
    dash.hourmeter = hourmeter
    cooldown = CoolDown(cfg)
    health = PiHealth(cfg, sim=args.sim)
    starter = StarterGuard(cfg)
    tilt_status = TiltStatus(cfg)
    tilt_sensor = None if args.sim or not tilt_status.enabled else TiltSensor(cfg)
    power = PowerManager(cfg, sim=args.sim, start_off=args.sim)
    power_state = power.state           # the simulator starts as a parked machine: key off, powered down
    splash = Splash(screen, cfg, here)
    clock = pygame.time.Clock()
    boot = time.monotonic()             # splash first, then the lamp test starts at t0
    t0 = boot + splash.hold()
    if power_state == ON:
        alerts.startup_test(t0)
    chimed = False
    running_since = None
    stopped_at = -99.0
    dip_since, prev_volts = None, None
    last_crank = None
    tach_fault = False
    low_since = None

    try:
        while True:
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return
                if e.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                    alerts.silence()            # tap the screen to silence
                if e.type == pygame.KEYDOWN:
                    if e.key in (pygame.K_ESCAPE, pygame.K_q):
                        return
                    if e.key == pygame.K_h:
                        dash.show_help = not dash.show_help
                    elif e.key == pygame.K_p and args.sim:
                        hourmeter.add_sim_hours(10)
                    elif e.key == pygame.K_x and args.sim:
                        hourmeter.sim_speed = 1 if hourmeter.sim_speed > 1 else 60
                        cooldown.speed = hourmeter.sim_speed
                    elif e.key == pygame.K_m:
                        alerts.silence()
                    elif e.key in (pygame.K_i, pygame.K_u) and args.sim:
                        health.sim_key(pygame.key.name(e.key), time.monotonic())
                    elif e.key == pygame.K_j and args.sim:
                        dash.light_style = "icons" if dash.light_style == "tiles" else "tiles"
                    else:
                        sensors.handle_key(pygame.key.name(e.key))

            now = time.monotonic()
            readings = sensors.read()

            # key-off: save, then power off (board rev 2.0 power hold)
            was = power_state
            power_state = power.update(readings.get("key"), now, before_shutdown=hourmeter.save)
            if was == SHUTDOWN and power_state == ON:     # simulator: key on = the Pi "boots"
                splash.load()                             # pick up a new picture without restarting
                # on the machine the picture is up through the Pi's whole boot (Plymouth) and then
                # the dash's own [splash] seconds; the simulator stands in for the boot part
                splash.extra = cfg.get("splash", {}).get("sim_boot_seconds", 3.0)
                boot, chimed = now, False
                t0 = boot + splash.hold()
                alerts.startup_test(t0)
            if was == ON and power_state == COUNTDOWN:
                alerts.keyoff()                           # soft falling chime: the dash is shutting down
            lights_on = []
            pi_still_on = power_state == COUNTDOWN or (power_state == SHUTDOWN and not args.sim)
            if pi_still_on and cfg.get("lights", {}).get("left_on_warning", True):
                inputs = light_inputs(cfg)
                lights_on = [inputs[n].get("label", n.upper()) for n, on in (readings.get("lights") or {}).items() if on]
                if lights_on:
                    alerts.lights_reminder(now)
            if args.sim and power_state == SHUTDOWN:      # simulated power off: blank screen, silence
                alerts.update({}, now)
                hourmeter.update(False, now)
                dash.draw_power(power_state, 0, None, True)
                pygame.display.flip()
                clock.tick(d["fps"])
                continue

            running_for = now - running_since if running_since is not None else 0.0
            if not low_idle_band(readings["rpm"], cfg):
                low_since = None
            elif low_since is None:
                low_since = now
            v, low_v = readings["volts"], cfg["voltage"]["engine_off"]["amber_low"]
            if v is None or v >= low_v:
                dip_since = None
            elif prev_volts is not None and prev_volts >= low_v:      # a sudden drop, not a flat battery
                dip_since = now
            prev_volts = v
            st = evaluate(readings, cfg, running_for, tach_fault, now - low_since if low_since is not None else 0.0,
                          just_stopped=now - stopped_at < 3.0, dip_for=now - dip_since if dip_since is not None else None,
                          crank_ago=now - last_crank if last_crank is not None else None)
            if st["cranking"]:
                last_crank = now
            # starter guard: REST STARTER past the crank limit, then a cooling countdown
            guard, beep = starter.update(st["cranking"], st["running"], now)
            if guard and st["rpm"][0] in (IDLE, STARTING):
                kind, left = guard
                mmss = f"{int(math.ceil(left)) // 60}:{int(math.ceil(left)) % 60:02d}"
                st["rpm"] = {"over": (STARTING, "REST STARTER"), "rest": (STARTING, f"REST {mmss}"),
                             "ready": (OK, "READY TO START")}[kind]
                st["header_note"] = {"over": ("REST STARTER", AMBER), "rest": (f"STARTER COOLING {mmss}", AMBER),
                                     "ready": ("READY TO START", GREEN)}[kind]
            if beep and power_state == ON:
                alerts.notice()
            tach_fault = st["tach_fault"]
            cooldown.update(st["running"] and not st["tach_fault"], readings["rpm"], now)
            cd = cooldown.status(now, readings["rpm"])
            if cd and cd[0] == COOLING:
                left = math.ceil(cd[1])
                st["cooldown"] = (f"COOL DOWN {left // 60}:{left % 60:02d}", AMBER)
            elif cd and cd[0] == IDLE_NEEDED:
                st["cooldown"] = ("IDLE TO COOL DOWN", AMBER)
            elif cd and cd[0] == DONE:
                st["cooldown"] = ("OK TO SHUT DOWN", GREEN)
            if st["running"] and running_since is None:
                running_since = now
            elif not st["running"]:
                if running_since is not None:
                    stopped_at = now
                running_since = None

            st["system"] = health.status(now)
            st["tilt"] = tilt_status.update(readings.get("tilt") if args.sim else
                                            (tilt_sensor.angles() if tilt_sensor else None), now)
            lamp_test = now < t0 + d.get("lamp_test_seconds", 0)      # includes the splash time
            if lamp_test:
                alerts.update({}, now)          # only the test chirp
                st["warnings"] = {name: (ALARM, "TEST") for name in st["warnings"]}
            else:
                if not chimed and power_state == ON:     # not if the key's already off again
                    alerts.chime()              # system ready
                    chimed = True
                alerts.update(flat_states(st), now)
            hourmeter.update(st["running"], now)
            if power_state != ON:
                alerts.update({}, now)          # no horn or tones while shutting down
            dash.muted = alerts.muted
            if hasattr(sensors, "status"):
                dash.sim_text = (sensors.status() + ("  HORN" if alerts.horn_on else "")
                                 + ("  TIME x60" if hourmeter.sim_speed > 1 else ""))

            dash.draw(readings, st, now, lamp_test)
            splash.draw(screen, now - boot)
            if power_state != ON:
                dash.draw_power(power_state, power.remaining(now), power.error, args.sim, lights_on)
            pygame.display.flip()
            clock.tick(d["fps"])
    finally:
        if tilt_sensor:
            tilt_sensor.close()
        health.close()
        alerts.close()
        hourmeter.close()
        sensors.stop()
        pygame.quit()


if __name__ == "__main__":
    main()

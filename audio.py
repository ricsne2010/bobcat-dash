"""Startup chime, alert tones and the external alarm horn.

  * Speaker (through the Pi's audio output): startup chime, a two-tone alert
    while a red alarm is active, one short beep for a new amber warning, and a
    "connection lost" sound when a sensor stops answering (grey NO SIGNAL).
  * Horn (GPIO -> MOSFET or relay -> 12 V piezo alarm): pulses while a red
    alarm from horn.sources is active.
  * Silence button (GPIO), M key or a screen tap: silences the alarms that are
    on now. Any NEW alarm sounds again, and a silenced one re-arms once it clears.

Sounds are WAV files in sounds/ (paths set in config.toml [audio]). Swap in any
WAV you like. If a file is missing or unreadable, a built-in tone is used for it.
If the audio device is missing, the dash keeps running silently.
"""
import logging
import math
import os
from array import array

log = logging.getLogger("audio")

ALARM, WARN, UNKNOWN = "alarm", "warn", "unknown"


def _render(notes, rate, channels, volume):
    """notes: [(start_s, freq_hz, length_s, decay, harmonics)] -> pygame Sound."""
    import pygame

    total = max(start + length for start, _, length, _, _ in notes)
    buf = [0.0] * (int(total * rate) + 2)
    for start, freq, length, decay, harmonics in notes:
        s0, n = int(start * rate), int(length * rate)
        attack = int(0.006 * rate)
        for i in range(n):
            t = i / rate
            env = min(1.0, i / attack) * math.exp(-decay * t) * min(1.0, (n - i) / attack)
            w = sum(amp * math.sin(2 * math.pi * freq * k * t) for k, amp in harmonics)
            buf[s0 + i] += env * w
    peak = max(1e-9, max(abs(x) for x in buf))
    scale = 32767 * volume / peak
    samples = array("h", (int(x * scale) for x in buf for _ in range(channels)))
    return pygame.mixer.Sound(buffer=samples.tobytes())


BELL = [(1, 1.0), (2, 0.35), (3, 0.12)]
BUZZ = [(1, 1.0), (3, 0.33), (5, 0.2)]   # odd harmonics: square-ish, cuts through noise


FILE_KEYS = {"chime": "startup_file", "alert": "alarm_file", "beep": "warning_file", "nosignal": "nosignal_file",
             "keyoff": "keyoff_file"}


def load_sounds(ac, base_dir):
    """WAV files from config; any that can't be loaded fall back to built-in tones."""
    import pygame

    volume = ac.get("volume", 0.8)
    sounds, fallback = {}, None
    for name, key in FILE_KEYS.items():
        path = ac.get(key)
        if path:
            path = os.path.join(base_dir, path)
            try:
                snd = pygame.mixer.Sound(path)
                snd.set_volume(volume)
                sounds[name] = snd
                continue
            except Exception as e:
                log.warning("can't load %s (%s), using built-in tone", path, e)
        fallback = fallback or make_sounds(volume)
        sounds[name] = fallback[name]
    return sounds


def make_sounds(volume):
    """Built-in fallback tones."""
    import pygame

    rate, _, channels = pygame.mixer.get_init()
    chime = [(0.00, 523.25, 0.9, 4.0, BELL),    # C5
             (0.16, 659.25, 0.9, 4.0, BELL),    # E5
             (0.32, 783.99, 0.9, 4.0, BELL),    # G5
             (0.48, 1046.5, 1.4, 3.0, BELL)]    # C6
    alert = [(0.00, 988.0, 0.22, 0.0, BUZZ), (0.25, 740.0, 0.22, 0.0, BUZZ),
             (0.50, 988.0, 0.22, 0.0, BUZZ), (0.75, 740.0, 0.22, 0.0, BUZZ),
             (1.00, 740.0, 0.40, 50.0, BUZZ)]   # quiet tail = gap before the loop repeats
    beep = [(0.00, 1200.0, 0.12, 0.0, BUZZ), (0.18, 1200.0, 0.12, 0.0, BUZZ)]
    nosignal = [(0.00, 784.0, 0.18, 8.0, BUZZ), (0.20, 587.3, 0.18, 8.0, BUZZ),
                (0.40, 392.0, 0.45, 5.0, BUZZ)]                  # three falling notes
    keyoff = [(0.00, 1046.5, 0.7, 4.0, BELL), (0.16, 783.99, 0.7, 4.0, BELL),
              (0.32, 659.25, 0.7, 4.0, BELL), (0.48, 523.25, 1.2, 3.0, BELL)]   # startup chime, falling
    return {
        "keyoff": _render(keyoff, rate, channels, volume * 0.8),
        "chime": _render(chime, rate, channels, volume),
        "alert": _render(alert, rate, channels, volume),
        "beep": _render(beep, rate, channels, volume * 0.7),
        "nosignal": _render(nosignal, rate, channels, volume * 0.8),
    }


class Alerts:
    def __init__(self, cfg, sim=False, base_dir="."):
        ac, hc = cfg.get("audio", {}), cfg.get("horn", {})
        self.horn_sources = set(hc.get("sources", []))
        self.pattern = (hc.get("pulse_on", 0.5), hc.get("pulse_off", 0.5))
        self.warn_delay = ac.get("warn_delay", 3.0)
        self.warning_beep = ac.get("warning_beep", True)
        self.nosignal_sound = ac.get("nosignal_sound", True)
        self.nosignal_delay = ac.get("nosignal_delay", 2.0)
        self.keyoff_chime = ac.get("keyoff_chime", True)
        self.reminder_at = 0.0
        self.test_chirp = hc.get("test_on_startup", True)

        self.sounds = {}
        if ac.get("speaker", True):
            try:
                import pygame
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                pygame.mixer.set_num_channels(4)
                self.sounds = load_sounds(ac, base_dir)
                self.alert_ch, self.fx_ch = pygame.mixer.Channel(0), pygame.mixer.Channel(1)
            except Exception as e:
                log.warning("speaker unavailable, continuing without sound: %s", e)
                self.sounds = {}

        self.horn = None
        self.button = None
        if not sim:
            try:
                from gpiozero import Button, OutputDevice
                if hc.get("enabled", False):
                    self.horn = OutputDevice(hc["gpio"], active_high=hc.get("active_high", True), initial_value=False)
                if cfg.get("silence_button"):
                    self.button = Button(cfg["silence_button"]["gpio"], pull_up=True, bounce_time=0.05)
                    self.button.when_pressed = self.silence
            except Exception as e:
                log.error("horn / silence button GPIO not available: %s", e)

        self.silenced = set()
        self.warn_since = {}
        self.warn_beeped = set()
        self.lost_since = {}        # sensor -> when it went NO SIGNAL
        self.lost_played = set()    # sensors whose "connection lost" sound has played
        self.chirp_from = self.chirp_until = 0.0
        self.horn_on = False
        self.muted = False          # alarms present but all silenced
        self._silence_request = False

    # -- events

    def startup_test(self, start):
        """Short horn chirp when the lamp test starts (after the splash screen), so the operator
        knows the horn works."""
        if self.test_chirp:
            self.chirp_from, self.chirp_until = start, start + 0.3

    def chime(self):
        if self.sounds:
            self.fx_ch.play(self.sounds["chime"])

    def silence(self):
        self._silence_request = True

    def notice(self):
        """One warning ding right now (for reminders that shouldn't wait for warn_delay)."""
        if self.sounds:
            self.fx_ch.play(self.sounds["beep"])

    def keyoff(self):
        """Soft falling chime when the key is turned off: the dash is about to shut down."""
        if self.keyoff_chime and self.sounds:
            self.fx_ch.play(self.sounds["keyoff"])

    def lights_reminder(self, now, every=1.5):
        """Lights still on after key-off: the warning ding, repeated, until they go off or the
        dash shuts down. Waits for the key-off chime to finish first."""
        if not self.sounds or now < self.reminder_at or self.fx_ch.get_busy():
            return
        self.reminder_at = now + every
        self.fx_ch.play(self.sounds["beep"])

    # -- every frame

    def update(self, states, now):
        """states: {source_name: state} for every gauge and warning light."""
        alarms = {k for k, s in states.items() if s == ALARM}
        if self._silence_request:
            self._silence_request = False
            self.silenced = set(alarms)
        self.silenced &= alarms             # an alarm that clears re-arms
        loud = alarms - self.silenced
        self.muted = bool(alarms) and not loud

        on, off = self.pattern
        pulse = (now % (on + off)) < on
        self._set_horn((bool(loud & self.horn_sources) and pulse) or self.chirp_from <= now < self.chirp_until)

        if self.sounds:
            if loud and not self.alert_ch.get_busy():
                self.alert_ch.play(self.sounds["alert"], loops=-1)
            elif not loud and self.alert_ch.get_busy():
                self.alert_ch.stop()

        warns = {k for k, s in states.items() if s == WARN}
        for k in list(self.warn_since):
            if k not in warns:
                del self.warn_since[k]
                self.warn_beeped.discard(k)
        for k in warns:
            since = self.warn_since.setdefault(k, now)
            if k not in self.warn_beeped and now - since >= self.warn_delay:
                self.warn_beeped.add(k)
                if self.warning_beep and self.sounds and not loud:
                    self.fx_ch.play(self.sounds["beep"])

        # NO SIGNAL: play "connection lost" once per dropout, after it has lasted nosignal_delay
        # (so a flickering connector doesn't chatter). It plays again only after the sensor
        # has reconnected and dropped out again. Several sensors lost together = one sound.
        lost = {k for k, s in states.items() if s == UNKNOWN}
        for k in list(self.lost_since):
            if k not in lost:
                del self.lost_since[k]
                self.lost_played.discard(k)
        due = set()
        for k in lost:
            since = self.lost_since.setdefault(k, now)
            if k not in self.lost_played and now - since >= self.nosignal_delay:
                due.add(k)
        if due and not loud:        # during a red alarm it waits, and plays once the alarm stops
            self.lost_played |= due
            if self.nosignal_sound and self.sounds:
                self.fx_ch.play(self.sounds["nosignal"])

    def _set_horn(self, on):
        self.horn_on = on
        if self.horn is not None and self.horn.value != on:
            self.horn.value = on

    def close(self):
        self._set_horn(False)
        if self.horn is not None:
            self.horn.close()

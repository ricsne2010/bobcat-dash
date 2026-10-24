"""The four menu buttons (breakout board rev 2.9, BUTTONS plug): LEFT, RIGHT, OK, BACK.

Each is a momentary push button to GND on its own GPIO (internal pull-up). Presses are queued from
gpiozero's thread and read by the dash loop with poll(). Holding BACK for hold_seconds sends "home".
In the simulator (or with a USB keyboard): ; and ' for LEFT / RIGHT, Enter for OK, Backspace for BACK
(hold it for home).
"""
import logging
import queue

log = logging.getLogger("buttons")

NAMES = ("left", "right", "ok", "back")
SIM_KEYS = {";": "left", "'": "right", "return": "ok", "enter": "ok", "backspace": "back"}


class Buttons:
    def __init__(self, cfg, sim=False):
        bc = cfg.get("buttons", {})
        self.enabled = bc.get("enabled", True)
        self.q = queue.Queue()
        self.devices = []
        self.hold_s = bc.get("hold_seconds", 2.0)
        self._held_back = False
        if sim or not self.enabled:
            return
        try:
            from gpiozero import Button
            for name in NAMES:
                pin = bc.get(f"{name}_gpio")
                if pin is None:
                    continue
                b = Button(pin, pull_up=True, bounce_time=0.03, hold_time=self.hold_s)
                if name == "back":                     # BACK acts on release, so a hold can be "home"
                    b.when_held = self._back_held
                    b.when_released = self._back_released
                else:
                    b.when_pressed = (lambda n=name: self.q.put(n))
                self.devices.append(b)
        except Exception as e:                         # no GPIO (not a Pi) or pin busy: dash still runs
            log.error("menu buttons not available: %s", e)

    def _back_held(self):
        self._held_back = True
        self.q.put("home")

    def _back_released(self):
        if not self._held_back:
            self.q.put("back")
        self._held_back = False

    def sim_key(self, key, down, now):
        """Simulator: returns True if the key was a menu button. Backspace held >= hold_s = home."""
        name = SIM_KEYS.get(key)
        if name is None:
            return False
        if name == "back":
            if down:
                self._back_down = now
            else:
                held = now - getattr(self, "_back_down", now)
                self.q.put("home" if held >= self.hold_s else "back")
        elif down:
            self.q.put(name)
        return True

    def poll(self):
        out = []
        while True:
            try:
                out.append(self.q.get_nowait())
            except queue.Empty:
                return out

    def close(self):
        for b in self.devices:
            b.close()

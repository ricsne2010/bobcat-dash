"""Button pod exhaust fan (breakout board rev 2.9: FAN output on J17, switched by Q5 from GPIO 11).

On when the Pi's CPU reaches on_c, off again once it's back under off_c (the gap stops it cycling).
Also on whenever the key-off countdown / shutdown is running, so the pod is aired out before the power
goes. In the simulator it just follows the simulated Pi temperature (I key = Pi too hot).
"""
import logging

import settings

log = logging.getLogger("fan")


class PodFan:
    def __init__(self, cfg, sim=False):
        fc = cfg.get("fan", {})
        self.enabled = fc.get("enabled", True)
        self.on_c = fc.get("on_c", 55.0)
        self.off_c = fc.get("off_c", 48.0)
        self.on = False
        self.dev = None
        if self.enabled and not sim:
            try:
                from gpiozero import DigitalOutputDevice
                self.dev = DigitalOutputDevice(fc.get("gpio", 11), active_high=True, initial_value=False)
            except Exception as e:                  # no GPIO (not a Pi) or pin busy: the dash still runs
                log.error("pod fan output not available: %s", e)

    def update(self, pi_temp, force=False):
        """pi_temp: deg C or None (unknown: run the fan to be safe). force: keep it on (shutting down)."""
        if not self.enabled:
            return False
        if force or pi_temp is None:
            want = True
        elif self.on:
            want = pi_temp > self.off_c
        else:
            want = pi_temp >= self.on_c
        if want != self.on:
            self.on = want
            log.info("pod fan %s (Pi %s C)", "on" if want else "off", "?" if pi_temp is None else f"{pi_temp:.0f}")
            if self.dev:
                self.dev.value = want
        return self.on

    def describe(self):
        if not self.enabled:
            return "not fitted"
        return (f"ON (off below {settings.fmt(self.off_c, space=True)})" if self.on
                else f"off (on at {settings.fmt(self.on_c, space=True)})")

    def close(self):
        if self.dev:
            self.dev.off()
            self.dev.close()

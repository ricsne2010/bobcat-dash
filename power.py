"""Key-off shutdown, for the breakout board's power-hold circuit (rev 2.0).

The board keeps the Pi powered after the key is turned off:

  * HOLD (GPIO 26) keeps the power on. It's set high by the Pi's firmware at boot
    (`gpio=26=op,dh` in config.txt), so this program never touches it.
  * KEY (GPIO 6) reads the key switch through an optocoupler: low = key on.
  * KILL (GPIO 16) cuts the power. It's raised by a tiny script that runs as the very
    last step of shutdown, after every disk is read-only
    (tools/bobcat-dash-poweroff, installed in /usr/lib/systemd/system-shutdown/).
  * If the Pi never shuts down, a timer on the board cuts the power ~3 minutes after key-off.

This module watches the key. When it's been off for keyoff_delay_s (5 s), the dash saves the
hour meter and asks the system to power off. Turning the key back on during the countdown
cancels it. Turning it back on after shutdown has started is fine too: the board cuts the
power for a few seconds and the Pi starts up again.
"""
import logging
import subprocess

log = logging.getLogger("power")

ON, COUNTDOWN, SHUTDOWN = "on", "countdown", "shutdown"


class PowerManager:
    def __init__(self, cfg, sim=False, start_off=False):
        """start_off: simulator only, start as a parked machine (key off, powered down)."""
        pc = cfg.get("power", {})
        self.enabled = pc.get("enabled", False)
        self.delay = pc.get("keyoff_delay_s", 5.0)
        self.command = pc.get("shutdown_command", ["sudo", "-n", "/usr/bin/systemctl", "poweroff"])
        self.sim = sim
        self.state = SHUTDOWN if (sim and start_off and self.enabled) else ON
        self.key_off_since = None
        self.seen_on = False     # act on key-off only after the key has been seen on
        self.error = None

    def remaining(self, now):
        if self.state != COUNTDOWN:
            return 0.0
        return max(0.0, self.delay - (now - self.key_off_since))

    def update(self, key_on, now, before_shutdown):
        """key_on: True / False, or None if the board has no key input (feature off).
        before_shutdown(): called once, just before the power-off command (save everything)."""
        if not self.enabled or key_on is None:
            self.state, self.key_off_since = ON, None
            return self.state

        if key_on:
            self.seen_on = True
        elif not self.seen_on:
            # Never seen the key on: a board without the power-hold circuit (the pin just
            # floats high), or the key went off while the Pi was booting. Do nothing; on a
            # rev 2.0 board the timer cuts the power ~3 minutes after key-off.
            return self.state

        if self.state == SHUTDOWN:
            if key_on and self.sim:          # simulator: key back on = the Pi "boots" again
                self.state, self.key_off_since = ON, None
            return self.state

        if key_on:
            if self.state == COUNTDOWN:
                log.info("key back on, shutdown cancelled")
            self.state, self.key_off_since = ON, None
        elif self.state == ON:
            self.state, self.key_off_since = COUNTDOWN, now
            log.info("key off, shutting down in %.0f s unless it's turned back on", self.delay)
        elif now - self.key_off_since >= self.delay:
            self.state = SHUTDOWN
            before_shutdown()
            self._power_off()
        return self.state

    def _power_off(self):
        if self.sim:
            log.info("simulator: would run %s", " ".join(self.command))
            return
        log.info("key off: powering off (%s)", " ".join(self.command))
        try:
            r = subprocess.run(self.command, capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                self.error = (r.stderr or r.stdout).strip() or f"exit code {r.returncode}"
        except (OSError, subprocess.TimeoutExpired) as e:
            self.error = str(e)
        if self.error:
            # The board's timer still cuts the power ~3 minutes after key-off.
            log.error("power-off command failed: %s", self.error)

"""Parking brake: a sealed switch on the handle, closed when the brake is set, through the breakout board's
PARK BRAKE input (optocoupler, rev 3.0) to a GPIO. Pin pulled low = brake set.

Shown as a red (P) on the dash while the brake is set. Two reminders, never more than that:
  PARKING BRAKE ON   the brake is set while the engine is working above idle (driving against it), for drive_s
  SET PARKING BRAKE  at key-off, if it isn't set (on the shutdown countdown, with a tone)
A broken wire reads as "released" (the switch can't tell an open wire from an open switch), so the key-off
reminder is also the check that the switch still works: set the brake and it goes away.
"""
import time

OK, WARN = "ok", "warn"


class BrakeStatus:
    def __init__(self, cfg, sim=False):
        bc = cfg.get("park_brake", {})
        self.enabled = bc.get("enabled", False) or (sim and bc.get("sim", True))
        self.drive_rpm = bc.get("drive_rpm", cfg.get("tach", {}).get("idle_rpm", 1000) + 400)
        self.drive_s = bc.get("drive_s", 5.0)
        self.since = None
        self.applied = None

    def update(self, applied, running, rpm, now=None):
        """applied: True / False / None (no input). -> {"applied", "state", "text"} or None when off."""
        if not self.enabled or applied is None:
            self.applied = None
            return None
        now = time.monotonic() if now is None else now
        self.applied = applied
        working = applied and running and (rpm or 0) >= self.drive_rpm
        if not working:
            self.since = None
        elif self.since is None:
            self.since = now
        if self.since is not None and now - self.since >= self.drive_s:
            return {"applied": True, "state": WARN, "text": "PARKING BRAKE ON"}
        return {"applied": applied, "state": OK, "text": "PARK BRAKE SET" if applied else "PARK BRAKE OFF"}

    def reminder(self):
        """True when the key is off and the brake isn't set (the shutdown overlay asks for it)."""
        return self.enabled and self.applied is False

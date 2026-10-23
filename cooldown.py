"""Cool-down reminder for the air-cooled Wisconsin VH4D.

After a spell of hard work the engine should idle for a few minutes before it's shut off,
so the heads and valves cool evenly. With a hand throttle that's easy to skip, so the dash
keeps track:

  * Hard work: time spent at or above hard_rpm adds up (short dips don't reset it).
  * Once there's been hard_minutes of it, a cool-down is due. As soon as the throttle comes
    back to idle (at or below idle_max_rpm) the RPM panel shows "COOL DOWN 2:40", counting down.
  * Revving above idle_max_rpm restarts the countdown (working hard again also adds more
    hard-work time). Between idle and hard_rpm the panel says "IDLE TO COOL DOWN".
  * When the countdown finishes: "OK TO SHUT DOWN" in green for done_seconds, then back to normal.
  * Stopping the engine clears it all.

Information only: no beep, no horn, not counted as a warning.
"""

HOT, IDLE_NEEDED, COOLING, DONE = "hot", "idle_needed", "cooling", "done"


class CoolDown:
    def __init__(self, cfg):
        c = cfg.get("cooldown", {})
        self.enabled = c.get("enabled", True)
        self.hard_rpm = c.get("hard_rpm", 2000)
        self.hard_needed = c.get("hard_minutes", 5.0) * 60
        self.idle_max = c.get("idle_max_rpm", 1300)
        self.cool_needed = c.get("cool_minutes", 3.0) * 60
        self.done_show = c.get("done_seconds", 60.0)
        self.speed = 1          # simulator: X runs the clock 60x faster (with the hour meter)
        self.t = None
        self.reset()

    def reset(self):
        self.hard = 0.0         # seconds of hard work since the last cool-down
        self.idled = 0.0        # seconds idled so far in this cool-down
        self.done_at = None

    @property
    def due(self):
        return self.hard >= self.hard_needed

    def update(self, running, rpm, now):
        # dt is capped so a pause (a stalled frame, the simulator's power-off screen) doesn't count
        dt = 0.0 if self.t is None else max(0.0, min(1.0, now - self.t)) * self.speed
        self.t = now
        if not self.enabled or not running or rpm is None:
            self.reset()
            return
        if rpm >= self.hard_rpm:
            self.hard += dt
            self.idled = 0.0
            self.done_at = None
        elif rpm <= self.idle_max:
            if self.due:
                self.idled += dt
                if self.idled >= self.cool_needed:
                    self.hard = self.idled = 0.0
                    self.done_at = now
        else:
            self.idled = 0.0    # part throttle: not working hard, but not cooling either

    def status(self, now, rpm):
        """(state, seconds_left) or None when there's nothing to show."""
        if self.due:
            if rpm is not None and rpm <= self.idle_max:
                return COOLING, max(0.0, (self.cool_needed - self.idled) / self.speed)
            if rpm is not None and rpm < self.hard_rpm:
                return IDLE_NEEDED, None
            return HOT, None                    # still working: nothing shown yet
        if self.done_at is not None and now - self.done_at < self.done_show:
            return DONE, None
        return None

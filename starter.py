"""Starter guard: don't overheat the starter.

  * Cranking for more than [tach] crank_limit seconds (10) without a start: REST STARTER, with a beep at once
    and every 5 s while it goes on.
  * Let go of the key after that: STARTER COOLING with a countdown of crank_rest seconds (30).
    Cranking again before it runs out: REST STARTER again, and the countdown starts over when you let go.
  * Countdown done: READY TO START (green) for a few seconds.
  * The engine starts: all of it clears.

Information and a reminder only: it doesn't stop anything (the starter is wired to the key, not the dash).
"""


class StarterGuard:
    def __init__(self, cfg):
        tc = cfg.get("tach", {})
        self.limit = tc.get("crank_limit", 10.0)
        self.rest = tc.get("crank_rest", 30.0)
        self.ready_show = 5.0
        self.beep_every = 5.0
        self.gap = 1.0                 # a dropout shorter than this is still the same crank
        self.crank_start = None
        self.last_crank = None
        self.over = False              # this crank went past the limit (or started while still resting)
        self.rest_until = None
        self.next_beep = 0.0

    def update(self, cranking, running, now):
        """Returns (status, beep_now). status: None, ("over", 0), ("rest", seconds_left) or ("ready", 0)."""
        if running:
            self.crank_start = self.last_crank = self.rest_until = None
            self.over = False
            return None, False
        if cranking or (self.last_crank is not None and now - self.last_crank < self.gap):
            if cranking:
                self.last_crank = now
            if self.crank_start is None:
                self.crank_start = now
                self.over = self.rest_until is not None and now < self.rest_until   # cranking again too soon
            if now - self.crank_start >= self.limit:
                self.over = True
            if self.over:
                beep = cranking and now >= self.next_beep        # no beep once the key's been let go
                if beep:
                    self.next_beep = now + self.beep_every
                return ("over", 0), beep
            return None, False
        if self.crank_start is not None:             # the key was let go
            if self.over:
                self.rest_until = now + self.rest
            self.crank_start, self.over, self.next_beep = None, False, 0.0
        if self.rest_until is not None:
            if now < self.rest_until:
                return ("rest", self.rest_until - now), False
            if now < self.rest_until + self.ready_show:
                return ("ready", 0), False
            self.rest_until = None
        return None, False

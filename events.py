"""Alarm and warning history: what happened, when (engine hours, and the date when the clock is set),
and for how long. Clearing an event (one, or all) only hides it from the HISTORY list: it stays in the
archive (ALL ALARMS), marked cleared. Kept in the data folder as events.json (the last max_events), written safely
(temp file, fsync, rename) when an event starts and when it ends, so it survives power cuts.

An event is a gauge or warning light going amber, red or NO SIGNAL for at least min_seconds. If it
gets worse while it lasts (amber -> red) the event is upgraded, not split. Nothing is recorded during
the lamp test or while the dash is shutting down.
"""
import logging
import time

from service import clock_valid, read_json, write_json

log = logging.getLogger("events")

LEVELS = {"warn": 1, "unknown": 1, "alarm": 2}         # what counts as an event, and how bad
FILE = "events.json"


class EventLog:
    def __init__(self, cfg, directory):
        ec = cfg.get("history", {})
        self.enabled = ec.get("enabled", True)
        self.min_s = ec.get("min_seconds", 2.0)
        self.max_events = ec.get("max_events", 500)
        self.dir = directory
        self.events = (read_json(directory, FILE) or {}).get("events", [])
        self.pending = {}           # source -> (level, detail, since): not long enough yet
        self.open = {}              # source -> index into self.events
        self.save_error = None

    def update(self, states, labels, hours, now, wall=None):
        """states: {source: (state, detail)}; labels: {source: display name}. Returns the events that
        became ALARMs this call (so the screen can jump back to the gauges)."""
        if not self.enabled:
            return []
        wall = time.time() if wall is None else wall
        new_alarms, changed = [], False
        for src, (state, detail) in states.items():
            level = state if state in LEVELS else None
            if src in self.open:
                ev = self.events[self.open[src]]
                if level is None:                                   # it cleared: close the event
                    ev["dur_s"] = round(now - ev["_since"], 1)
                    ev.pop("_since", None)
                    del self.open[src]
                    changed = True
                elif LEVELS[level] > LEVELS[ev["level"]]:           # got worse: upgrade it
                    ev["level"], ev["detail"] = level, detail
                    changed = True
                    if level == "alarm":
                        new_alarms.append(ev)
                continue
            if level is None:
                self.pending.pop(src, None)
                continue
            p = self.pending.get(src)
            if p is None or LEVELS[level] > LEVELS[p[0]]:
                self.pending[src] = (level, detail, now if p is None else p[2])
                p = self.pending[src]
            if now - p[2] >= self.min_s:                            # long enough: it's an event
                ev = {"what": labels.get(src, src.upper()), "src": src, "level": p[0], "detail": p[1],
                      "h": round(hours, 1), "t": (wall - (now - p[2])) if clock_valid(wall) else None,
                      "dur_s": None, "_since": p[2]}
                self.events.append(ev)
                self.open[src] = len(self.events) - 1
                del self.pending[src]
                changed = True
                if p[0] == "alarm":
                    new_alarms.append(ev)
        for src in [s for s in self.open if s not in states]:      # source gone (e.g. sensor disabled)
            self.events[self.open.pop(src)].pop("_since", None)
            changed = True
        if len(self.events) > self.max_events:
            drop = len(self.events) - self.max_events
            self.events = self.events[drop:]
            self.open = {s: i - drop for s, i in self.open.items() if i >= drop}
        if changed:
            self.save()
        return new_alarms

    def note(self, what, level, detail, hours, wall=None):
        """A one-off entry (not a gauge going amber), e.g. a wrong maintenance code."""
        wall = time.time() if wall is None else wall
        self.events.append({"what": what, "src": "note", "level": level, "detail": detail, "h": round(hours, 1),
                            "t": wall if clock_valid(wall) else None, "dur_s": 0})
        if len(self.events) > self.max_events:
            drop = len(self.events) - self.max_events
            self.events = self.events[drop:]
            self.open = {s: i - drop for s, i in self.open.items() if i >= drop}
        self.save()

    def close_all(self, now):
        """Key-off / exit: end whatever's still going, so durations aren't left open."""
        for src, i in list(self.open.items()):
            ev = self.events[i]
            ev["dur_s"] = round(now - ev.pop("_since", now), 1)
        self.open.clear()
        self.pending.clear()
        self.save()

    def newest_first(self):
        """The current list: everything not cleared, newest first."""
        return [ev for ev in reversed(self.events) if not ev.get("cleared")]

    def archive(self):
        """Everything ever recorded (cleared or not), newest first."""
        return list(reversed(self.events))

    def clear(self, ev):
        """Hide one event from the current list (it stays in the archive)."""
        ev["cleared"] = True
        self.save()

    def clear_all(self):
        for ev in self.events:
            ev["cleared"] = True
        self.save()

    def save(self):
        try:
            clean = [{k: v for k, v in ev.items() if not k.startswith("_")} for ev in self.events]
            write_json(self.dir, FILE, {"events": clean})
            self.save_error = None
        except OSError as e:
            if not self.save_error:
                log.error("can't save %s: %s", FILE, e)
            self.save_error = str(e)

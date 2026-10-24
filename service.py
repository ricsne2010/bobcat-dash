"""Service reminders, by engine hours (and, for some items, by date too).

The schedule is in config.toml, [service]: every item has an interval in engine hours, and items the
Bobcat 700 manual gives a different figure for in hot weather (engine oil: every 25 h above 90 F instead
of 50 h) say so with hours_by_climate. The climate is picked on the Service screen and saved, so moving
the machine to another climate is one setting, not an edit.

Saved in the data folder (next to the hour meter) as service.json: the climate, when each item was last
done (engine hours + date), any "remind me later", and the list of completed services. Written the same
safe way as the hour meter (temp file, fsync, rename), so a power cut can't corrupt it.
"""
import json
import logging
import os
import time

log = logging.getLogger("service")

OK, SOON, DUE = "ok", "soon", "due"
FILE = "service.json"
CLOCK_VALID_AFTER = 1735689600          # 2025-01-01: an earlier date means the Pi's clock was never set


def clock_valid(t=None):
    return (time.time() if t is None else t) > CLOCK_VALID_AFTER


def write_json(directory, name, data):
    """Temp file, fsync, rename, fsync the folder: either the old or the new file, never half of one."""
    os.makedirs(directory, exist_ok=True)
    tmp = os.path.join(directory, name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, os.path.join(directory, name))
    try:
        dfd = os.open(directory, os.O_RDONLY)
        os.fsync(dfd)
        os.close(dfd)
    except OSError:
        pass


def read_json(directory, name):
    try:
        with open(os.path.join(directory, name)) as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (ValueError, OSError) as e:
        log.error("%s is unreadable (%s): starting it fresh", name, e)
        return None


class Service:
    def __init__(self, cfg, directory):
        sc = cfg.get("service", {})
        self.enabled = sc.get("enabled", True)
        self.dir = directory
        self.within_h = sc.get("remind_within_hours", 5.0)
        self.short_h = sc.get("short_interval_hours", 10.0)      # items this frequent (the daily checks)...
        self.short_within_h = sc.get("remind_short_within_hours", 2.0)   # ...get a shorter warning
        self.within_days = sc.get("remind_within_days", 14)
        self.snooze_h = sc.get("snooze_hours", 5.0)
        self.climates = sc.get("climate", [])                 # [{id, label, oil_grade}]
        self.items = sc.get("item", [])                       # [{id, name, task, hours, hours_by_climate, days}]
        saved = read_json(directory, FILE) or {}
        ids = [c["id"] for c in self.climates]
        self.climate = saved.get("climate") if saved.get("climate") in ids else sc.get("default_climate",
                                                                                     ids[0] if ids else "")
        self.state = saved.get("items", {})                   # id -> {done_h, done_t, snooze_h, later}
        self.history = saved.get("history", [])               # [{id, name, h, t}]
        self.session_later = set()                            # "remind me at next start": until the Pi restarts
        self.soon_shown = set(saved.get("soon_shown", []))
        self.save_error = None

    # -- the schedule

    def climate_info(self, cid=None):
        cid = cid or self.climate
        return next((c for c in self.climates if c["id"] == cid), {"id": cid, "label": cid, "oil_grade": ""})

    def interval(self, item):
        return item.get("hours_by_climate", {}).get(self.climate, item["hours"])

    def window(self, item):
        """How many engine hours ahead it's announced: shorter for the frequent items."""
        return self.short_within_h if self.interval(item) <= self.short_h else self.within_h

    def climate_sensitive(self, item):
        return bool(item.get("hours_by_climate"))

    def task(self, item):
        return item.get("task", "").replace("{oil_grade}", self.climate_info().get("oil_grade", ""))

    def baseline(self, hours):
        """First run, or a new item in the config: count it from now (marked as not confirmed)."""
        changed = False
        for it in self.items:
            if it["id"] not in self.state:
                self.state[it["id"]] = {"done_h": round(hours, 1), "done_t": time.time() if clock_valid() else None,
                                        "baseline": True}
                changed = True
        if changed:
            self.save()

    def status(self, hours, now_t=None):
        """[(item, state, hours_left, days_left)], most urgent first. hours_left < 0 = overdue."""
        now_t = time.time() if now_t is None else now_t
        out = []
        for it in self.items:
            s = self.state.get(it["id"], {})
            left = self.interval(it) - (hours - s.get("done_h", hours))
            days_left = None
            if it.get("days") and s.get("done_t") and clock_valid(now_t):
                days_left = it["days"] - (now_t - s["done_t"]) / 86400.0
            if left <= 0 or (days_left is not None and days_left <= 0):
                state = DUE
            elif left <= self.window(it) or (days_left is not None and days_left <= self.within_days):
                state = SOON
            else:
                state = OK
            out.append((it, state, left, days_left))
        order = {DUE: 0, SOON: 1, OK: 2}
        out.sort(key=lambda x: (order[x[1]], x[2]))
        return out

    def snoozed(self, item, hours):
        s = self.state.get(item["id"], {})
        return item["id"] in self.session_later or (s.get("snooze_h") is not None and hours < s["snooze_h"])

    def to_announce(self, hours):
        """Items for the key-on pop-up: every DUE item not put off, and each SOON item once."""
        out = []
        for it, state, left, days in self.status(hours):
            if self.snoozed(it, hours):
                continue
            if state == DUE or (state == SOON and it["id"] not in self.soon_shown):
                out.append((it, state, left, days))
        return out

    def any_due(self, hours):
        return any(state == DUE for _, state, _, _ in self.status(hours))

    # -- operator actions

    def mark_done(self, item_id, hours):
        it = next(i for i in self.items if i["id"] == item_id)
        t = time.time() if clock_valid() else None
        self.state[item_id] = {"done_h": round(hours, 1), "done_t": t}
        self.history.append({"id": item_id, "name": it["name"], "h": round(hours, 1), "t": t})
        self.history = self.history[-300:]
        self.session_later.discard(item_id)
        self.soon_shown.discard(item_id)
        self.save()

    def later(self, item_id, hours, next_start=True):
        """Remind me later: at the next key-on, or after snooze_hours more engine hours."""
        if next_start:
            self.session_later.add(item_id)
        else:
            self.state.setdefault(item_id, {})["snooze_h"] = round(hours + self.snooze_h, 1)
            self.save()

    def shown(self, items):
        """The pop-up showed these: a SOON item isn't announced again until it's DUE."""
        new = {it["id"] for it, state, _, _ in items if state == SOON} - self.soon_shown
        if new:
            self.soon_shown |= new
            self.save()

    def set_climate(self, cid):
        if cid != self.climate and any(c["id"] == cid for c in self.climates):
            self.climate = cid
            self.save()
            log.info("climate set to %s", cid)

    def completed(self, item_id=None):
        return [h for h in reversed(self.history) if item_id is None or h["id"] == item_id]

    def save(self):
        try:
            write_json(self.dir, FILE, {"climate": self.climate, "items": self.state, "history": self.history,
                                        "soon_shown": sorted(self.soon_shown)})
            self.save_error = None
        except OSError as e:
            if not self.save_error:
                log.error("can't save %s: %s", FILE, e)
            self.save_error = str(e)

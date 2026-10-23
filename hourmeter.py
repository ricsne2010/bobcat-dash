"""Engine hour meter (Hobbs meter): counts engine running time and keeps it
across reboots and sudden power loss.

  * Counts only while the engine is running.
  * Saves every save_every_s seconds of running, and when the engine stops.
    With the breakout board rev 2.0 the Pi shuts down cleanly after key-off (power.py),
    so the engine-stop save keeps everything. Without it, or after an unexpected power
    cut, the periodic save limits the loss to save_every_s seconds.
  * Two copies (a and b) are written alternately, each written to a temporary
    file, flushed to disk and then renamed into place, and each carries a
    checksum. If power dies mid-write, the other copy is still good.
  * There is no reset on screen or in config.toml. The only way to change the
    total is `python3 dash.py --set-hours N`, which asks for confirmation and
    refuses to run while the dash is running.
"""
import fcntl
import hashlib
import json
import logging
import os

log = logging.getLogger("hourmeter")
FILES = ("hours_a.json", "hours_b.json")


def _check(hours, seq):
    return hashlib.sha256(f"{hours:.6f}:{seq}".encode()).hexdigest()[:16]


def data_dir(cfg, sim):
    d = os.path.expanduser(cfg.get("hourmeter", {}).get("data_dir", "~/bobcat-dash-data"))
    return os.path.join(d, "simulator") if sim else d


def read_saved(directory):
    """Newest valid saved total as (hours, seq), or None if there's nothing valid."""
    best = None
    for name in FILES:
        try:
            with open(os.path.join(directory, name)) as f:
                rec = json.load(f)
            hours, seq = float(rec["hours"]), int(rec["seq"])
            if rec.get("check") != _check(hours, seq) or hours < 0:
                log.warning("%s failed its checksum, ignoring it", name)
                continue
            if best is None or seq > best[1]:
                best = (hours, seq)
        except FileNotFoundError:
            pass
        except (ValueError, KeyError, TypeError) as e:
            log.warning("%s is unreadable (%s), ignoring it", name, e)
    return best


def write_saved(directory, hours, seq):
    """Write copy a or b (alternating by seq) safely: temp file, fsync, rename, fsync dir."""
    os.makedirs(directory, exist_ok=True)
    name = FILES[seq % 2]
    tmp = os.path.join(directory, name + ".tmp")
    with open(tmp, "w") as f:
        json.dump({"hours": round(hours, 6), "seq": seq, "check": _check(round(hours, 6), seq)}, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, os.path.join(directory, name))
    try:
        dfd = os.open(directory, os.O_RDONLY)
        os.fsync(dfd)
        os.close(dfd)
    except OSError:
        pass


def storage_is_volatile(directory):
    """True if the directory is on a filesystem that is thrown away at reboot
    (the read-only overlay mode, or a RAM disk)."""
    try:
        path = os.path.realpath(directory)
        best, fstype = "", ""
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                mnt = parts[1]
                if (path == mnt or path.startswith(mnt.rstrip("/") + "/")) and len(mnt) > len(best):
                    best, fstype = mnt, parts[2]
        return fstype in ("overlay", "tmpfs")
    except OSError:
        return False          # no /proc/mounts (not Linux): assume a normal disk


class HourMeter:
    def __init__(self, cfg, sim=False):
        hc = cfg.get("hourmeter", {})
        self.dir = data_dir(cfg, sim)
        self.save_every = hc.get("save_every_s", 15)
        self.saves_ok = True
        self.lock_file = None
        self._lock()
        saved = read_saved(self.dir)
        if saved:
            self.hours, self.seq = saved
        else:
            self.hours, self.seq = float(hc.get("initial_hours", 0.0)), 0
            log.info("no saved hours in %s, starting at %.1f", self.dir, self.hours)
        if storage_is_volatile(self.dir):
            log.error("hour meter folder %s is on a read-only overlay / RAM disk: hours will be lost at reboot", self.dir)
            self.saves_ok = False
        self.unsaved = 0.0
        self.last = None
        self.running = False
        self.sim_speed = 1           # simulator fast-forward (X key); always 1 on the machine

    def _lock(self):
        """Hold a lock while the dash runs, so --set-hours can't race it."""
        os.makedirs(self.dir, exist_ok=True)
        self.lock_file = open(os.path.join(self.dir, ".lock"), "w")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(f"Another copy of the dash is already using {self.dir}.")

    def update(self, running, now):
        if self.last is not None and running and self.running:
            dt = min(now - self.last, 5.0)     # ignore gaps (e.g. the computer was asleep)
            self.hours += dt * self.sim_speed / 3600.0
            self.unsaved += dt
            if self.unsaved >= self.save_every:
                self.save()
        if self.running and not running:      # engine just stopped
            self.save()
        self.running, self.last = running, now

    def save(self):
        if not self.unsaved:
            return
        try:
            self.seq += 1
            write_saved(self.dir, self.hours, self.seq)
            self.unsaved = 0.0
        except OSError as e:
            if self.saves_ok:
                log.error("can't save hours: %s", e)
            self.saves_ok = False

    def add_sim_hours(self, h):
        """Simulator only: jump the count forward to see the display roll over."""
        self.hours += h
        self.unsaved += 1
        self.save()

    def tenths_fraction(self):
        """How far the tenths wheel has turned toward the next digit (0..1), for the rolling display."""
        x = self.hours * 10
        return max(0.0, x - int(x + 1e-9))

    def display(self):
        """'1234.5': 4 digits and tenths, wrapping after 9999.9 like a mechanical meter."""
        tenths = int(self.hours * 10 + 1e-9) % 100000
        return f"{tenths // 10:04d}.{tenths % 10}"

    def close(self):
        self.save()
        if self.lock_file:
            self.lock_file.close()


def set_hours_cli(cfg, value, sim=False):
    """`dash.py --set-hours N`: the only way to change the total."""
    directory = data_dir(cfg, sim)
    os.makedirs(directory, exist_ok=True)
    lock = open(os.path.join(directory, ".lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("The dash is running. Stop it first:  sudo systemctl stop bobcat-dash")
        return 1
    saved = read_saved(directory)
    current = saved[0] if saved else None
    print(f"Hour meter folder: {directory}")
    print(f"Current total:     {'none saved' if current is None else f'{current:.2f} h'}")
    print(f"New total:         {value:.2f} h")
    if input("Type YES to change the engine hours: ").strip() != "YES":
        print("Not changed.")
        return 1
    write_saved(directory, float(value), (saved[1] if saved else 0) + 1)
    write_saved(directory, float(value), (saved[1] if saved else 0) + 2)   # both copies agree
    print(f"Engine hours set to {value:.1f}.")
    return 0

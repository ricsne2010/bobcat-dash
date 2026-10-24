"""The maintenance code: a short number code, entered with the menu buttons, that guards the service jobs
(turning SERVICE WI-FI on, installing software from a USB stick, clearing alarms, marking service done), so not
just anyone at the buttons can. Entered once, it stays good until the engine starts or the key goes off.

A new code can't be all one digit (1111) or a run up or down (1234, 4321, 7890, 8901): weak() says why.
There's no code out of the box (a default code in a public program would be no code at all): the first time
it's needed, the dash asks you to make one up and enter it twice. Only a salted hash is kept, in the data folder
(maint-code.json), never the code itself.

code_tries wrong codes in a row lock it for 5 minutes, then 10, 20, ... up to 2 hours; the count and the lock
survive a restart. Every wrong code is also recorded in the alarm history (MAINTENANCE CODE).
Change it: SYSTEM > MX CODE (engine off): the old code first, then the new one twice, then a last look at it.
The recovery code doesn't change.
Forgot it?
  1. The RECOVERY CODE (8 digits) shown once when the code was made: on the code screen, arrow the first digit
     to "?" and press OK, enter it, then make a new code (and get a new recovery code).
  2. Lost that too: take out the SD card, put it in any computer and make an empty file called  reset-code  on
     its boot drive (the small one Windows / macOS can open). At the next start the dash forgets the code
     and deletes the file. (Or on the Pi itself:  python3 dash.py --reset-code)
"""
import hashlib
import hmac
import logging
import os
import random
import subprocess
import time

from service import read_json, write_json

log = logging.getLogger("maintcode")

FILE = "maint-code.json"
ROUNDS = 100_000
RESET_FILES = ("/boot/firmware/reset-code", "/boot/reset-code")
RESET_HELPER = "/usr/local/bin/bobcat-dash-reset-code"


def _hash(code, salt):
    return hashlib.pbkdf2_hmac("sha256", code.encode(), bytes.fromhex(salt), ROUNDS).hex()


def weak(code):
    """Why a new code isn't allowed, or None if it's fine."""
    d = [int(c) for c in code]
    if len(set(d)) == 1:
        return "All the same digit. Pick another."
    steps = {(b - a) % 10 for a, b in zip(d, d[1:])}
    if steps in ({1}, {9}):
        return "Digits in a row (like 1234 or 4321). Pick another."
    return None


class MaintCode:
    def __init__(self, cfg, directory):
        sc = cfg.get("service_mode", {})
        self.digits = sc.get("code_digits", 4)
        self.tries = sc.get("code_tries", 3)
        self.dir = directory
        self.saved = read_json(directory, FILE) or {}
        self.unlocked = False          # entered since key-on, engine not run since (the dash locks it again)

    def is_set(self):
        return bool(self.saved.get("hash"))

    def _save(self):
        try:
            write_json(self.dir, FILE, self.saved)
        except OSError as e:
            log.error("can't save %s: %s", FILE, e)

    def locked_for(self, wall=None):
        """Seconds until codes are accepted again (0 = not locked)."""
        wall = time.time() if wall is None else wall
        return max(0.0, self.saved.get("locked_until", 0) - wall)

    def set(self, code):
        """Saves a new code and makes a new recovery code, which it returns (to show once)."""
        rnd = random.SystemRandom()
        while True:
            recovery = "".join(rnd.choice("0123456789") for _ in range(8))
            if not weak(recovery):
                break
        salt = os.urandom(16).hex()
        self.saved = {"salt": salt, "hash": _hash(code, salt), "recovery": _hash(recovery, salt), "set_t": time.time()}
        self._save()
        log.info("maintenance code set")
        return recovery

    def change(self, code):
        """A new code in place of the old one (SYSTEM > MX CODE). The recovery code stays as it was, so the
        paperwork kept with the machine still works."""
        self.saved.update(hash=_hash(code, self.saved["salt"]), set_t=time.time(), wrong=0, locks=0)
        self._save()
        log.info("maintenance code changed")

    def same(self, code):
        """True if code is the current code (no try counted: only for refusing a 'new' code that's the old one)."""
        return self.is_set() and hmac.compare_digest(_hash(code, self.saved["salt"]), self.saved["hash"])

    def check_recovery(self, code, wall=None):
        """The 8-digit recovery code (same lock as the code). True = OK to make a new code."""
        return self.check(code, wall, key="recovery")

    def check(self, code, wall=None, key="hash"):
        """True if right. A wrong one counts toward the lock; while locked every code is refused."""
        wall = time.time() if wall is None else wall
        if not self.is_set() or self.locked_for(wall) > 0 or not self.saved.get(key):
            return False
        if hmac.compare_digest(_hash(code, self.saved["salt"]), self.saved[key]):
            if self.saved.get("wrong") or self.saved.get("locks"):
                self.saved["wrong"] = self.saved["locks"] = 0
                self._save()
            return True
        self.saved["wrong"] = self.saved.get("wrong", 0) + 1
        if self.saved["wrong"] >= self.tries:
            locks = self.saved.get("locks", 0)
            self.saved["locked_until"] = wall + min(300 * 2 ** locks, 7200)
            self.saved["locks"] = locks + 1
            self.saved["wrong"] = 0
            log.warning("maintenance code: %d wrong in a row, locked for %.0f min", self.tries,
                        self.locked_for(wall) / 60)
        self._save()
        return False

    def tries_left(self):
        return self.tries - self.saved.get("wrong", 0)


def boot_reset(directory, sim=False):
    """At start-up: a reset-code file on the SD card's boot drive forgets the code. True if it did."""
    files = [os.path.join(directory, "reset-code")] if sim else list(RESET_FILES)
    found = [f for f in files if os.path.exists(f)]
    if not found:
        return False
    try:
        os.remove(os.path.join(directory, FILE))
    except FileNotFoundError:
        pass
    for f in found:
        try:
            if sim:
                os.remove(f)
            else:                       # the boot drive belongs to root: a small helper deletes the file
                subprocess.run(["sudo", "-n", RESET_HELPER], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as e:
            log.error("can't delete %s: %s", f, e)
    log.warning("maintenance code forgotten (reset-code file on the SD card)")
    return True


def reset_cli(directory):
    path = os.path.join(directory, FILE)
    if not os.path.exists(path):
        print("No maintenance code is set.")
        return 0
    os.remove(path)
    print("Maintenance code removed. The dash asks for a new one the next time it's needed.")
    return 0

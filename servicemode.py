"""SERVICE WI-FI: the dash's own Wi-Fi network and service web page (web.py), turned on from the SYSTEM screen.

On:   SYSTEM screen > OK > OK (engine off). The Pi becomes a Wi-Fi hotspot (NetworkManager, through the small
      tools/bobcat-dash-wifi helper, allowed in sudoers) and starts the web page. The screen shows the network
      name, password and address (and a QR code to join, if python3-qrcode is installed).
      Turning it on asks for the maintenance code (maintcode.py), so not just anyone at the buttons can.
Off:  when its time runs out (minutes, 30; the web page's EXTEND adds extend_minutes each press, no limit),
      SYSTEM screen > OK > OK, the web page's button, or key-off. Afterwards NetworkManager goes back to your normal Wi-Fi by itself (if it's in range).

The password is [service_mode] password, or (when that's empty) one made up the first time and saved in the
data folder (service-wifi.json): it stays the same, so a phone that joined once joins again by itself.
In the simulator there's no hotspot: the web page runs on this computer, http://localhost:8080.
"""
import logging
import random
import subprocess
import threading
import time

from service import read_json, write_json

log = logging.getLogger("servicemode")

HELPER = "/usr/local/bin/bobcat-dash-wifi"
ADDRESS = "10.42.0.1"               # NetworkManager's address for a shared (hotspot) connection
LETTERS = "abcdefghjkmnpqrstuvwxyz23456789"     # no 0/o, 1/l/i: easy to read off the screen


class ServiceMode:
    OFF, STARTING, ON, STOPPING, FAILED = "off", "starting", "on", "stopping", "failed"

    def __init__(self, cfg, data_dir, sim=False):
        sc = cfg.get("service_mode", {})
        self.enabled = sc.get("enabled", True)
        self.on_s = sc.get("minutes", 30) * 60
        self.extend_s = sc.get("extend_minutes", 30) * 60
        self.ssid = sc.get("ssid", "MOSS-BOBCAT-M700")
        self.port = 8080 if sim else sc.get("port", 80)
        self.sim = sim
        self.dir = data_dir
        self.password = sc.get("password") or self._saved_password()
        self.state = self.OFF
        self.error = ""
        self.since = self.last_use = self.off_at = 0.0
        self.web = None
        self.web_ctx = None             # set by the dash (web.py's ctx)
        self.restart_requested = False
        self.off_reason = ""
        self._lock = threading.Lock()
        if not sim and self._helper("status").strip() == "on":     # on before a restart (software update)
            log.info("service Wi-Fi was already on: keeping it")
            self._start_web()
            self.state = self.ON
            self.since = self.last_use = time.monotonic()
            self.off_at = self.since + self.on_s

    def _saved_password(self):
        saved = read_json(self.dir, "service-wifi.json") or {}
        if saved.get("password"):
            return saved["password"]
        pw = "".join(random.SystemRandom().choice(LETTERS) for _ in range(10))
        try:
            write_json(self.dir, "service-wifi.json", {"password": pw})
        except OSError as e:
            log.error("can't save the Wi-Fi password: %s", e)
        return pw

    def _helper(self, *args):
        if self.sim:
            return "off"
        try:
            r = subprocess.run(["sudo", "-n", HELPER, *args], capture_output=True, text=True, timeout=45)
            if r.returncode:
                raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip()
                                   else f"exit {r.returncode}")
            return r.stdout
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RuntimeError(str(e))

    @property
    def address(self):
        host = "localhost" if self.sim else ADDRESS
        port = self.web.port if self.web else self.port
        return f"http://{host}" + ("" if port == 80 else f":{port}")

    def is_on(self):
        return self.state == self.ON

    def touch(self):
        self.last_use = time.monotonic()

    def extend(self):
        """The web page's EXTEND: extend_minutes more (from now if it was about to run out). No limit."""
        if self.state == self.ON:
            now = time.monotonic()
            self.off_at = max(self.off_at, now) + self.extend_s
            log.info("service Wi-Fi extended: off in %.0f min", (self.off_at - now) / 60)

    # -- on / off (in a thread: the hotspot takes a few seconds; the gauges keep running)

    def turn_on(self):
        with self._lock:
            if self.state in (self.STARTING, self.ON) or not self.enabled:
                return
            self.state, self.error = self.STARTING, ""
        threading.Thread(target=self._on, name="wifi-on", daemon=True).start()

    def _on(self):
        try:
            self._helper("on", self.ssid, self.password)
            if not self._start_web():
                raise RuntimeError("the web page couldn't start: " + (self.web.error if self.web else "?"))
            self.since = self.last_use = time.monotonic()
            self.off_at = self.since + self.on_s
            if self.web_ctx is not None:
                self.web_ctx["clients"] = {}
            self.state = self.ON
            log.info("service Wi-Fi on: %s, %s", self.ssid, self.address)
        except RuntimeError as e:
            log.error("service Wi-Fi didn't start: %s", e)
            self.error = str(e)
            try:
                self._helper("off")
            except RuntimeError:
                pass
            self.state = self.FAILED

    def _start_web(self):
        from web import WebServer
        self.web = WebServer(self.web_ctx, self.port)
        return self.web.start()

    def turn_off(self, reason="turned off"):
        with self._lock:
            if self.state not in (self.ON, self.FAILED):
                return
            self.state = self.STOPPING
        self.off_reason = reason
        threading.Thread(target=self._off, name="wifi-off", daemon=True).start()

    def _off(self):
        time.sleep(0.5)                 # let the web page's last answer go out
        if self.web:
            self.web.stop()
            self.web = None
        try:
            self._helper("off")
        except RuntimeError as e:
            log.error("service Wi-Fi off: %s", e)
        log.info("service Wi-Fi off (%s)", self.off_reason)
        self.state = self.OFF

    def update(self, now, key_on):
        """Every frame: the time limit and key-off."""
        if self.state == self.ON:
            if not key_on:
                self.turn_off("key off")
            elif now >= self.off_at:
                self.turn_off("time ran out")

    def devices(self, within=60.0):
        """Devices that used the web page in the last `within` seconds: ['iPhone · Safari (10.42.0.57)']."""
        clients = (self.web_ctx or {}).get("clients", {})
        now = time.monotonic()
        return [f"{dev} ({ip})" for ip, (dev, t) in sorted(clients.items(), key=lambda x: -x[1][1]) if now - t <= within]

    def minutes_left(self, now):
        if self.state != self.ON:
            return 0
        return max(0.0, self.off_at - now) / 60

    def describe(self, now):
        if self.state == self.ON:
            return f"ON, off in {self.minutes_left(now):.0f} min"
        if self.state == self.STARTING:
            return "starting..."
        if self.state == self.STOPPING:
            return "turning off..."
        if self.state == self.FAILED:
            return "FAILED: " + self.error
        return "OFF" + (f" ({self.off_reason})" if self.off_reason else "")

    def close(self):
        if self.web:
            self.web.stop()
            self.web = None
        if self.state in (self.ON, self.STARTING) and not self.restart_requested:
            try:
                self._helper("off")
            except RuntimeError:
                pass

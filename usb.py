"""USB stick: plug one into the pod's USB socket with the engine off and the dash
  1. copies everything worth keeping to SSOMS-BOBCAT-M700/<date>_<hours>h/ on the stick (the same files as the web
     page's "Everything" download: report.html, CSV files, settings, data backup, log),
  2. looks for a software update on the stick: a zip whose name starts with "bobcat-dash" in its top folder
     (GitHub's download is bobcat-dash-main.zip), checks it, and if it's good asks
     "INSTALL v1.2.0?" on the screen (OK = install, BACK = no),
  3. unmounts the stick and says when it's safe to pull it out.
The stick needs to be FAT32 or exFAT (how they come). A stick plugged in while the engine runs waits until
it stops. Plugged in for every visit: it only copies once per plugging in.

On the Pi the dash watches /dev/disk/by-id/usb-* and mounts through tools/bobcat-dash-usb (allowed in sudoers).
Simulator: a folder stands in for the stick, [usb] sim_dir (default ~/bobcat-dash-data/simulator/usb-stick):
make the folder = plug in, delete or rename it = pull out.
"""
import glob
import logging
import os
import re
import shutil
import subprocess
import threading
import time

import report
import updater

log = logging.getLogger("usb")

HELPER = "/usr/local/bin/bobcat-dash-usb"
MOUNT = "/mnt/bobcat-usb"
FOLDER = "SSOMS-BOBCAT-M700"


class UsbStick:
    NONE, WAITING, COPYING, DONE, FAILED, INSTALLING, INSTALLED = (
        "none", "waiting", "copying", "done", "failed", "installing", "installed")

    def __init__(self, cfg, data_dir, sim=False):
        uc = cfg.get("usb", {})
        self.enabled = uc.get("enabled", True)
        self.sim = sim
        self.sim_dir = os.path.expanduser(uc.get("sim_dir", os.path.join(data_dir, "usb-stick")))
        self.data_dir = data_dir
        self.state = self.NONE
        self.device = None             # what's plugged in now
        self.handled = None            # the device already copied (until it's pulled out)
        self.result = {}               # {"folder", "files", "update": check() info, "error"}
        self.notice = False            # something new for the screen
        self.export_ctx = None         # set by the dash: report.bundle()'s ctx
        self.repo = None
        self.restart = None            # set by the dash: call to restart into new software
        self._next_poll = 0.0

    # -- finding the stick

    def _present(self):
        if self.sim:
            return self.sim_dir if os.path.isdir(self.sim_dir) else None
        links = glob.glob("/dev/disk/by-id/usb-*")
        devs = sorted({os.path.realpath(p) for p in links})
        parts = [d for d in devs if re.search(r"\d$", d)]
        return parts[0] if parts else devs[0] if devs else None

    def _mount(self):
        if self.sim:
            return self.sim_dir
        r = subprocess.run(["sudo", "-n", HELPER, "mount", self.device], capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise RuntimeError((r.stderr or r.stdout).strip() or "couldn't mount the stick")
        return MOUNT

    def _unmount(self):
        if self.sim:
            return
        subprocess.run(["sudo", "-n", HELPER, "unmount"], capture_output=True, timeout=60)

    # -- every frame

    def update(self, now, key_on, running):
        if not self.enabled or now < self._next_poll:
            return
        self._next_poll = now + 2.0
        dev = self._present()
        if dev != self.device:
            self.device = dev
            if dev is None:            # pulled out
                if self.state not in (self.COPYING, self.INSTALLING):
                    self.state, self.handled, self.result = self.NONE, None, {}
                return
        if dev is None or dev == self.handled or self.state in (self.COPYING, self.INSTALLING):
            return
        if running or not key_on:
            if self.state != self.WAITING:
                self.state, self.notice = self.WAITING, True
            return
        self.handled = dev
        self.state, self.notice, self.result = self.COPYING, True, {}
        threading.Thread(target=self._copy, name="usb", daemon=True).start()

    def _copy(self):
        res = {"folder": "", "files": 0, "update": None, "error": "", "update_error": ""}
        mounted = False
        try:
            root = self._mount()
            mounted = True
            hours = self.export_ctx["hours"]()
            name = report.export_name(hours)
            dest = os.path.join(root, FOLDER, name)
            os.makedirs(dest, exist_ok=True)
            for fname, data in report.bundle(self.export_ctx).items():
                p = os.path.join(dest, fname)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as f:
                    f.write(data)
                res["files"] += 1
            res["folder"] = f"{FOLDER}/{name}"
            zips = sorted((z for z in glob.glob(os.path.join(root, "*.zip"))
                           if os.path.basename(z).lower().startswith("bobcat-dash")), key=os.path.getmtime)
            if zips:
                local = os.path.join(self.data_dir, "update-usb.zip")
                shutil.copyfile(zips[-1], local)
                try:
                    info = updater.check(local)
                    info["file"] = os.path.basename(zips[-1])
                    res["update"] = info
                except updater.UpdateError as e:
                    res["update_error"] = f"{os.path.basename(zips[-1])}: {e}"
            os.sync()
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            log.error("USB copy failed: %s", e)
            res["error"] = str(e)
        finally:
            if mounted:
                try:
                    self._unmount()
                except (OSError, subprocess.SubprocessError) as e:
                    res["error"] = res["error"] or f"unmount: {e}"
        log.info("USB stick: %s", res)
        self.result = res
        self.state = self.FAILED if res["error"] else self.DONE
        self.notice = True

    def install(self, running):
        """OK on the screen's INSTALL question."""
        if running or self.state != self.DONE or not self.result.get("update"):
            return
        self.state = self.INSTALLING
        threading.Thread(target=self._install, name="usb-install", daemon=True).start()

    def _install(self):
        local = os.path.join(self.data_dir, "update-usb.zip")
        try:
            info = updater.install(local, self.repo, self.data_dir)
            os.remove(local)
            self.result["installed"] = info["version"]
            self.state = self.INSTALLED
            time.sleep(3)              # "INSTALLED, restarting" on the screen for a moment
            if self.restart:
                self.restart()
        except (updater.UpdateError, OSError) as e:
            self.result["update_error"] = f"install failed: {e}"
            self.result["update"] = None
            self.state = self.DONE

    def skip_update(self):
        self.result["update"] = None
        try:
            os.remove(os.path.join(self.data_dir, "update-usb.zip"))
        except OSError:
            pass

    def describe(self):
        return {self.NONE: "none", self.WAITING: "waiting for engine off", self.COPYING: "copying...",
                self.DONE: "copied, OK to remove", self.FAILED: "FAILED: " + self.result.get("error", ""),
                self.INSTALLING: "installing update...", self.INSTALLED: "update installed"}[self.state]

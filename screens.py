"""The extra screens (menu buttons, breakout board rev 2.9): alarm HISTORY, SERVICE, SYSTEM, plus the
service pop-up at key-on. The gauges stay the home screen.

Buttons:  LEFT / RIGHT  change screen, or move through a list once you're in it
          OK            open the list / the highlighted line / confirm
          BACK          leave the list or pop-up; on a screen, back to the gauges. Hold 2 s: gauges from anywhere
SYSTEM:   OK opens SERVICE WI-FI (the dash's own Wi-Fi and service web page, servicemode.py / web.py).
          Turning it on, and installing software from a USB stick, ask for the maintenance code (maintcode.py).
USB stick: plugged in with the engine off, its pop-up opens by itself (usb.py).
Safety: a new red alarm always brings the gauges back, pop-ups never open by themselves with the engine running,
the clock and time zone are set with the engine off only (CLOCK says why), and
after home_after_s without a button press the dash goes back to the gauges on its own.
"""
import datetime
import os
import shutil
import socket
import time

import pygame

import settings
from maintcode import weak
from service import DUE, SOON, clock_valid
from pihealth import computer_model
from version import BOARD_REV, BUILD_DATE, SOURCE, VERSION

try:
    import qrcode                   # python3-qrcode: a code to scan to join the service Wi-Fi (optional)
except ImportError:
    qrcode = None

BG = (8, 11, 16)
PANEL = (22, 27, 35)
ROW = (30, 36, 46)
SEL = (52, 64, 82)
TEXT = (236, 239, 244)
DIM = (150, 158, 170)
GREEN = (34, 197, 94)
AMBER = (245, 166, 35)
RED = (239, 68, 68)
GRAY = (95, 103, 115)
BLUE = (59, 130, 246)
LEVEL_COLOR = {"alarm": RED, "warn": AMBER, "unknown": GRAY}
LEVEL_WORD = {"alarm": "ALARM", "warn": "WARNING", "unknown": "NO SIGNAL"}

PAGES = ("gauges", "history", "service", "system")
TITLES = {"gauges": "GAUGES", "history": "HISTORY", "service": "SERVICE", "system": "SYSTEM"}
# DETAILS first: an OK pressed without looking only shows the job, it never marks it done
# CLOSE first and selected; the rows stop at their ends (no wrap-round), so one stray press can't reach CLEAR ALL
EV_ACTIONS = (("close", "CLOSE"), ("clear", "CLEAR THIS"), ("all", "CLEAR ALL"))
SURE = ("NO", "YES")
CLOCK_FIELDS = (("YEAR", 2025, 2099), ("MONTH", 1, 12), ("DAY", 1, 31), ("HOUR", 0, 23), ("MINUTE", 0, 59))
CLOCK_SETTING = ("clockset", "clocksure", "tzpick", "tzsure")
CLOCK_WHY = ("to set the clock", "to change the time zone")
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")           # "are you sure?" pop-ups: NO is selected; YES needs a deliberate arrow press
ACTIONS = (("info", "DETAILS"), ("done", "MARK DONE"), ("later", "LATER"), ("later5", "+5 HOURS"), ("hist", "COMPLETED"))


def when(t, fmt="%b %d %Y  %H:%M"):
    return time.strftime(fmt, time.localtime(t)) if t and clock_valid(t) else "date not set"


def dur(s):
    if s is None:
        return "still on"
    s = int(round(s))
    return f"{s} s" if s < 60 else f"{s // 60} min {s % 60:02d} s" if s < 3600 else f"{s // 3600} h {s % 3600 // 60:02d} min"


def hours_left(left, days, window=5.0):
    if left <= 0:
        txt, col = f"OVERDUE {-left:.1f} h", RED
    elif left <= window:
        txt, col = f"in {left:.1f} h", AMBER
    else:
        txt, col = f"in {left:.0f} h", GREEN
    if days is not None:
        if days <= 0:
            txt, col = f"OVERDUE {-days:.0f} days" if left > 0 else txt, RED
        elif days <= 14 and col == GREEN:
            txt, col = f"in {days:.0f} days", AMBER
    return txt, col


class Screens:
    def __init__(self, cfg):
        bc = cfg.get("buttons", {})
        self.home_after = bc.get("home_after_s", 120)
        self.page = "gauges"
        self.listing = False         # inside a list (LEFT / RIGHT move the highlight)
        self.cursor = 0
        self.modal = None            # pop-up: dict with "kind"
        self.last_press = 0.0
        self._sys_cache = (0.0, {})
        self.locked = False          # an alarm nobody has silenced yet: menus locked, gauges only
        self.archive = False         # HISTORY: showing ALL ALARMS (the archive, cleared ones included)
        self._qr = (None, None)      # (text, surface)

    # -- input

    def go_home(self):
        self.page, self.listing, self.cursor, self.modal, self.archive = "gauges", False, 0, None, False

    def announce(self, items, now):
        """Key-on service pop-up: one item at a time, its actions underneath."""
        self.modal = {"kind": "announce", "items": list(items), "i": 0, "act": 0}
        self.last_press = now

    def press(self, b, ctx, now):
        """b: left / right / ok / back / home. ctx: {"service", "events", "hours"}."""
        self.last_press = now
        if self.locked:              # SILENCE first: no screen changes while an alarm is unanswered
            return
        if b == "home":
            self.go_home()
            return
        if self.modal:
            self._modal_press(b, ctx)
            return
        n = self._list_len(ctx)
        if self.listing:
            if b == "left":
                self.cursor = (self.cursor - 1) % max(n, 1)
            elif b == "right":
                self.cursor = (self.cursor + 1) % max(n, 1)
            elif b == "back":
                self.listing = False
            elif b == "ok":
                self._open(ctx)
            return
        i = PAGES.index(self.page)
        if b == "left":
            self.page, self.cursor, self.archive = PAGES[(i - 1) % len(PAGES)], 0, False
        elif b == "right":
            self.page, self.cursor, self.archive = PAGES[(i + 1) % len(PAGES)], 0, False
        elif b == "back" and self.archive:
            self.archive, self.cursor = False, 0          # ALL ALARMS -> back to the history list
        elif b == "back":
            self.go_home()
        elif b == "ok" and self.page in ("history", "service") and n:
            self.listing, self.cursor = True, 0
        elif b == "ok" and self.page == "system":
            self.modal = {"kind": "sysmenu", "act": 0}

    def _list_len(self, ctx):
        if self.page == "history":
            ev = ctx["events"]
            return len(ev.archive()) if self.archive else 1 + len(ev.newest_first())   # + the ALL ALARMS line
        if self.page == "service":
            return 1 + len(ctx["service"].items)          # climate setting + the items
        return 0

    def _open(self, ctx):
        svc = ctx["service"]
        if self.page == "history":
            if self.archive:
                evs = ctx["events"].archive()
                if self.cursor < len(evs):
                    self.modal = {"kind": "event", "ev": evs[self.cursor], "archive": True, "act": 0}
            elif self.cursor == 0:                        # the ALL ALARMS line
                self.archive, self.listing, self.cursor = True, False, 0
            else:
                evs = ctx["events"].newest_first()
                if self.cursor - 1 < len(evs):
                    self.modal = {"kind": "event", "ev": evs[self.cursor - 1], "archive": False, "act": 0}
        elif self.page == "service":
            if self.cursor == 0:
                ids = [c["id"] for c in svc.climates]
                self.modal = {"kind": "climate", "i": ids.index(svc.climate) if svc.climate in ids else 0}
            else:
                rows = svc.status(ctx["hours"])
                it, state, left, days = rows[self.cursor - 1]
                self.modal = {"kind": "actions", "items": [(it, state, left, days)], "i": 0, "act": 0}

    def _modal_press(self, b, ctx):
        m, svc, hours = self.modal, ctx["service"], ctx["hours"]
        k = m["kind"]
        if k in ("announce", "actions"):
            if b in ("left", "right"):
                m["act"] = max(0, min(len(ACTIONS) - 1, m["act"] + (1 if b == "right" else -1)))
            elif b == "back":
                if k == "announce":         # closing the pop-up = ask again at the next key-on
                    for it, *_ in m["items"][m["i"]:]:
                        svc.later(it["id"], hours, next_start=True)
                self.modal = None
            elif b == "ok":
                it = m["items"][m["i"]][0]
                act = ACTIONS[m["act"]][0]
                if act == "done":
                    self._need_code(ctx, "to mark service done",
                                    lambda: setattr(self, "modal", {"kind": "confirm", "item": it, "back": m, "sel": 0}), m)
                    return
                if act == "hist":
                    self.modal = {"kind": "completed", "item": it, "back": m}
                    return
                if act == "info":
                    self.modal = {"kind": "details", "item": it, "back": m}
                    return
                svc.later(it["id"], hours, next_start=(act == "later"))
                self._next_item(m)
        elif k in ("confirm", "clear_one", "clear_all"):       # "are you sure?": NO unless YES is picked
            if b in ("left", "right"):
                m["sel"] = 1 if b == "right" else 0
            elif b == "back" or (b == "ok" and m["sel"] == 0):
                self.modal = m["back"]
                if self.modal and self.modal.get("kind") == "event":
                    self.modal["act"] = 0              # backed out: the highlight goes back to CLOSE
            elif b == "ok" and k == "confirm":
                svc.mark_done(m["item"]["id"], hours)
                self.modal = m["back"]
                self._next_item(self.modal)
            elif b == "ok" and k == "clear_one":
                ctx["events"].clear(m["ev"])
                self.modal = None
                self.cursor = min(self.cursor, len(ctx["events"].newest_first()))
                if self.cursor == 0:
                    self.listing = False
            elif b == "ok" and k == "clear_all":
                ctx["events"].clear_all()
                self.modal, self.listing, self.cursor = None, False, 0
        elif k in ("completed", "details"):
            if b in ("back", "ok"):
                self.modal = m["back"]
        elif k == "climate":
            n = len(svc.climates)
            if b in ("left", "right") and n:
                m["i"] = (m["i"] + (1 if b == "right" else -1)) % n
            elif b == "ok" and n:
                cid = svc.climates[m["i"]]["id"]
                if cid == svc.climate:                     # unchanged: nothing to save
                    self.modal = None
                    return

                def save():
                    svc.set_climate(cid)
                    self.modal = None
                self._need_code(ctx, "to change the climate setting", save, m)
            elif b == "back":
                self.modal = None
        elif k == "event":
            if m["archive"] or b == "back":
                self.modal = None
            elif b in ("left", "right"):
                m["act"] = max(0, min(len(EV_ACTIONS) - 1, m["act"] + (1 if b == "right" else -1)))
            elif b == "ok":
                act = EV_ACTIONS[m["act"]][0]
                if act == "clear":
                    self._need_code(ctx, "to clear alarms",
                                    lambda: setattr(self, "modal", {"kind": "clear_one", "ev": m["ev"], "back": m, "sel": 0}), m)
                elif act == "all":
                    self._need_code(ctx, "to clear alarms",
                                    lambda: setattr(self, "modal", {"kind": "clear_all", "back": m, "sel": 0}), m)
                else:
                    self.modal = None
        elif k == "sysmenu":
            if b in ("left", "right"):
                m["act"] = max(0, min(4, m["act"] + (1 if b == "right" else -1)))
                m.pop("msg", None)
            elif b == "back":
                self.modal = None
            elif b == "ok" and m["act"] == 0:
                self.modal = {"kind": "wifi", "back": m}
            elif b == "ok" and m["act"] == 1:
                settings.set_units("C" if settings.units() == "F" else "F")
            elif b == "ok" and m["act"] == 2:
                self.modal = {"kind": "clock", "back": m, "act": 0}
            elif b == "ok" and m["act"] == 3:
                self._change_code(ctx, m)
            elif b == "ok" and m["act"] == 4:
                self.modal = {"kind": "about", "back": m}
        elif k == "about":
            if b in ("ok", "back"):
                self.modal = m["back"]
        elif k == "clock":
            if b in ("left", "right"):
                m["act"] = max(0, min(2, m.get("act", 0) + (1 if b == "right" else -1)))
            elif b == "back":
                self.modal = m["back"]
            elif b == "ok" and m.get("act") == 2:                                   # 12 / 24 HOUR
                settings.set_clock_fmt("24h" if settings.clock_fmt() == "12h" else "12h")
            elif b == "ok" and ctx["st"]["running"]:              # SET TIME / TIME ZONE: engine off only
                m["msg"] = "Stop the engine first to set the time or the time zone."
            elif b == "ok" and m.get("act") == 1:                 # TIME ZONE
                names = [z for z, _ in settings.TIME_ZONES]
                cur = settings.zone_name()
                picker = {"kind": "tzpick", "back": m, "i": names.index(cur) if cur in names else 0}
                self._need_code(ctx, "to change the time zone", lambda: setattr(self, "modal", picker), m)
            elif b == "ok":                                      # SET TIME: by hand
                t = time.localtime() if clock_valid() else time.localtime(time.mktime((2026, 1, 1, 12, 0, 0, 0, 0, -1)))
                setter = {"kind": "clockset", "back": m, "f": 0,
                          "v": [t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min]}
                self._need_code(ctx, "to set the clock", lambda: setattr(self, "modal", setter), m)
        elif k == "clockset":
            lo, hi = CLOCK_FIELDS[m["f"]][1], CLOCK_FIELDS[m["f"]][2]
            if m["f"] == 2:                                      # days in that month
                y, mo = m["v"][0], m["v"][1]
                hi = (datetime.date(y + mo // 12, mo % 12 + 1, 1) - datetime.timedelta(days=1)).day
            if b in ("left", "right"):
                v = m["v"][m["f"]] + (1 if b == "right" else -1)
                m["v"][m["f"]] = lo + (v - lo) % (hi - lo + 1)
            elif b == "back":
                if m["f"]:
                    m["f"] -= 1
                else:
                    self.modal = m["back"]
            elif b == "ok":
                if m["f"] < len(CLOCK_FIELDS) - 1:
                    m["f"] += 1
                    y, mo = m["v"][0], m["v"][1]                 # a 31st carried into a shorter month
                    last = (datetime.date(y + mo // 12, mo % 12 + 1, 1) - datetime.timedelta(days=1)).day
                    m["v"][2] = min(m["v"][2], last)
                else:
                    self.modal = {"kind": "clocksure", "back": m, "sel": 0, "v": list(m["v"])}
        elif k == "tzpick":
            n = len(settings.TIME_ZONES)
            if b in ("left", "right"):
                m["i"] = (m["i"] + (1 if b == "right" else -1)) % n
            elif b == "back":
                self.modal = m["back"]
            elif b == "ok":
                self.modal = {"kind": "tzsure", "back": m, "sel": 0, "zone": settings.TIME_ZONES[m["i"]]}
        elif k == "tzsure":
            if b in ("left", "right"):
                m["sel"] = 1 if b == "right" else 0
            elif b == "back" or (b == "ok" and m["sel"] == 0):
                self.modal = m["back"]
            elif b == "ok" and ctx["st"]["running"]:
                self.modal = self._clock_modal(m)
            elif b == "ok":
                ok_, msg = ctx["set_clock"](None, m["zone"][0])
                if ok_:
                    ctx["events"].note("CLOCK", "warn", f"time zone set to {m['zone'][0]} on the dash", ctx["hours"])
                self.modal = {"kind": "clockdone", "ok": ok_, "msg": msg, "back": m["back"]["back"]}
        elif k == "clocksure":
            if b in ("left", "right"):
                m["sel"] = 1 if b == "right" else 0
            elif b == "back" or (b == "ok" and m["sel"] == 0):
                self.modal = m["back"]
            elif b == "ok" and ctx["st"]["running"]:
                self.modal = self._clock_modal(m)
            elif b == "ok":
                y, mo, dd, hh, mi = m["v"]
                ok_, msg = ctx["set_clock"](time.mktime((y, mo, dd, hh, mi, 0, 0, 0, -1)))
                if ok_:
                    ctx["events"].note("CLOCK", "warn", "set by hand on the dash", ctx["hours"])
                self.modal = {"kind": "clockdone", "ok": ok_, "msg": msg, "back": m["back"]["back"]}
        elif k == "clockdone":
            if b in ("ok", "back"):
                self.modal = m["back"]
        elif k == "wifi":
            sm, running = ctx["svcmode"], ctx["st"]["running"]
            if b == "back":
                self.modal = m.get("back")
            elif b == "ok" and sm.state == sm.ON:
                sm.turn_off("turned off on the dash")
            elif b == "ok" and sm.state in (sm.OFF, sm.FAILED) and not running:
                if sm.state == sm.FAILED:
                    sm.state = sm.OFF
                def wifi_on():
                    sm.turn_on()
                    self.modal = {"kind": "wifi"}
                self._need_code(ctx, "to turn on SERVICE WI-FI", wifi_on, m)
        elif k == "usb":
            usb, running = ctx["usb"], ctx["st"]["running"]
            update = usb.state == usb.DONE and usb.result.get("update")
            if b == "ok" and update and not running:
                def install():
                    usb.install(ctx["st"]["running"])
                    self.modal = {"kind": "usb"}
                self._need_code(ctx, "to install the software update", install, m)
            elif b in ("ok", "back") and usb.state not in (usb.INSTALLED,):
                if b == "back" and update:
                    usb.skip_update()
                self.modal = None
        elif k == "code":
            self._code_press(b, ctx)
        elif k == "codechg":                    # "you're changing the code": OK goes on, BACK keeps the old one
            if b == "ok":
                self.modal = self._code_modal("new", "", None, m["back"], change=True)
            elif b == "back":
                self.modal = m["back"]
        elif k == "codeshow":                   # the new code on screen: is it right? NO is selected
            if b in ("left", "right"):
                m["sel"] = 1 if b == "right" else 0
            elif b == "back":
                self.modal = m["back"]
            elif b == "ok" and m["sel"] == 0:
                self.modal = self._code_modal("new", "", None, m["back"], change=True)
                self.modal["msg"] = ("Not saved. Enter the new code again.", AMBER)
            elif b == "ok" and ctx["st"]["running"]:
                m["back"]["msg"] = "Stop the engine first to change the maintenance code."
                self.modal = m["back"]
            elif b == "ok":
                ctx["code"].change(m["new"])
                ctx["code"].unlocked = True
                ctx["events"].note("MAINTENANCE CODE", "warn", "changed on the dash", ctx["hours"])
                self.modal = {"kind": "codedone", "back": m["back"]}
        elif k == "codedone":
            if b in ("ok", "back"):
                self.modal = m["back"]
        elif k == "recovery":
            if b == "ok":
                m["then"]()

    @staticmethod
    def _clock_modal(m):
        """From a clock-setting pop-up back to the CLOCK pop-up, saying why (the engine started)."""
        while m and m.get("kind") != "clock":
            m = m.get("back")
        if m:
            m["msg"] = "Stop the engine first to set the time or the time zone."
        return m

    # -- the maintenance code

    def _need_code(self, ctx, why, then, back):
        """Run then() if the code was entered since key-on (and the engine hasn't run since); otherwise ask
        for it first. back: the pop-up to return to on cancel."""
        code = ctx["code"]
        if code.unlocked:
            then()
            return
        self.modal = self._code_modal("enter" if code.is_set() else "new", why, then, back)

    @staticmethod
    def _code_modal(mode, why, then, back, change=False):
        return {"kind": "code", "why": why, "then": then, "back": back, "mode": mode, "got": [], "val": 0,
                "first": None, "msg": None, "change": change}

    def _change_code(self, ctx, menu):
        """SYSTEM > MX CODE: the old code (always asked, even if entered already), a "you're changing it" screen,
        the new code twice, then the new code on screen to check before it's saved. Engine off only."""
        code = ctx["code"]
        if ctx["st"]["running"]:
            menu["msg"] = "Stop the engine first to change the maintenance code."
        elif not code.is_set():                  # no code yet: making one is the same as the first time
            self._need_code(ctx, "", lambda: setattr(self, "modal", menu), menu)
        else:
            self.modal = self._code_modal("enter", "to change the code", lambda: setattr(
                self, "modal", {"kind": "codechg", "back": menu}), menu)

    def _code_len(self, m, code):
        return 8 if m["mode"] == "recover" else code.digits

    def _code_ok(self, m, ctx):
        ctx["code"].unlocked = True
        m["then"]()

    def _code_press(self, b, ctx):
        m, code = self.modal, ctx["code"]
        if m["mode"] in ("enter", "recover") and code.locked_for() > 0:
            if b == "back":
                self.modal = m["back"]
            return
        if b in ("left", "right"):
            top = 11 if m["mode"] == "enter" and not m["got"] else 10     # 10 = "?" (forgot the code)
            m["val"] = (m["val"] + (1 if b == "right" else -1)) % top
            return
        if b == "back":
            if m["got"]:
                m["val"] = m["got"].pop()
            elif m["mode"] == "recover":
                m.update(mode="enter", val=0, msg=None)
            else:
                self.modal = m["back"]
            return
        if b != "ok":
            return
        if m["val"] == 10:                     # "?": enter the recovery code instead
            m.update(mode="recover", val=0, got=[], msg=None)
            return
        m["got"].append(m["val"])
        m["val"], m["msg"] = 0, None
        if len(m["got"]) < self._code_len(m, code):
            return
        entered = "".join(map(str, m["got"]))
        m["got"] = []
        if m["mode"] == "new":
            why = weak(entered)
            if not why and m.get("change") and code.same(entered):
                why = "That's the code now. Pick a different one."
            if why:
                m["msg"] = (why, RED)
            else:
                m["first"], m["mode"] = entered, "confirm"
        elif m["mode"] == "confirm":
            if entered == m["first"] and m.get("change"):
                self.modal = {"kind": "codeshow", "new": entered, "sel": 0, "back": m["back"]}
            elif entered == m["first"]:
                recovery = code.set(entered)
                code.unlocked = True
                self.modal = {"kind": "recovery", "code": recovery, "then": m["then"]}
            else:
                m["mode"], m["first"], m["msg"] = "new", None, ("The two didn't match. Start again.", RED)
        elif m["mode"] == "recover":
            if code.check_recovery(entered):
                ctx["events"].note("MAINTENANCE CODE", "warn", "reset with the recovery code", ctx["hours"])
                if m["why"] == "to change the code":     # the new code is made right here: no second change after
                    m["then"] = lambda back=m["back"]: setattr(self, "modal", back)
                m.update(mode="new", msg=("Recovery code accepted. Make a new code.", GREEN))
            else:
                self._wrong(m, ctx, "wrong recovery code")
        elif code.check(entered):
            self._code_ok(m, ctx)
        else:
            self._wrong(m, ctx, "wrong code")

    def _wrong(self, m, ctx, what):
        code = ctx["code"]
        locked = code.locked_for()
        ctx["events"].note("MAINTENANCE CODE", "warn", what + (", locked" if locked else ""), ctx["hours"])
        m["msg"] = (f"{what.upper()}. Locked for {locked / 60:.0f} min." if locked else
                    f"{what.upper()}. {code.tries_left()} more {'try' if code.tries_left() == 1 else 'tries'}, "
                    f"then it locks.", RED)

    def _draw_code(self, d, ctx):
        m, code = self.modal, ctx["code"]
        box = self._box(d, 800, 470, AMBER)
        title = {"enter": "MAINTENANCE CODE", "new": "MAKE A MAINTENANCE CODE", "confirm": "ENTER IT AGAIN",
                 "recover": "RECOVERY CODE"}[m["mode"]]
        if m.get("change"):
            title = {"new": "NEW MAINTENANCE CODE", "confirm": "NEW CODE AGAIN"}.get(m["mode"], title)
        elif m["mode"] == "enter" and m["why"] == "to change the code":
            title = "OLD MAINTENANCE CODE"
        d.text(title, 40, AMBER, midtop=(box.centerx, box.y + d.px(20)))
        sub = {"enter": f"{code.digits} digits, {m['why']}",
               "new": f"Pick {code.digits} digits (not all the same, not in a row)",
               "confirm": "The same code again, to be sure",
               "recover": "The 8 digits shown when the code was made"}[m["mode"]]
        d.text(sub, 26, DIM, max_w=box.w - d.px(40), midtop=(box.centerx, box.y + d.px(76)))
        locked = code.locked_for() if m["mode"] in ("enter", "recover") else 0
        n = self._code_len(m, code)
        w, gap = (84, 18) if n <= 6 else (68, 10)
        x0 = box.centerx - d.px((n * w + (n - 1) * gap) / 2)
        y0 = box.y + d.px(130)
        for i in range(n):
            r = pygame.Rect(x0 + d.px(i * (w + gap)), y0, d.px(w), d.px(104))
            cur = i == len(m["got"]) and not locked
            pygame.draw.rect(d.screen, SEL if cur else ROW, r, border_radius=d.px(10))
            if cur:
                pygame.draw.rect(d.screen, TEXT, r, width=d.px(3), border_radius=d.px(10))
                d.text("?" if m["val"] == 10 else str(m["val"]), 64, AMBER if m["val"] == 10 else TEXT, center=r.center)
            elif i < len(m["got"]):
                pygame.draw.circle(d.screen, TEXT, r.center, d.px(12))
        if locked:
            msg = (f"Too many wrong codes. Try again in {int(locked // 60)}:{int(locked % 60):02d}", RED)
        elif m["val"] == 10:
            msg = ("Forgot the code?  OK = enter the 8-digit recovery code", AMBER)
        else:
            msg = m["msg"] or ("Arrows change the digit.  OK = next digit,  BACK = previous", DIM)
        d.text(msg[0], 28, msg[1], max_w=box.w - d.px(40), midtop=(box.centerx, box.y + d.px(270)))
        if m["mode"] == "enter" and not locked and m["val"] != 10:
            d.text("Forgot it?  Arrow the first digit to  ?  and press OK", 22, DIM,
                   midtop=(box.centerx, box.y + d.px(320)))
        hints = [("back", "cancel")] if locked else [("lr", "digit"), ("ok", "next"), ("back", "back")]
        self._hints(d, hints, box.bottom - d.px(32), right=box.right - d.px(24))

    def _draw_about(self, d, ctx):
        """SYSTEM > ABOUT: the patch, the system's name, the software and board versions, the computer."""
        box = self._box(d, 960, 600, TEXT)
        patch = d.logo(250, big=True) if hasattr(d, "logo") else None
        if patch:
            d.screen.blit(patch, patch.get_rect(midleft=(box.x + d.px(30), box.centery - d.px(16))))
        x = box.x + d.px(310)
        y = box.y + d.px(34)
        d.text(d.name if hasattr(d, "name") else "M.O.S.S.", 52, TEXT, topleft=(x, y))
        d.text("Maintenance, Operations, and Service System", 26, DIM, topleft=(x, y + d.px(64)))
        d.text("Bobcat M700 skid steer (1978)  -  Project Moon Pi", 26, DIM, topleft=(x, y + d.px(98)))
        sm = ctx.get("svcmode")
        rows = [("Software", f"v{VERSION}  ({BUILD_DATE})"), ("Breakout board", f"rev {BOARD_REV}"),
                ("Computer", computer_model()), ("Engine hours", f"{ctx['hours']:.1f} h"),
                ("Service Wi-Fi", sm.ssid if sm else "-"), ("Source", f"{SOURCE}  (MIT licence)")]
        for i, (a, v) in enumerate(rows):
            ry = y + d.px(160 + 46 * i)
            d.text(a, 26, DIM, topleft=(x, ry))
            d.text(v, 28, TEXT, max_w=box.right - x - d.px(220), topleft=(x + d.px(200), ry - d.px(1)))
        d.text("Display font B612 (designed for Airbus cockpits, SIL Open Font License)", 22, DIM,
               midbottom=(box.centerx, box.bottom - d.px(70)))
        self._hints(d, [("back", "close")], box.bottom - d.px(32), right=box.right - d.px(24))

    def _draw_recovery(self, d, ctx):
        box = self._box(d, 820, 460, GREEN)
        d.text("CODE SAVED", 40, GREEN, midtop=(box.centerx, box.y + d.px(20)))
        d.text("Write down this RECOVERY CODE and keep it with the machine's papers:", 28, TEXT,
               max_w=box.w - d.px(40), midtop=(box.centerx, box.y + d.px(84)))
        rc = self.modal["code"]
        d.text(f"{rc[:4]}  {rc[4:]}", 80, AMBER, midtop=(box.centerx, box.y + d.px(140)))
        self._wrap(d, "If you forget the maintenance code, it lets you make a new one: on the code screen, arrow the "
                      "first digit to ? and press OK. It's shown only this once.", box, box.y + d.px(260), 26, DIM, 3)
        self._hints(d, [("ok", "I wrote it down")], box.bottom - d.px(32), right=box.right - d.px(24))

    def _next_item(self, m):
        m["i"] += 1
        m["act"] = 0
        if m["i"] >= len(m["items"]):
            self.modal = None

    def tick(self, now, new_alarm, running, ctx=None):
        """Back to the gauges on a new alarm or after a while without presses. No pop-up while running."""
        usb = ctx.get("usb") if ctx else None
        busy = usb and usb.state in (usb.COPYING, usb.INSTALLING, usb.INSTALLED)
        if new_alarm or (self.page != "gauges" or self.modal) and now - self.last_press > self.home_after and not busy:
            self.go_home()
        if running and self.modal and self.modal["kind"] in ("announce", "usb"):
            self.modal = None
        m = self.modal
        if running and m and (m["kind"] in CLOCK_SETTING or m["kind"] == "code" and m["why"] in CLOCK_WHY):
            self.modal = self._clock_modal(m)            # the clock is set with the engine off
        elif running and m and (m["kind"] in ("codechg", "codeshow") or m["kind"] == "code" and
                                (m.get("change") or m["why"] == "to change the code")):
            self.modal = m["back"]                       # the code is changed with the engine off
            self.modal["msg"] = "Stop the engine first to change the maintenance code."
        if usb and usb.notice and not running and not self.locked and not self.modal:
            usb.notice = False
            if usb.state != usb.WAITING:
                self.modal = {"kind": "usb"}
                self.last_press = now

    # -- drawing helpers

    def _tri(self, d, x, y, size, direction, color):
        s = d.px(size)
        if direction == "left":
            pts = [(x, y), (x + s, y - s), (x + s, y + s)]
        else:
            pts = [(x + s, y), (x, y - s), (x, y + s)]
        pygame.draw.polygon(d.screen, color, pts)

    def _hints(self, d, items, y, right=None):
        """Button hints: [("lr" | "ok" | "back", text)], drawn right to left from `right` (default: screen edge)."""
        x = d.R(1006, 0, 0, 0).x if right is None else right
        for key, text in reversed(items):
            t = d.font(24).render(text, True, DIM)
            x -= t.get_width()
            d.screen.blit(t, t.get_rect(midleft=(x, y)))
            x -= d.px(10)
            if key == "lr":
                self._tri(d, x - d.px(10), y, 8, "right", TEXT)
                self._tri(d, x - d.px(30), y, 8, "left", TEXT)
                x -= d.px(34)
            else:
                cap = d.font(22).render("OK" if key == "ok" else "BACK", True, BG)
                r = cap.get_rect().inflate(d.px(14), d.px(6))
                r.midright = (x, y)
                pygame.draw.rect(d.screen, TEXT, r, border_radius=d.px(5))
                d.screen.blit(cap, cap.get_rect(center=r.center))
                x = r.left
            x -= d.px(26)
        return x + d.px(26)                 # left end of the hints

    def draw_bar(self, d):
        """Screen tabs along the bottom, and what the buttons do here."""
        bar = d.R(0, 716, 1024, 52)
        pygame.draw.rect(d.screen, PANEL, bar)
        x = d.R(14, 0, 0, 0).x
        for p in PAGES:
            on = p == self.page
            t = d.font(24).render(TITLES[p], True, BG if on else DIM)
            r = t.get_rect().inflate(d.px(18), d.px(10))
            r.midleft = (x, bar.centery)
            if on:
                pygame.draw.rect(d.screen, TEXT, r, border_radius=d.px(6))
            d.screen.blit(t, t.get_rect(center=r.center))
            x = r.right + d.px(6)
        self._bar_pills = (x, bar.centery)
        if self.locked:
            msg = d.font(28).render("ALARM:  press SILENCE to use the menu", True, BG)
            r = msg.get_rect().inflate(d.px(24), d.px(10))
            r.midright = (d.R(1010, 0, 0, 0).x, bar.centery)
            pygame.draw.rect(d.screen, RED, r, border_radius=d.px(6))
            d.screen.blit(msg, msg.get_rect(center=r.center))
            self._bar_right = r.left
            return
        if self.page == "gauges":
            hints = [("lr", "other screens")]
        elif self.listing:
            hints = [("lr", "move"), ("ok", "open"), ("back", "done")]
        elif self.archive:
            hints = [("lr", "screen"), ("ok", "select"), ("back", "history")]
        elif self.page in ("history", "service"):
            hints = [("lr", "screen"), ("ok", "select"), ("back", "gauges")]
        elif self.page == "system":
            hints = [("lr", "screen"), ("ok", "settings"), ("back", "gauges")]
        else:
            hints = [("lr", "screen"), ("back", "gauges")]
        self._bar_right = self._hints(d, hints, bar.centery)

    def _draw_pills(self, d, ctx):
        """WI-FI 27 min / USB ... next to the screen tabs, while they're on."""
        x, cy = getattr(self, "_bar_pills", (0, 0))
        sm, usb = ctx.get("svcmode"), ctx.get("usb")
        pills = []
        if sm and sm.state in (sm.ON, sm.STARTING, sm.STOPPING):
            pills.append((f"WI-FI {sm.minutes_left(ctx['now']):.0f}m" if sm.state == sm.ON else "WI-FI ...", BLUE))
        if usb and usb.state != usb.NONE:
            pills.append(({usb.WAITING: "USB WAIT", usb.COPYING: "USB ...", usb.DONE: "USB OK",
                           usb.FAILED: "USB FAILED", usb.INSTALLING: "UPDATING", usb.INSTALLED: "UPDATED"}[usb.state],
                          RED if usb.state == usb.FAILED else BLUE))
        code = ctx.get("code")
        if code and code.unlocked:
            pills.append(("MX UNLOCKED", GREEN))
        for text, col in pills:
            t = d.font(22).render(text, True, TEXT)
            r = t.get_rect().inflate(d.px(14), d.px(8))
            r.midleft = (x + d.px(8), cy)
            pygame.draw.rect(d.screen, col, r, border_radius=d.px(6))
            d.screen.blit(t, t.get_rect(center=r.center))
            x = r.right
        self._draw_clock(d, x, getattr(self, "_bar_right", x), cy)

    def _draw_clock(self, d, left, right, cy):
        """Day, date and time in the menu bar's free space (just the time when the date doesn't fit)."""
        if settings.clock_fmt() == "off" or right - left < d.px(90):
            return
        if not clock_valid():
            choices = [("CLOCK NOT SET", 26, AMBER), ("NO CLOCK", 24, AMBER)]
        else:
            now = time.localtime()
            tm = settings.hhmm(now)
            full = time.strftime("%a %b ", now) + f"{now.tm_mday} {now.tm_year}  ·  " + tm
            choices = [(full, 26, TEXT), (full, 23, TEXT), (full, 21, TEXT), (time.strftime("%b ", now) + f"{now.tm_mday} {now.tm_year}  ·  " + tm, 23, TEXT),
                       (tm, 26, TEXT)]
        for text, size, col in choices:
            t = d.font(size).render(text, True, col)
            if t.get_width() <= right - left - d.px(36):
                d.screen.blit(t, t.get_rect(center=((left + right) // 2, cy)))
                return

    def _rows(self, d, top, rows, row_h, render):
        """A scrolling list: rows drawn by render(rect, row, selected), the highlight kept in view."""
        area_h = 700 - top
        per = max(1, int(area_h // row_h))
        first = 0
        if self.listing and self.cursor >= per:
            first = self.cursor - per + 1
        for k, row in enumerate(rows[first:first + per]):
            idx = first + k
            rect = d.R(14, top + k * row_h, 996, row_h - 6)
            sel = self.listing and idx == self.cursor
            pygame.draw.rect(d.screen, SEL if sel else ROW, rect, border_radius=d.px(8))
            if sel:
                pygame.draw.rect(d.screen, TEXT, rect, width=d.px(2), border_radius=d.px(8))
            render(rect, row, sel)
        if len(rows) > per:
            d.text(f"{first + 1}-{min(first + per, len(rows))} of {len(rows)}", 22, DIM,
                   topright=d.R(1010, top - 30, 0, 0).topleft)

    # -- the screens

    def draw(self, d, ctx):
        """Draws the current non-gauge screen (below the header) and any pop-up."""
        if self.page != "gauges":
            pygame.draw.rect(d.screen, (8, 11, 16), d.R(0, 56, 1024, 660))
            getattr(self, "draw_" + self.page)(d, ctx)
        self.draw_bar(d)                  # on every screen, the gauges too
        self._draw_pills(d, ctx)
        if self.modal:
            self.draw_modal(d, ctx)
        code = ctx.get("code")
        if code and code.unlocked:        # maintenance code entered: a green frame round the whole screen
            pygame.draw.rect(d.screen, GREEN, d.screen.get_rect(), width=max(3, d.px(5)))

    def draw_history(self, d, ctx):
        log = ctx["events"]
        allev = log.archive()

        def render_ev(rect, ev, sel):
            cleared = ev.get("cleared")
            col = LEVEL_COLOR.get(ev["level"], GRAY)
            pygame.draw.rect(d.screen, GRAY if cleared else col, (rect.x, rect.y, d.px(10), rect.h),
                             border_top_left_radius=d.px(8), border_bottom_left_radius=d.px(8))
            cy = rect.centery
            ink = DIM if cleared else TEXT
            d.text(when(ev.get("t"), "%b %d  %H:%M"), 26, ink, midleft=(rect.x + d.px(24), cy))
            d.text(f"{ev['h']:.1f} h", 26, DIM, midleft=(rect.x + d.px(200), cy))
            d.text(ev["what"], 28, DIM if cleared else col, max_w=d.px(230), midleft=(rect.x + d.px(320), cy))
            d.text(ev.get("detail") or "", 26, ink, max_w=d.px(230), midleft=(rect.x + d.px(560), cy))
            d.text(("cleared  " if cleared else "") + ("" if ev.get("src") == "note" else dur(ev.get("dur_s"))), 26, DIM,
                   midright=(rect.right - d.px(16), cy))

        if self.archive:
            n_cl = sum(1 for e in allev if e.get("cleared"))
            d.text("ALL ALARMS  (archive)", 34, DIM, topleft=d.R(20, 72, 0, 0).topleft)
            d.text(f"{len(allev)} recorded, {n_cl} cleared from the history list", 26, DIM,
                   topright=d.R(1004, 78, 0, 0).topleft)
            if not allev:
                d.text("Nothing recorded yet.", 32, DIM, center=d.R(512, 380, 0, 0).topleft)
                return
            self._rows(d, 116, allev, 54, render_ev)
            return

        cur = log.newest_first()
        d.text("ALARM & WARNING HISTORY", 34, DIM, topleft=d.R(20, 72, 0, 0).topleft)

        def render(rect, row, sel):
            if row is None:                           # the ALL ALARMS line
                d.text("ALL ALARMS  (archive)", 28, TEXT, midleft=(rect.x + d.px(24), rect.centery))
                d.text(f"{len(allev)} recorded - OK to open", 26, DIM, midright=(rect.right - d.px(16), rect.centery))
                return
            render_ev(rect, row, sel)
        self._rows(d, 116, [None] + cur, 54, render)
        if not cur:
            d.text("No alarms in the list." + ("  (Older ones are in ALL ALARMS.)" if allev else ""), 30, DIM,
                   center=d.R(512, 380, 0, 0).topleft)

    def draw_service(self, d, ctx):
        svc, hours = ctx["service"], ctx["hours"]
        d.text("SERVICE", 34, DIM, topleft=d.R(20, 72, 0, 0).topleft)
        d.text(f"Engine hours {hours:.1f}", 28, TEXT, topright=d.R(1004, 74, 0, 0).topleft)
        rows = [None] + svc.status(hours)

        def render(rect, row, sel):
            cy = rect.centery
            if row is None:                       # the climate setting
                ci = svc.climate_info()
                d.text("CLIMATE", 28, DIM, midleft=(rect.x + d.px(20), cy))
                d.text(ci.get("label", ""), 28, TEXT, max_w=d.px(420), midleft=(rect.x + d.px(200), cy))
                d.text(f"engine oil {ci.get('oil_grade', '')}", 26, DIM, midright=(rect.right - d.px(16), cy))
                return
            it, state, left, days = row
            col = RED if state == DUE else AMBER if state == SOON else GREEN
            pygame.draw.rect(d.screen, col, (rect.x, rect.y, d.px(10), rect.h),
                             border_top_left_radius=d.px(8), border_bottom_left_radius=d.px(8))
            d.text(it["name"], 28, TEXT, max_w=d.px(400), midleft=(rect.x + d.px(24), cy))
            every = f"every {svc.interval(it):g} h" + (f" / {it['days'] // 365} yr" if it.get("days", 0) >= 365 else "")
            if svc.climate_sensitive(it):
                every += " *"
            d.text(every, 24, DIM, midleft=(rect.x + d.px(440), cy))
            txt, c = hours_left(left, days, svc.window(it))
            if svc.snoozed(it, hours) and state != "ok":
                txt += "  (later)"
            d.text(txt, 28, c, midright=(rect.right - d.px(16), cy))
        self._rows(d, 116, rows, 50, render)
        d.text("* changes with the climate setting", 22, DIM, bottomleft=d.R(20, 712, 0, 0).topleft)

    def _sysinfo(self, ctx, now):
        t, info = self._sys_cache
        if now - t < 2.0:
            return info
        info = {}
        try:
            with open("/proc/uptime") as f:
                up = float(f.read().split()[0])
            info["uptime"] = f"{int(up // 3600)} h {int(up % 3600 // 60):02d} min"
        except OSError:
            info["uptime"] = "-"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))           # no packet is sent: just picks the local address
            info["ip"] = s.getsockname()[0]
            s.close()
        except OSError:
            info["ip"] = "no network"
        try:
            u = shutil.disk_usage(ctx["data_dir"])
            info["disk"] = f"{u.free / 1e9:.1f} GB free"
        except OSError:
            info["disk"] = "-"
        self._sys_cache = (now, info)
        return info

    def draw_system(self, d, ctx):
        st, r, now = ctx["st"], ctx["readings"], ctx["now"]
        info = self._sysinfo(ctx, now)
        d.text("SYSTEM", 34, DIM, topleft=d.R(20, 72, 0, 0).topleft)

        def block(x, y, title, lines):
            box = d.R(x, y, 492, 40 + 40 * len(lines))
            pygame.draw.rect(d.screen, PANEL, box, border_radius=d.px(12))
            d.text(title, 26, DIM, topleft=(box.x + d.px(16), box.y + d.px(10)))
            for i, (k, v, c) in enumerate(lines):
                yy = box.y + d.px(52 + 40 * i)
                d.text(k, 26, DIM, midleft=(box.x + d.px(16), yy))
                d.text(str(v), 28, c, max_w=d.px(290), midright=(box.right - d.px(16), yy))
            return box.bottom

        def state_line(name, pair):
            state, label = pair
            return (name, label, {"ok": GREEN, "warn": AMBER, "alarm": RED}.get(state, GRAY))

        volts = r.get("volts")
        temps = st.get("temps") or {}
        tilt = st.get("tilt") or {}
        machine = [("Engine hours", f"{ctx['hours']:.1f}", TEXT),
                   ("Battery", f"{volts:.1f} V" if volts is not None else "--", COLOR_OF(st["volts"][0])),
                   ("Engine", f"{r.get('rpm', 0):.0f} rpm", TEXT),
                   ("Fuel", f"{r['fuel_pct']:.0f} %" if r.get("fuel_pct") is not None else "--",
                    COLOR_OF(st["fuel"][0])),
                   ("Climate", ctx["service"].climate_info().get("label", ""), TEXT)]
        sensors = [state_line(n, p) for n, p in (("Battery sensor", st["volts"]), ("Fuel sender", st["fuel"]))]
        sensors.append(("Machine angle", tilt.get("text", "off") if tilt else "off",
                        COLOR_OF(tilt.get("state", "unknown")) if tilt else GRAY))
        if temps:
            sensors.append(("E-box temp", temps["box"][1].replace("E-BOX HOT ", "").replace("E-BOX ", ""), COLOR_OF(temps["box"][0])))
            for a in temps.get("ambient", []):
                sensors.append(("Probe", a, TEXT))
        pi_warn = st.get("system", [])
        pi = [("Pi CPU", ctx["pi_temp"], AMBER if pi_warn else GREEN),
              ("Pi warnings", ", ".join(l for _, l in pi_warn) or "none", AMBER if pi_warn else GREEN),
              ("Clock", time.strftime("%b %d %Y %H:%M") if clock_valid() else "NOT SET (no battery / Wi-Fi)",
               TEXT if clock_valid() else AMBER),
              ("Pod fan", ctx.get("fan", "-"), GREEN if str(ctx.get("fan", "")).startswith("ON") else TEXT),
              ("Up for", info["uptime"], TEXT),
              ("Network", info["ip"], TEXT),
              ("SD card", info["disk"], TEXT),
              ("Saving", "OK" if not ctx["save_errors"] else "FAILED: " + ctx["save_errors"],
               GREEN if not ctx["save_errors"] else RED),
              ("Software", f"v{ctx['version']}  ({ctx['build']})", TEXT)]
        sm, usb = ctx.get("svcmode"), ctx.get("usb")
        if sm:
            pi.append(("Service Wi-Fi", sm.describe(now), BLUE if sm.state == sm.ON else
                       RED if sm.state == sm.FAILED else TEXT))
        if usb:
            pi.append(("USB stick", usb.describe(), RED if usb.state == usb.FAILED else TEXT))
        y = block(14, 116, "MACHINE", machine)
        block(14, y / d.sy + 12, "SENSORS", sensors[:6])
        block(518, 116, "RASPBERRY PI", pi)

    # -- pop-ups

    def _box(self, d, w, h, border):
        shade = pygame.Surface(d.screen.get_size(), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 170))
        d.screen.blit(shade, (0, 0))
        box = d.R(512 - w / 2, 400 - h / 2, w, h)
        pygame.draw.rect(d.screen, BG, box, border_radius=d.px(14))
        pygame.draw.rect(d.screen, border, box, width=d.px(3), border_radius=d.px(14))
        return box

    def _buttons_row(self, d, box, labels, active, y):
        n = len(labels)
        gap = 12
        w = (box.w / d.sx - 40 - gap * (n - 1)) / n
        for i, lab in enumerate(labels):
            r = d.R(box.x / d.sx + 20 + i * (w + gap), y, w, 52)
            on = i == active
            pygame.draw.rect(d.screen, TEXT if on else ROW, r, border_radius=d.px(8))
            d.text(lab, 26, BG if on else TEXT, max_w=r.w - d.px(10), center=r.center)

    def draw_modal(self, d, ctx):
        m, svc, hours = self.modal, ctx["service"], ctx["hours"]
        k = m["kind"]
        if k in ("announce", "actions"):
            it, state, left, days = m["items"][m["i"]]
            col = RED if state == DUE else AMBER
            box = self._box(d, 780, 420, col)
            head = ("SERVICE DUE" if state == DUE else "SERVICE COMING UP")
            if len(m["items"]) > 1:
                head += f"   ({m['i'] + 1} of {len(m['items'])})"
            d.text(head, 40, col, midtop=(box.centerx, box.y + d.px(22)))
            d.text(it["name"], 44, TEXT, max_w=box.w - d.px(40), midtop=(box.centerx, box.y + d.px(80)))
            txt, c = hours_left(left, days, svc.window(it))
            d.text(f"{txt}   (every {svc.interval(it):g} h)", 30, c, midtop=(box.centerx, box.y + d.px(140)))
            self._wrap(d, svc.task(it), box, box.y + d.px(190), 26, DIM, 3)
            self._buttons_row(d, box, [a[1] for a in ACTIONS], m["act"], box.y / d.sy + 300)
            self._hints(d, [("lr", "choose"), ("ok", "do it"), ("back", "close")], box.bottom - d.px(28), right=box.right - d.px(24))
        elif k == "confirm":
            box = self._box(d, 720, 380, GREEN)
            d.text("ARE YOU SURE?", 40, GREEN, midtop=(box.centerx, box.y + d.px(22)))
            d.text(f"Mark {m['item']['name']} as done", 32, TEXT, max_w=box.w - d.px(40), midtop=(box.centerx, box.y + d.px(80)))
            d.text(f"at {hours:.1f} engine hours" + (f", {time.strftime('%b %d %Y')}" if clock_valid() else ""),
                   28, DIM, midtop=(box.centerx, box.y + d.px(128)))
            self._sure_row(d, box, m)
        elif k == "details":
            it = m["item"]
            box = self._box(d, 880, 600, TEXT)
            d.text(it["name"], 40, TEXT, max_w=box.w - d.px(40), midtop=(box.centerx, box.y + d.px(20)))
            s = svc.state.get(it["id"], {})
            every = f"Every {svc.interval(it):g} engine hours" + (" or once a year" if it.get("days", 0) >= 365 else "")
            last = (f"last done at {s['done_h']:.1f} h" + (f", {when(s.get('done_t'), '%b %d %Y')}" if s.get("done_t") else "")
                    + (" (counted from install)" if s.get("baseline") else "")) if s else "not done yet"
            d.text(f"{every}  -  {last}", 26, DIM, max_w=box.w - d.px(40), midtop=(box.centerx, box.y + d.px(72)))
            steps = [x.strip().rstrip(".") for x in svc.task(it).replace(". ", ".|").split("|") if x.strip()]
            y = box.y + d.px(124)
            f = d.font(30)
            for st_ in steps:
                lines, line = [], ""
                for w in st_.split():
                    t = (line + " " + w).strip()
                    if f.size(t)[0] > box.w - d.px(110) and line:
                        lines.append(line)
                        line = w
                    else:
                        line = t
                lines.append(line)
                pygame.draw.circle(d.screen, AMBER, (box.x + d.px(46), y + d.px(14)), d.px(6))
                for ln in lines:
                    if y > box.bottom - d.px(80):
                        break
                    d.text(ln, 30, TEXT, topleft=(box.x + d.px(66), y))
                    y += d.px(36)
                y += d.px(10)
            if svc.climate_sensitive(it):
                d.text(f"Interval set by the climate: {svc.climate_info().get('label', '')}", 24, DIM,
                       bottomleft=(box.x + d.px(30), box.bottom - d.px(56)))
            self._hints(d, [("back", "back")], box.bottom - d.px(28), right=box.right - d.px(24))
        elif k == "completed":
            hist = svc.completed(m["item"]["id"])
            box = self._box(d, 700, 440, DIM)
            d.text(f"COMPLETED: {m['item']['name']}", 32, TEXT, max_w=box.w - d.px(40),
                   midtop=(box.centerx, box.y + d.px(22)))
            if not hist:
                d.text("No completed service recorded yet.", 28, DIM, center=box.center)
            for i, h in enumerate(hist[:7]):
                y = box.y + d.px(86 + 42 * i)
                d.text(f"{h['h']:.1f} h", 28, TEXT, midleft=(box.x + d.px(40), y))
                d.text(when(h.get("t")), 28, DIM, midright=(box.right - d.px(40), y))
            self._hints(d, [("back", "back")], box.bottom - d.px(28), right=box.right - d.px(24))
        elif k == "climate":
            c = svc.climates[m["i"]] if svc.climates else {}
            box = self._box(d, 760, 360, AMBER)
            d.text("CLIMATE", 40, AMBER, midtop=(box.centerx, box.y + d.px(22)))
            cy = box.y + d.px(110)
            self._tri(d, box.x + d.px(30), cy, 14, "left", TEXT)
            self._tri(d, box.right - d.px(46), cy, 14, "right", TEXT)
            d.text(c.get("label", ""), 40, TEXT, max_w=box.w - d.px(120), center=(box.centerx, cy))
            oil = [it for it in svc.items if it.get("hours_by_climate")]
            lines = [f"Engine oil: {c.get('oil_grade', '')}"]
            for it in oil:
                lines.append(f"{it['name']}: every {it.get('hours_by_climate', {}).get(c.get('id'), it['hours']):g} h")
            for i, line in enumerate(lines[:4]):
                d.text(line, 30, TEXT if i == 0 else DIM, midtop=(box.centerx, box.y + d.px(160 + 38 * i)))
            save = "save" if ctx["code"].unlocked else "save (code)"
            self._hints(d, [("lr", "change"), ("ok", save), ("back", "cancel")], box.bottom - d.px(28), right=box.right - d.px(24))
        elif k == "event":
            ev = m["ev"]
            col = LEVEL_COLOR.get(ev["level"], GRAY)
            box = self._box(d, 740, 430 if not m["archive"] else 360, col)
            d.text(f"{ev['what']}  {LEVEL_WORD.get(ev['level'], '')}", 40, col, max_w=box.w - d.px(40),
                   midtop=(box.centerx, box.y + d.px(24)))
            lines = [("What", ev.get("detail") or "-"), ("When", when(ev.get("t"))),
                     ("Engine hours", f"{ev['h']:.1f}"),
                     ("Lasted", "-" if ev.get("src") == "note" else dur(ev.get("dur_s")))]
            if ev.get("cleared"):
                lines.append(("In the history list", "cleared"))
            for i, (a_, b_) in enumerate(lines):
                y = box.y + d.px(96 + 44 * i)
                d.text(a_, 28, DIM, midleft=(box.x + d.px(40), y))
                d.text(b_, 30, TEXT, midright=(box.right - d.px(40), y))
            if m["archive"]:
                self._hints(d, [("back", "close")], box.bottom - d.px(28), right=box.right - d.px(24))
            else:
                self._buttons_row(d, box, [a_[1] for a_ in EV_ACTIONS], m["act"], box.y / d.sy + 300)
                self._hints(d, [("lr", "choose"), ("ok", "do it"), ("back", "close")], box.bottom - d.px(28),
                            right=box.right - d.px(24))
        elif k == "sysmenu":
            box = self._box(d, 960, 330, TEXT)
            d.text("SYSTEM", 40, TEXT, midtop=(box.centerx, box.y + d.px(22)))
            notes = ["the dash's own Wi-Fi and web page", f"temperatures in °{settings.units()}: OK switches",
                     time.strftime("%b %d %Y  %H:%M") if clock_valid() else "NOT SET",
                     "change the maintenance code (the old code first)", "software version, board and build"]
            if m.get("msg"):
                d.text(m["msg"], 28, AMBER, max_w=box.w - d.px(40), midtop=(box.centerx, box.y + d.px(86)))
            else:
                d.text(notes[m["act"]], 28, AMBER if m["act"] == 2 and not clock_valid() else DIM,
                       midtop=(box.centerx, box.y + d.px(86)))
            self._buttons_row(d, box, ["SERVICE WI-FI", f"UNITS  °{settings.units()}", "CLOCK", "MX CODE", "ABOUT"],
                              m["act"], box.y / d.sy + 160)
            self._hints(d, [("lr", "choose"), ("ok", "open" if m["act"] != 1 else "switch"), ("back", "close")],
                        box.bottom - d.px(32), right=box.right - d.px(24))
        elif k == "clock":
            box = self._box(d, 860, 470, TEXT)
            d.text("CLOCK", 40, TEXT, midtop=(box.centerx, box.y + d.px(22)))
            ok_ = clock_valid()
            d.text(time.strftime("%a %b %d %Y   ") + settings.hhmm(seconds=True) if ok_ else "NOT SET", 40,
                   TEXT if ok_ else AMBER, midtop=(box.centerx, box.y + d.px(84)))
            d.text(settings.zone_text(), 26, TEXT, max_w=box.w - d.px(40), midtop=(box.centerx, box.y + d.px(142)))
            if ctx["st"]["running"]:
                self._wrap(d, m.get("msg") or "ENGINE RUNNING: stop the engine to set the time or the time zone.",
                           box, box.y + d.px(190), 26, AMBER, 3)
            else:
                m.pop("msg", None)
                self._wrap(d, "Daylight saving follows the time zone by itself. A phone or laptop can set both at once: "
                              "SERVICE WI-FI, then the web page's Settings > Sync to this device.", box, box.y + d.px(190), 24, DIM, 3)
            fmt_btn = "24-HOUR" if settings.clock_fmt() == "24h" else "12-HOUR"
            self._buttons_row(d, box, ["SET TIME", "TIME ZONE", fmt_btn], m.get("act", 0), box.y / d.sy + 300)
            act = m.get("act", 0)
            self._hints(d, [("lr", "choose"), ("ok", "switch" if act == 2 else "open"), ("back", "back")],
                        box.bottom - d.px(32), right=box.right - d.px(24))
        elif k == "tzpick":
            zone, label = settings.TIME_ZONES[m["i"]]
            box = self._box(d, 820, 400, TEXT)
            d.text("TIME ZONE", 40, TEXT, midtop=(box.centerx, box.y + d.px(22)))
            cy = box.y + d.px(130)
            self._tri(d, box.x + d.px(30), cy, 14, "left", TEXT)
            self._tri(d, box.right - d.px(46), cy, 14, "right", TEXT)
            d.text(label, 48, TEXT, center=(box.centerx, cy))
            d.text(zone + ("   (now)" if zone == settings.zone_name() else ""), 28, DIM, center=(box.centerx, cy + d.px(52)))
            dst = settings.zone_dst(zone)
            d.text("daylight saving: changes by itself" if dst else "no daylight saving", 28, AMBER if dst else GREEN,
                   center=(box.centerx, cy + d.px(100)))
            self._hints(d, [("lr", "choose"), ("ok", "use this"), ("back", "back")], box.bottom - d.px(32),
                        right=box.right - d.px(24))
        elif k == "tzsure":
            zone, label = m["zone"]
            box = self._box(d, 760, 360, AMBER)
            d.text("ARE YOU SURE?", 40, AMBER, midtop=(box.centerx, box.y + d.px(22)))
            d.text(f"Time zone: {label} ({zone})", 32, TEXT, max_w=box.w - d.px(40), midtop=(box.centerx, box.y + d.px(84)))
            d.text("The clock shows that zone's local time from now on.", 26, DIM, midtop=(box.centerx, box.y + d.px(130)))
            self._sure_row(d, box, m)
        elif k == "clockset":
            box = self._box(d, 860, 400, TEXT)
            d.text("SET THE CLOCK", 40, TEXT, midtop=(box.centerx, box.y + d.px(22)))
            d.text(f"Local time, {time.strftime('%Z')}", 26, DIM, midtop=(box.centerx, box.y + d.px(76)))
            shown = [str(m["v"][0]), MONTHS[m["v"][1] - 1], f"{m['v'][2]:02d}", f"{m['v'][3]:02d}", f"{m['v'][4]:02d}"]
            widths = (150, 120, 100, 100, 100)
            gap = 18
            x = box.centerx - d.px((sum(widths) + gap * 4) / 2)
            for i, (txt, w) in enumerate(zip(shown, widths)):
                r = pygame.Rect(x, box.y + d.px(130), d.px(w), d.px(100))
                cur = i == m["f"]
                pygame.draw.rect(d.screen, SEL if cur else ROW, r, border_radius=d.px(10))
                if cur:
                    pygame.draw.rect(d.screen, TEXT, r, width=d.px(3), border_radius=d.px(10))
                d.text(txt, 52, TEXT, center=r.center)
                d.text(CLOCK_FIELDS[i][0], 20, TEXT if cur else DIM, midtop=(r.centerx, r.bottom + d.px(8)))
                x = r.right + d.px(gap)
            self._hints(d, [("lr", "change"), ("ok", "next" if m["f"] < 4 else "done"), ("back", "back")],
                        box.bottom - d.px(32), right=box.right - d.px(24))
        elif k == "clocksure":
            y, mo, dd, hh, mi = m["v"]
            box = self._box(d, 760, 380, AMBER)
            d.text("ARE YOU SURE?", 40, AMBER, midtop=(box.centerx, box.y + d.px(22)))
            d.text(f"Set the clock to  {dd} {MONTHS[mo - 1].title()} {y}  {hh:02d}:{mi:02d}", 32, TEXT,
                   max_w=box.w - d.px(40), midtop=(box.centerx, box.y + d.px(84)))
            d.text("Every record from now on is dated by this clock.", 26, DIM, midtop=(box.centerx, box.y + d.px(134)))
            self._sure_row(d, box, m)
        elif k == "clockdone":
            box = self._box(d, 760, 300, GREEN if m["ok"] else RED)
            d.text("CLOCK SET" if m["ok"] else "NOT SET", 40, GREEN if m["ok"] else RED, midtop=(box.centerx, box.y + d.px(22)))
            self._wrap(d, m["msg"], box, box.y + d.px(100), 28, TEXT, 3)
            self._hints(d, [("ok", "done")], box.bottom - d.px(32), right=box.right - d.px(24))
        elif k == "wifi":
            self._draw_wifi(d, ctx)
        elif k == "code":
            self._draw_code(d, ctx)
        elif k == "about":
            self._draw_about(d, ctx)
        elif k == "codechg":
            box = self._box(d, 800, 400, AMBER)
            d.text("CHANGING THE CODE", 40, AMBER, midtop=(box.centerx, box.y + d.px(22)))
            self._wrap(d, "You are changing the maintenance code. The old code stops working as soon as the new one "
                          "is saved. Next: enter the new code twice, then check it on the screen.", box,
                       box.y + d.px(96), 28, TEXT, 4)
            d.text("The recovery code stays the same.", 26, DIM, midtop=(box.centerx, box.y + d.px(260)))
            self._hints(d, [("ok", "go on"), ("back", "keep the old code")], box.bottom - d.px(32),
                        right=box.right - d.px(24))
        elif k == "codeshow":
            box = self._box(d, 800, 420, AMBER)
            d.text("IS THIS THE NEW CODE?", 40, AMBER, midtop=(box.centerx, box.y + d.px(22)))
            d.text("  ".join(m["new"]), 80, TEXT, midtop=(box.centerx, box.y + d.px(84)))
            d.text("Write it down before saving. YES saves it, NO enters it again.", 26, DIM,
                   midtop=(box.centerx, box.y + d.px(190)))
            self._buttons_row(d, box, ["NO", "YES, SAVE IT"], m["sel"], box.y / d.sy + 250)
            self._hints(d, [("lr", "choose"), ("ok", "save" if m["sel"] else "enter again"), ("back", "keep the old code")],
                        box.bottom - d.px(32), right=box.right - d.px(24))
        elif k == "codedone":
            box = self._box(d, 760, 320, GREEN)
            d.text("CODE CHANGED", 40, GREEN, midtop=(box.centerx, box.y + d.px(22)))
            self._wrap(d, "The new maintenance code works from now on; the old one doesn't. The recovery code is "
                          "unchanged.", box, box.y + d.px(96), 28, TEXT, 3)
            self._hints(d, [("ok", "done")], box.bottom - d.px(32), right=box.right - d.px(24))
        elif k == "recovery":
            self._draw_recovery(d, ctx)
        elif k == "usb":
            self._draw_usb(d, ctx)
        elif k == "clear_one":
            ev = m["ev"]
            box = self._box(d, 720, 380, AMBER)
            d.text("ARE YOU SURE?", 40, AMBER, midtop=(box.centerx, box.y + d.px(22)))
            d.text(f"Clear this alarm: {ev['what']}", 32, TEXT, max_w=box.w - d.px(40), midtop=(box.centerx, box.y + d.px(80)))
            d.text(f"{when(ev.get('t'), '%b %d %H:%M')}  ·  {ev['h']:.1f} h  ·  {ev.get('detail') or ''}", 26, DIM,
                   max_w=box.w - d.px(40), midtop=(box.centerx, box.y + d.px(126)))
            d.text("It leaves the history list and stays in ALL ALARMS.", 26, DIM, midtop=(box.centerx, box.y + d.px(162)))
            self._sure_row(d, box, m)
        elif k == "clear_all":
            n = len(ctx["events"].newest_first())
            box = self._box(d, 720, 380, RED)
            d.text("ARE YOU SURE?", 40, RED, midtop=(box.centerx, box.y + d.px(22)))
            d.text(f"Clear ALL {n} alarm{'s' if n != 1 else ''} from the history list", 32, TEXT, max_w=box.w - d.px(40),
                   midtop=(box.centerx, box.y + d.px(80)))
            d.text("They stay in ALL ALARMS (the archive).", 26, DIM, midtop=(box.centerx, box.y + d.px(126)))
            self._sure_row(d, box, m)

    def _sure_row(self, d, box, m):
        """NO / YES buttons (NO selected until an arrow picks YES) and the hints under them."""
        self._buttons_row(d, box, list(SURE), m["sel"], box.y / d.sy + 220)
        self._hints(d, [("lr", "choose"), ("ok", "YES: do it" if m["sel"] else "NO: back out"), ("back", "back out")],
                    box.bottom - d.px(32), right=box.right - d.px(24))

    def _qr_code(self, text, px):
        """A QR code surface (cached), or None without python3-qrcode."""
        if qrcode is None:
            return None
        if self._qr[0] != (text, px):
            q = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
            q.add_data(text)
            q.make(fit=True)
            m = q.get_matrix()
            n = len(m)
            surf = pygame.Surface((n, n))
            surf.fill((255, 255, 255))
            for y, row in enumerate(m):
                for x, on in enumerate(row):
                    if on:
                        surf.set_at((x, y), (0, 0, 0))
            self._qr = ((text, px), pygame.transform.scale(surf, (px, px)))
        return self._qr[1]

    def _draw_wifi(self, d, ctx):
        sm, running, now = ctx["svcmode"], ctx["st"]["running"], ctx["now"]
        on = sm.state == sm.ON
        box = self._box(d, 880, 520, BLUE)
        d.text("SERVICE WI-FI", 40, BLUE, midtop=(box.centerx, box.y + d.px(20)))
        if on:
            qr = self._qr_code(f"WIFI:T:WPA;S:{sm.ssid};P:{sm.password};;", d.px(250))
            x0 = box.x + d.px(40)
            if qr:
                d.screen.blit(qr, (x0, box.y + d.px(84)))
                d.text("scan to join", 22, DIM, midtop=(x0 + qr.get_width() // 2, box.y + d.px(340)))
                x0 += qr.get_width() + d.px(40)
            rows = [("1. Join Wi-Fi", sm.ssid), ("Password", sm.password), ("2. Open", sm.address.replace("http://", ""))]
            for i, (a, b) in enumerate(rows):
                y = box.y + d.px(92 + 84 * i)
                d.text(a, 26, DIM, topleft=(x0, y))
                d.text(b, 44, TEXT, max_w=box.right - x0 - d.px(30), topleft=(x0, y + d.px(28)))
            d.text(f"Turns off in {sm.minutes_left(now):.0f} min (EXTEND on the web page adds more), and at key-off.", 26, DIM,
                   midtop=(box.centerx, box.y + d.px(380)))
            devs = sm.devices()
            d.text("Connected now: " + (", ".join(devs[:3]) + (f" +{len(devs) - 3} more" if len(devs) > 3 else "")
                                        if devs else "nobody yet"), 26, TEXT if devs else DIM,
                   max_w=box.w - d.px(40), midtop=(box.centerx, box.y + d.px(420)))
            hints = [("ok", "turn off"), ("back", "close (stays on)")]
        else:
            if sm.state == sm.STARTING:
                msg, col = "Starting the Wi-Fi...", TEXT
            elif sm.state == sm.STOPPING:
                msg, col = "Turning off...", TEXT
            elif sm.state == sm.FAILED:
                msg, col = "Didn't start: " + sm.error, RED
            elif running:
                msg, col = "Stop the engine first.", AMBER
            else:
                msg, col = "OFF" + (f"  ({sm.off_reason})" if sm.off_reason else ""), DIM
            self._wrap(d, "Turns on the dash's own Wi-Fi network so a phone or laptop can open the service web page: "
                          "performance reports, alarm and service records, downloads and software updates.",
                       box, box.y + d.px(90), 30, TEXT, 4)
            self._wrap(d, f"Needs the maintenance code (unless entered since key-on). It turns itself off after {sm.on_s // 60:.0f} minutes "
                          f"(the web page can extend it), and at key-off.",
                       box, box.y + d.px(236), 28, DIM, 2)
            self._wrap(d, msg, box, box.y + d.px(320), 32, col, 2)
            can = sm.state in (sm.OFF, sm.FAILED) and not running
            hints = ([("ok", "enter code")] if can else []) + [("back", "close")]
        self._hints(d, hints, box.bottom - d.px(32), right=box.right - d.px(24))

    def _draw_usb(self, d, ctx):
        usb = ctx["usb"]
        res = usb.result
        col = RED if usb.state == usb.FAILED else BLUE
        box = self._box(d, 820, 440, col)
        d.text("USB STICK", 40, col, midtop=(box.centerx, box.y + d.px(20)))
        lines, hints = [], [("back", "close")]
        if usb.state == usb.COPYING:
            lines = [("Copying the reports and data...", TEXT, 34), ("Leave the stick in for now.", AMBER, 30)]
        elif usb.state == usb.WAITING:
            lines = [("Stop the engine to copy.", AMBER, 34)]
        elif usb.state == usb.FAILED:
            lines = [(res.get("error", ""), RED, 28), ("Pull it out and try again. The stick must be FAT32 or exFAT.", DIM, 26)]
        elif usb.state in (usb.DONE, usb.INSTALLING, usb.INSTALLED):
            lines = [(f"Copied {res.get('files', 0)} files to", DIM, 28), (res.get("folder", ""), TEXT, 34)]
            up = res.get("update")
            if usb.state == usb.INSTALLING:
                lines += [(f"Installing version {up['version']}...", AMBER, 34)]
                hints = []
            elif usb.state == usb.INSTALLED:
                lines += [(f"Version {res.get('installed')} installed. Restarting...", GREEN, 34)]
                hints = []
            elif up:
                lines += [(f"Software update on the stick: version {up['version']} ({up['build']})", TEXT, 30),
                          (f"This dash has version {ctx['version']}. Your settings are kept.", DIM, 26)]
                hints = [("ok", "install (code)"), ("back", "no")]
                if ctx["st"]["running"]:
                    hints = [("back", "no (stop the engine first)")]
            else:
                if res.get("update_error"):
                    lines.append(("Update not used: " + res["update_error"], AMBER, 24))
                lines.append(("Safe to pull the stick out.", GREEN, 34))
                hints = [("ok", "close")]
        y = box.y + d.px(96)
        for text, c, size in lines:
            self._wrap(d, text, box, y, size, c, 2)
            y += d.px(size + 30)
        if hints:
            self._hints(d, hints, box.bottom - d.px(32), right=box.right - d.px(24))

    def _wrap(self, d, text, box, y, size, color, max_lines):
        words, line, lines = text.split(), "", []
        f = d.font(size)
        for w in words:
            t = (line + " " + w).strip()
            if f.size(t)[0] > box.w - d.px(60) and line:
                lines.append(line)
                line = w
            else:
                line = t
        if line:
            lines.append(line)
        for i, ln in enumerate(lines[:max_lines]):
            d.text(ln, size, color, midtop=(box.centerx, y + i * d.px(size + 4)))


def COLOR_OF(state):
    return {"ok": GREEN, "warn": AMBER, "alarm": RED}.get(state, GRAY)

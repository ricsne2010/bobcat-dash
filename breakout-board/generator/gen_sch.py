"""Write bobcat-dash-breakout.kicad_sch from design.py: a wired schematic, one boxed block per circuit.

Parts inside a block are joined by real wires. Supplies use power symbols (GND, +3V3, +5V, +12V, ...), and the
few signals that travel between blocks use global labels (flag shapes) with the same name at both ends.

Before writing anything, the wiring is traced point by point and checked against design.py: every pin must
land on exactly the net design.py gives it, and every net must be one connected group. A mistake stops the
build here. The PCB generator then reads the net names from sch_uuids.json, and KiCad's ERC and the
schematic <-> PCB parity check confirm the result.
"""
import json
import math
import sys
import uuid
from collections import defaultdict

import sexpr
from sexpr import Sym, find, first
from design import PARTS, FP_TP, FP_MH

SYMDIR = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
PROJECT = "bobcat-dash-breakout"
OUT = sys.argv[1] if len(sys.argv) > 1 else f"{PROJECT}.kicad_sch"
ROOT = str(uuid.uuid4())
PART = {p["ref"]: p for p in PARTS}

_libs = {}


def lib_symbol(lib_id):
    lib, name = lib_id.split(":")
    if lib not in _libs:
        tree = sexpr.parse(open(f"{SYMDIR}/{lib}.kicad_sym").read())
        _libs[lib] = {s[1]: s for s in find(tree, "symbol")}
    syms = _libs[lib]
    s = syms[name]
    ext = first(s, "extends")
    if ext:   # flatten: parent's drawing + child's properties
        parent = syms[ext[1]]
        props = {p[1]: p for p in find(s, "property")}
        flat = [Sym("symbol"), name]
        for c in parent[2:]:
            if isinstance(c, list) and c[0] == "property" and c[1] in props:
                flat.append(props.pop(c[1]))
            elif isinstance(c, list) and c[0] == "symbol":
                flat.append([c[0], c[1].replace(ext[1], name, 1)] + c[2:])
            else:
                flat.append(c)
        at = max(i for i, c in enumerate(flat) if isinstance(c, list) and c[0] == "property") + 1
        flat[at:at] = list(props.values())          # child-only properties (e.g. ki_fp_filters)
        s = flat
    return [s[0], lib_id] + s[2:]


def pins_of(sym):
    out = {}

    def walk(node):
        for c in node:
            if isinstance(c, list) and c and c[0] == "pin":
                at = first(c, "at")
                out[first(c, "number")[1]] = (float(at[1]), float(at[2]))
            elif isinstance(c, list) and c and c[0] == "symbol":
                walk(c)
    walk(sym)
    return out


def U():
    return [Sym("uuid"), str(uuid.uuid4())]


def eff(size=1.27, hide=False, justify=None, bold=False):
    font = [Sym("font"), [Sym("size"), size, size]] + ([[Sym("bold"), Sym("yes")]] if bold else [])
    e = [Sym("effects"), font]
    js = [j for j in (justify or "").split() if j != "center"]      # centred is KiCad's default (no keyword)
    if js:
        e.append([Sym("justify")] + [Sym(j) for j in js])
    if hide:
        e.append([Sym("hide"), Sym("yes")])
    return e


def R4(v):
    return round(v + 0.0, 4)


def pt(x, y):
    return (R4(x), R4(y))


# ================================================================ drawing primitives
items = []            # finished s-expressions (symbols, labels, text, boxes)
lib_syms = {}
P = {}                # ref -> {pin: (x, y)}
pin_at = []           # (point, ref, pin)
segs = []             # wire segments (p1, p2)
names_at = []         # (point, net name, kind): kind = power | global | local
nc_at = []            # no-connect points
_pwr_n = [0]


def tw(s, size=1.27):
    """Rough text width (KiCad's stroke font)."""
    return len(s) * size * 0.8


def place(ref, x, y, rot=0, mirror=False, ref_at=None, val_at=None, value=None, lib=None, fields=True, show_value=True):
    """Place a symbol. ref_at / val_at: (dx, dy, side) relative to the symbol; side "left" = text starts there,
    "right" = text ends there, None = centred. (Field text is stored centred: KiCad flips left/right
    justification on rotated symbols.)"""
    p = PART.get(ref) if not ref.startswith("#") else None
    lib = lib or p["lib"]
    sym = lib_symbol(lib)
    lib_syms[lib] = sym
    pins = {}
    r = math.radians(rot)
    for n, (px, py) in pins_of(sym).items():
        qx, qy = px * math.cos(r) - py * math.sin(r), px * math.sin(r) + py * math.cos(r)
        if mirror:
            qx = -qx
        pins[n] = pt(x + qx, y - qy)
        pin_at.append((pins[n], ref, n))
    P[ref] = pins
    vert2 = len(pins) == 2 and abs(pins["1"][0] - pins["2"][0]) < 0.01      # two-pin part standing up
    horiz2 = len(pins) == 2 and abs(pins["1"][1] - pins["2"][1]) < 0.01
    fang = rot if rot in (90, 270) else 0                                  # keeps field text horizontal
    if ref_at is None:
        ref_at = (2.54, -1.27, "left") if vert2 else (0, -3.3, None) if horiz2 else (0, -6.35, None)
    if val_at is None:
        val_at = (2.54, 1.27, "left") if vert2 else (0, 3.3, None) if horiz2 else (0, 6.35, None)
    value = value if value is not None else (p["value"] if p else "")
    fp = p["fp"] if p else None

    def centre(at, s):
        dx, dy, side = at
        return (x + dx + (tw(s) / 2 if side == "left" else -tw(s) / 2 if side == "right" else 0), y + dy)
    rpos, vpos = centre(ref_at, ref), centre(val_at, value)
    node = [Sym("symbol"), [Sym("lib_id"), lib], [Sym("at"), R4(x), R4(y), rot]]
    if mirror:
        node.append([Sym("mirror"), Sym("y")])
    hide = not fields
    node += [[Sym("unit"), 1], [Sym("exclude_from_sim"), Sym("no")],
             [Sym("in_bom"), Sym("no") if (p is None or fp in (FP_TP, FP_MH, None)) else Sym("yes")],
             [Sym("on_board"), Sym("yes") if fp else Sym("no")], [Sym("dnp"), Sym("no")], U(),
             [Sym("property"), "Reference", ref, [Sym("at"), R4(rpos[0]), R4(rpos[1]), fang],
              eff(1.27, hide or ref.startswith("#"))],
             [Sym("property"), "Value", value, [Sym("at"), R4(vpos[0]), R4(vpos[1]), fang],
              eff(1.27, hide or not show_value)],
             [Sym("property"), "Footprint", fp or "", [Sym("at"), R4(x), R4(y), 0], eff(1.27, True)],
             [Sym("property"), "Datasheet", "~", [Sym("at"), R4(x), R4(y), 0], eff(1.27, True)],
             [Sym("property"), "Description", p["desc"] if p else "", [Sym("at"), R4(x), R4(y), 0], eff(1.27, True)]]
    for n in sorted(pins, key=lambda n: (len(n), n)):
        node.append([Sym("pin"), n, U()])
    node.append([Sym("instances"), [Sym("project"), PROJECT,
                 [Sym("path"), "/" + ROOT, [Sym("reference"), ref], [Sym("unit"), 1]]]])
    items.append(node)
    for n, net in (p["pins"].items() if p else []):
        if net is None:
            nc_at.append(pins[n])
    return pins


def pin(ref, n):
    return P[ref][str(n)]


def W(*pts):
    """Wire through the points (each a 2-tuple)."""
    pts = [pt(*q) for q in pts]
    for a, b in zip(pts, pts[1:]):
        if a != b:
            assert a[0] == b[0] or a[1] == b[1], f"diagonal wire {a} -> {b}"
            segs.append((a, b))


POWER_LIB = {"GND": "power:GND", "+3V3": "power:+3V3", "+5V": "power:+5V"}


def pwr(net, at, down=False, side=None):
    """Power symbol at a point. side = which way the symbol sits from the point: rails "up" by default,
    GND "down". down=True puts a rail below the point."""
    _pwr_n[0] += 1
    ref = f"#PWR{_pwr_n[0]:03d}"
    lib = POWER_LIB.get(net, "power:+12V")         # +12V, +12V_IN, +12V_BAT, +12V_HORN: the +12V arrow, renamed
    gnd = net == "GND"
    side = side or ("down" if gnd or down else "up")
    rot = ({"down": 0, "right": 90, "up": 180, "left": 270} if gnd else {"up": 0, "left": 90, "down": 180, "right": 270})[side]
    d = (4.6 if gnd else 3.6)
    vx, vy = {"up": (0, -d), "down": (0, d), "left": (-d - tw(net) / 2, 0), "right": (d + tw(net) / 2, 0)}[side]
    place(ref, at[0], at[1], rot, lib=lib, value=net, ref_at=(0, 0, None), val_at=(vx, vy, None), show_value=not gnd)
    names_at.append((pt(*at), net, "power"))
    for q, r_, n in list(pin_at):               # the power symbol's own pin is just a name, not a part pin
        if r_ == ref:
            pin_at.remove((q, r_, n))


_flag_n = [0]


def flag(at, down=False):
    """PWR_FLAG: tells ERC this net is supplied (from the harness, a module or the Pi)."""
    _flag_n[0] += 1
    ref = f"#FLG{100 + _flag_n[0]}"                # design.py's own #FLG01/02 are replaced by these
    place(ref, at[0], at[1], 180 if down else 0, lib="power:PWR_FLAG", value="PWR_FLAG",
          ref_at=(0, 0, None), val_at=(0, 3.81 if down else -3.81, None))
    for q, r_, n in list(pin_at):
        if r_ == ref:
            pin_at.remove((q, r_, n))


def gl(net, at, ang=0):
    """Global label: ang 0 = flag to the right of the point, 180 = left, 90 = up, 270 = down."""
    just = {0: "left", 180: "right", 90: "left", 270: "right"}[ang]
    items.append([Sym("global_label"), net, [Sym("shape"), Sym("passive")], [Sym("at"), R4(at[0]), R4(at[1]), ang],
                  [Sym("fields_autoplaced"), Sym("yes")], eff(1.27, justify=just), U(),
                  [Sym("property"), "Intersheetrefs", "${INTERSHEET_REFS}", [Sym("at"), R4(at[0]), R4(at[1]), ang],
                   eff(1.27, hide=True)]])
    names_at.append((pt(*at), net, "global"))


def local(net, at, ang=0):
    items.append([Sym("label"), net, [Sym("at"), R4(at[0]), R4(at[1]), ang],
                  eff(1.27, justify="left bottom" if ang in (0, 90) else "right bottom"), U()])
    names_at.append((pt(*at), net, "local"))


def text(s, x, y, size=1.27, bold=False, justify="left bottom"):
    items.append([Sym("text"), s, [Sym("exclude_from_sim"), Sym("no")], [Sym("at"), R4(x), R4(y), 0],
                  eff(size, justify=justify, bold=bold), U()])


def box(x1, y1, x2, y2, title, sub=None, hv=False):
    """Block outline with its title (the same block names as on the board's silkscreen)."""
    for k in ((0.0, 0.8) if hv else (0.0,)):
        items.append([Sym("rectangle"), [Sym("start"), R4(x1 + k), R4(y1 + k)], [Sym("end"), R4(x2 - k), R4(y2 - k)],
                      [Sym("stroke"), [Sym("width"), 0.35 if hv else 0.25], [Sym("type"), Sym("solid" if hv else "dash")],
                       [Sym("color"), 160, 0, 0, 1] if hv else [Sym("color"), 0, 0, 132, 1]],
                      [Sym("fill"), [Sym("type"), Sym("none")]], U()])
    text(title, x1 + 2.54, y1 + 4.4, 2.0, bold=True)
    if sub:
        # wrap to the box: KiCad's font at 1.27 mm is ~1.07 mm per character (measured on the PDF)
        import textwrap
        width = max(20, int((x2 - x1 - 5.08) / 1.1))
        lines = [w for part in sub.split("\n") for w in textwrap.wrap(part, width)]
        text("\n".join(lines), x1 + 2.54, y1 + 6.0, 1.27, justify="left top")


# ---------------------------------------------------------------- reusable sub-circuits
def led_chain(x, y, rail, r, d, label=None):
    """rail at the top -> resistor -> LED (anode up) -> GND. (x, y) = top of the resistor."""
    place(r, x, y + 3.81)
    place(d, x, y + 11.43, 90)
    if rail.startswith("gl:"):
        W((x, y), (x, y - 2.54), (x + 2.54, y - 2.54))
        gl(rail[3:], (x + 2.54, y - 2.54))
    else:
        pwr(rail, (x, y))
    pwr("GND", pin(d, 1))
    if label:
        text(label, x, y + 22.0, 1.27, justify="center")


def opto(ux, uy, r, led, u, diode=None, top=None, sw=None, out=None, out_len=7.62):
    """+supply -> R -> status LED -> PC817 LED -> switch side, with an optional reverse diode across the LEDs.
    top: rail name, or None (caller wires to the R's top pin). sw: "GND", or None (caller wires the switch side).
    out: global label on the transistor output, or None (caller wires it). Returns key points."""
    xc = ux - 15.24
    place(u, ux, uy, ref_at=(0, -6.35, None), val_at=(0, 6.35, None))
    place(led, xc, uy - 6.35, 90)
    place(r, xc, uy - 13.97)
    W(pin(led, 1), pin(u, 1))
    if top:
        pwr(top, pin(r, 1))
    pwr("GND", pin(u, 3))
    k = {"top": pin(r, 1), "sw": pin(u, 2), "out": pin(u, 4), "xd": xc - 7.62}
    if diode:
        xd = xc - 7.62
        place(diode, xd, uy - 6.35, 270, ref_at=(-2.54, -1.27, "right"), val_at=(-2.54, 1.27, "right"))
        W(pin(r, 2), (xd, uy - 10.16))
        W(pin(diode, 2), (xd, uy + 2.54), pin(u, 2))
        k["sw"] = pt(xd, uy + 2.54)
    if sw == "GND":
        pwr("GND", k["sw"])
    if out:
        W(pin(u, 4), (ux + 7.62 + out_len, uy - 2.54))
        gl(out, (ux + 7.62 + out_len, uy - 2.54))
    return k


def adc_clamp(nx, ny, d_up, d_dn, c, label, extra=None):
    """ADC input node at (nx, ny): Schottky to 3.3 V above, Schottky to GND below, filter cap, label."""
    place(d_up, nx, ny - 3.81, 270)
    place(d_dn, nx, ny + 3.81, 270)
    pwr("+3V3", pin(d_up, 1))
    pwr("GND", pin(d_dn, 2))
    place(c, nx + 12.7, ny + 3.81)
    pwr("GND", pin(c, 2))
    W((nx, ny), (nx + 17.78, ny))
    gl(label, (nx + 17.78, ny))


# ================================================================ the blocks
def blk_power(ox, oy):
    box(ox, oy, ox + 150, oy + 52, "POWER IN / FUSES / PROTECTION / POWER LEDS",
        "J2 BAT+ is the constant battery feed (7.5 A fuse at the battery). F1 5 A main, D1 TVS clamps spikes / blows F1 if reversed.")
    jx, jy = ox + 10.16, oy + 25.4
    place("J2", jx, jy, mirror=True, ref_at=(-2.54, -5.08, None), val_at=(-2.54, 6.35, None))
    a = pin("J2", 1)
    W(a, (a[0] + 2.54, a[1]), (a[0] + 2.54, oy + 15.24))
    W((a[0] + 2.54, oy + 15.24), (a[0] + 2.54, oy + 12.7))
    pwr("+12V_IN", (a[0] + 2.54, oy + 12.7))
    place("F1", ox + 27.94, oy + 15.24, 90)
    W((a[0] + 2.54, oy + 15.24), pin("F1", 1))
    node = (ox + 38.1, oy + 15.24)
    W(pin("F1", 2), node, (ox + 45.72, oy + 15.24), (ox + 45.72, oy + 12.7))
    pwr("+12V_BAT", (ox + 45.72, oy + 12.7))
    place("D1", ox + 38.1, oy + 22.86, 270)
    W(node, pin("D1", 1))
    pwr("GND", pin("D1", 2))
    W(pin("J2", 2), (a[0] + 7.62, jy))
    gl("IGN", (a[0] + 7.62, jy))
    pwr("GND", pin("J2", 3))
    # J3 out to the buck, F2 horn feed
    place("J3", ox + 63.5, oy + 22.86, ref_at=(2.54, -5.08, None), val_at=(0, 7.62, "left"))
    W(pin("J3", 1), (pin("J3", 1)[0] - 2.54, pin("J3", 1)[1]), (pin("J3", 1)[0] - 2.54, oy + 15.24))
    pwr("+12V", (pin("J3", 1)[0] - 2.54, oy + 15.24))
    pwr("GND", pin("J3", 2))
    place("F2", ox + 76.2, oy + 22.86)
    pwr("+12V", pin("F2", 1))
    W(pin("F2", 2), (ox + 76.2, oy + 29.21))
    pwr("+12V_HORN", (ox + 76.2, oy + 29.21), down=True)
    # power LEDs
    for k, (rail, r, d, cap) in enumerate([("+12V", "R1", "D2", "12V ON"), ("+12V_HORN", "R2", "D3", "HORN/F2"),
                                          ("+5V", "R3", "D4", "5V"), ("+3V3", "R4", "D5", "3V3")]):
        led_chain(ox + 90.17 + k * 15.24, oy + 15.24, rail, r, d, cap)


def blk_hold(ox, oy):
    box(ox, oy, ox + 250, oy + 112, "POWER HOLD",
        "Q2 passes +12V_BAT to +12V while Q3 is on: key on (IGN) OR Pi HOLD high. Q4 cuts it: Pi KILL at the end of "
        "shutdown, or the U6 timer ~3 min after key-off. C7 stretches a cut to a few seconds.")
    X0, Yr = ox + 25.4, oy + 17.78
    Yn = Yr + 12.7
    # Q2 high-side switch: source up to +12V_BAT, drain down to +12V
    place("Q2", X0 + 22.86, Yn, 180, ref_at=(-8.89, -1.27, "left"), val_at=(-8.89, 1.27, "left"))
    W((X0 + 12.7, Yr), (X0 + 20.32, Yr), (X0 + 33.02, Yr), (X0 + 43.18, Yr))
    pwr("+12V_BAT", (X0 + 12.7, Yr))
    W(pin("Q2", 3), (X0 + 20.32, Yr))
    W(pin("Q2", 2), (X0 + 20.32, Yn + 7.62))
    pwr("+12V", (X0 + 20.32, Yn + 7.62), down=True)
    place("R60", X0 + 33.02, Yr + 6.35)
    place("D40", X0 + 43.18, Yr + 6.35, 270)
    W((X0 + 33.02, Yr), pin("R60", 1)); W(pin("R60", 2), (X0 + 33.02, Yn))
    W((X0 + 43.18, Yr), pin("D40", 1)); W(pin("D40", 2), (X0 + 43.18, Yn))
    W(pin("Q2", 1), (X0 + 33.02, Yn), (X0 + 43.18, Yn), (X0 + 50.8, Yn))
    place("R61", X0 + 50.8, Yn + 6.35)
    W((X0 + 50.8, Yn), pin("R61", 1))
    place("Q3", X0 + 48.26, Yn + 15.24, ref_at=(5.08, -1.27, "left"), val_at=(5.08, 1.27, "left"))
    pwr("GND", pin("Q3", 3))
    yp = Yn + 15.24                                  # PWR_ON bus
    W(pin("Q3", 2), (X0 + 38.1, yp), (X0 + 27.94, yp), (X0 + 15.24, yp))
    place("R64", X0 + 38.1, yp + 3.81)
    pwr("GND", pin("R64", 2))
    place("R62", X0 + 11.43, yp, 90, ref_at=(0, -4.8, None), val_at=(0, -2.54, None))
    gl("IGN", pin("R62", 1), 180)
    place("R63", X0 + 11.43, yp + 5.08, 90, ref_at=(0, 2.54, None), val_at=(0, 4.8, None))
    W(pin("R63", 2), (X0 + 15.24, yp))
    gl("HOLD_GPIO", pin("R63", 1), 180)
    place("Q4", X0 + 25.4, yp + 12.7, ref_at=(5.08, -1.27, "left"), val_at=(5.08, 1.27, "left"))
    W(pin("Q4", 1), (X0 + 27.94, yp))
    pwr("GND", pin("Q4", 3))
    # KILL_RC: R65 into Q4's base; R66 + C7 to ground; KILL (Pi) and the timer through diodes
    yk = yp + 12.7
    place("R65", X0 + 16.51, yk, 90)
    xk = X0 + 12.7
    W(pin("R65", 1), (xk, yk))
    W((xk, yk), (xk, yk + 5.08), (xk, yk + 15.24), (xk, yk + 20.32))
    W((xk, yk + 5.08), (X0 + 5.08, yk + 5.08), (X0 - 7.62, yk + 5.08))
    place("R66", X0 + 5.08, yk + 8.89)
    place("C7", X0 - 7.62, yk + 8.89)
    pwr("GND", pin("R66", 2)); pwr("GND", pin("C7", 2))
    gl("KILL_RC", (X0 - 7.62, yk), 180)
    W((X0 - 7.62, yk), (X0 - 7.62, yk + 5.08))
    W((xk, yk + 20.32), (xk, yk + 25.4))
    place("D41", xk + 3.81, yk + 15.24)
    place("D42", xk + 3.81, yk + 25.4)
    place("R67", xk + 11.43, yk + 15.24, 270)
    place("R68", xk + 11.43, yk + 25.4, 270)
    gl("KILL_GPIO", pin("R67", 1))
    # U6 CD4060 (mirrored: Q14 on the left, the oscillator pins on the right)
    ux, uy = X0 + 80.01, yk + 12.7
    place("U6", ux, uy, mirror=True, ref_at=(-10.16, -22.86, "left"), val_at=(0, 23.5, None))
    W(pin("R68", 1), pin("U6", 3))
    pwr("GND", pin("U6", 8))
    vn = (ux, uy - 27.94)
    W(pin("U6", 16), vn, (ux + 10.16, vn[1]), (ux + 20.32, vn[1]), (ux + 27.94, vn[1]))
    place("R71", ux, vn[1] - 3.81)
    pwr("+12V", pin("R71", 1))
    place("C9", ux + 10.16, vn[1] + 3.81)
    place("D43", ux + 20.32, vn[1] + 3.81, 270)
    pwr("GND", pin("C9", 2)); pwr("GND", pin("D43", 2))
    flag((ux + 27.94, vn[1]))
    # oscillator: pins 11 / 10 / 9 to R69 / R70 / C8, all meeting at TMR_N below
    cols = [("R69", 11, ux + 20.32), ("R70", 10, ux + 27.94), ("C8", 9, ux + 35.56)]
    for ref, pn, cx in cols:
        a = pin("U6", pn)
        place(ref, cx, uy + 3.81)
        W(a, (cx, a[1]), pin(ref, 1))
    yn2 = uy + 10.16
    W(pin("R69", 2), (ux + 20.32, yn2)); W(pin("R70", 2), (ux + 27.94, yn2)); W(pin("C8", 2), (ux + 35.56, yn2))
    W((ux + 20.32, yn2), (ux + 27.94, yn2), (ux + 35.56, yn2))
    # reset: held high while the key is on
    a = pin("U6", 12)
    yr = uy + 25.4
    W(a, (ux + 15.24, a[1]), (ux + 15.24, yr), (ux + 22.86, yr), (ux + 30.48, yr), (ux + 36.83, yr))
    place("R73", ux + 22.86, yr + 3.81)
    place("C10", ux + 30.48, yr + 3.81)
    pwr("GND", pin("R73", 2)); pwr("GND", pin("C10", 2))
    place("R72", ux + 40.64, yr, 270)
    gl("IGN", pin("R72", 1))
    # key sense opto, IGN clamp, HOLD LED
    kx = ox + 205.74
    k = opto(kx, oy + 45.72, "R16", "D16", "U5", sw="GND", out="KEY_GPIO")
    W(k["top"], (k["top"][0], k["top"][1] - 2.54), (k["top"][0] - 12.7, k["top"][1] - 2.54))
    gl("IGN", (k["top"][0] - 12.7, k["top"][1] - 2.54), 180)
    place("D27", k["top"][0] - 7.62, k["top"][1] + 1.27, 270, ref_at=(-2.54, -1.27, "right"), val_at=(-2.54, 1.27, "right"))
    W((k["top"][0] - 7.62, k["top"][1] - 2.54), pin("D27", 1))
    pwr("GND", pin("D27", 2))
    led_chain(ox + 200.66, oy + 74.93, "gl:HOLD_GPIO", "R74", "D17", "HOLD (Pi holding power)")
    text("U5 output low = key on", kx - 10, oy + 57.15, 1.27)


def blk_inputs(ox, oy):
    box(ox, oy, ox + 160, oy + 190, "ENGINE + HYDRAULIC INPUTS  (TACH, OIL, FILTER, TEMP)",
        "Optocouplers: input active = yellow LED on = GPIO pulled low.\nFilter + temp: monitored on the ADC "
        "with a 4.7k resistor AT THE SWITCH (1.65 V OK, 0 V closed, 3.3 V wire broken).")
    # ---- high-voltage coil input
    Xh, Yc = ox + 5.08, oy + 22.86
    box(Xh - 2.54, Yc - 8.89, Xh + 58.42, Yc + 17.78, "HIGH VOLTAGE - IGNITION COIL", hv=True)
    place("J12", Xh + 2.54, Yc, mirror=True, ref_at=(-2.54, -3.81, None), val_at=(-2.54, 6.35, None))
    pwr("GND", pin("J12", 2))
    place("R80", Xh + 17.78, Yc, 90, ref_at=(0, 2.54, None), val_at=(0, 4.8, None))
    place("R81", Xh + 31.75, Yc, 90, ref_at=(0, 2.54, None), val_at=(0, 4.8, None))
    W(pin("J12", 1), pin("R80", 1))
    W(pin("R80", 2), pin("R81", 1))
    nd = (Xh + 38.1, Yc)
    W(pin("R81", 2), nd)
    place("D45", Xh + 38.1, Yc + 6.35, 270)
    place("C11", Xh + 48.26, Yc + 6.35)
    W(nd, pin("D45", 1)); W(nd, (Xh + 48.26, Yc), pin("C11", 1))
    pwr("GND", pin("D45", 2)); pwr("GND", pin("C11", 2))
    text("coil - spikes to ~400 V", Xh + 2.54, Yc + 15.24, 1.27)
    # ---- coil opto (clamped, <= 15 V) and Hall opto share TACH_GPIO
    ux = ox + 88.9
    kc = opto(ux, Yc + 17.78, "R82", "D39", "U10", sw="GND")
    W((Xh + 48.26, Yc), kc["top"])
    kh = opto(ux, Yc + 50.8, "R14", "D14", "U4", diode="D24", top="+12V")
    xb = ux + 15.24
    W(kc["out"], (xb, kc["out"][1]), (xb + 7.62, kc["out"][1]), (xb + 12.7, kc["out"][1]))
    W(kh["out"], (xb, kh["out"][1]), (xb, kc["out"][1]))
    place("R15", xb + 7.62, kc["out"][1] - 3.81)
    pwr("+3V3", pin("R15", 1))
    gl("TACH_GPIO", (xb + 12.7, kc["out"][1]))
    text("connect the coil (J12) OR a Hall sensor (J5), not both", xb - 2.54, kh["out"][1] + 10.16, 1.27)
    place("J5", ox + 10.16, kh["sw"][1], mirror=True, ref_at=(-2.54, -6.35, None), val_at=(-2.54, 6.35, None))
    W(pin("J5", 2), kh["sw"])
    pwr("+12V", pin("J5", 1)); pwr("GND", pin("J5", 3))
    # ---- oil pressure opto
    ko = opto(ux, Yc + 83.82, "R11", "D11", "U1", diode="D21", top="+12V", out="OIL_GPIO", out_len=12.7)
    place("J4", ox + 10.16, ko["sw"][1] + 2.54, mirror=True, ref_at=(-2.54, -6.35, None), val_at=(-2.54, 8.89, None))
    W(pin("J4", 1), ko["sw"])
    pwr("GND", pin("J4", 4))
    # ---- monitored filter + temp switches
    xa = ox + 22.86
    for (name, sw_pin, r_pu, r_s, d_up, d_dn, c, r_led, d_led, adc, yrow) in [
            ("FILT", 2, "R50", "R51", "D34", "D35", "C4", "R12", "D12", "FILT_ADC", Yc + 106.68),
            ("TEMP", 3, "R52", "R53", "D36", "D37", "C5", "R13", "D13", "TEMP_ADC", Yc + 139.7)]:
        x0 = xa if name == "FILT" else xa - 2.54
        a = pin("J4", sw_pin)
        W(a, (x0, a[1]), (x0, yrow), (xa + 7.62, yrow), (xa + 12.7, yrow))
        place(r_pu, xa + 7.62, yrow - 3.81)
        pwr("+3V3", pin(r_pu, 1))
        place(r_s, xa + 16.51, yrow, 90, ref_at=(0, -2.54, None), val_at=(0, 2.54, None))
        nx = xa + 25.4
        W(pin(r_s, 2), (nx, yrow))
        adc_clamp(nx, yrow, d_up, d_dn, c, adc)
        # test point tap: the switch wire
        W((xa + 7.62, yrow), (xa + 7.62, yrow + 7.62))
        gl(f"{name}_SW", (xa + 7.62, yrow + 7.62), 270)
        led_chain(xa + 66.04, yrow - 10.16, f"gl:{name}_LED", r_led, d_led,
                  "on = closed, blink = broken wire")


def blk_horn(ox, oy):
    box(ox, oy, ox + 92, oy + 58, "HORN DRIVER", "R21 keeps the horn off while the Pi boots.")
    qx, qy = ox + 40.64, oy + 40.64
    place("Q1", qx, qy, ref_at=(5.08, -1.27, "left"), val_at=(5.08, 1.27, "left"))
    pwr("GND", pin("Q1", 3))
    yt, yd = oy + 12.7, oy + 27.94
    xa, xb = qx + 2.54, qx + 15.24
    W(pin("Q1", 2), (xa, yd))
    place("D25", xa, yt + 3.81, 270)
    W(pin("D25", 2), (xa, yd))
    place("R22", xb, yt + 3.81)
    place("D26", xb, yt + 11.43, 90)
    W(pin("D26", 1), (xb, yd))
    xc = xb + 20.32
    place("J7", xc + 5.08, yt + 6.35, ref_at=(2.54, -3.81, None), val_at=(2.54, 5.08, None))
    W((xa - 5.08, yt), (xa, yt), (xb, yt), (xc - 5.08, yt), (xc - 5.08, pin("J7", 1)[1]), pin("J7", 1))
    W((xa, yd), (xb, yd), (xc - 2.54, yd), (xc - 2.54, pin("J7", 2)[1]), pin("J7", 2))
    pwr("+12V_HORN", (xa - 5.08, yt))
    ng = (qx - 10.16, qy)
    W(pin("Q1", 1), ng)
    place("R21", qx - 10.16, qy + 3.81)
    pwr("GND", pin("R21", 2))
    place("R20", qx - 17.78, qy, 90, ref_at=(0, -2.54, None), val_at=(0, 2.54, None))
    W(pin("R20", 2), ng)
    gl("HORN_GPIO", pin("R20", 1), 180)
    W(ng, (ng[0], qy - 7.62))
    gl("HORN_G", (ng[0], qy - 7.62), 90)


def blk_analog(ox, oy):
    box(ox, oy, ox + 240, oy + 66, "BATTERY / FUEL / BUTTON",
        "ADC inputs clamp to 0..3.3 V. Fuel: A = sender only (JP1 1-2, JP2 on); B = gauge + dash (JP1 2-3, JP2 off).")
    # battery divider -> A0
    x, y = ox + 10.16, oy + 20.32
    place("R30", x, y + 3.81)
    place("R31", x, y + 11.43)
    pwr("+12V", pin("R30", 1))
    pwr("GND", pin("R31", 2))
    W(pin("R30", 2), (x + 7.62, y + 7.62))
    adc_clamp(x + 7.62, y + 7.62, "D30", "D31", "C1", "BATT_ADC")
    text("battery / 5.7", x - 2.54, y + 27.94, 1.27)
    # fuel sender -> A1
    jx, cx, cy = ox + 58.42, ox + 86.36, oy + 33.02
    yin, ydiv = cy + 7.62, cy - 7.62
    place("J6", jx, yin, mirror=True, ref_at=(-2.54, -3.81, None), val_at=(-2.54, 5.08, None))
    pwr("GND", pin("J6", 2))
    place("JP1", cx, cy, 90, ref_at=(6.35, 3.81, "left"), val_at=(6.35, 6.35, "left"))
    place("R33", cx - 12.7, cy, 180)
    W(pin("J6", 1), (cx - 12.7, yin), (cx, yin), pin("JP1", 1))
    W(pin("R33", 1), (cx - 12.7, yin))
    W(pin("R33", 2), (cx - 12.7, ydiv), (cx, ydiv), pin("JP1", 3))
    place("R34", cx - 22.86, ydiv + 3.81)
    W((cx - 12.7, ydiv), (cx - 22.86, ydiv))
    pwr("GND", pin("R34", 2))
    sel = pin("JP1", 2)
    xs = cx + 10.16
    place("JP2", xs, sel[1] - 5.08, 270, ref_at=(2.54, -1.27, "left"), val_at=(2.54, 1.27, "left"))
    place("R32", xs, sel[1] - 13.97)
    pwr("+3V3", pin("R32", 1))
    W(pin("R32", 2), pin("JP2", 1))
    place("R35", cx + 27.94, sel[1], 90, ref_at=(0, -2.54, None), val_at=(0, 2.54, None))
    W(sel, (xs, sel[1]), pin("R35", 1))
    W(pin("JP2", 2), (xs, sel[1]))
    W(pin("R35", 2), (cx + 35.56, sel[1]))
    adc_clamp(cx + 35.56, sel[1], "D32", "D33", "C2", "FUEL_ADC")
    # silence button
    bx, by = ox + 168.91, oy + 27.94
    place("J8", bx, by, mirror=True, ref_at=(-2.54, -3.81, None), val_at=(-2.54, 5.08, None))
    pwr("GND", pin("J8", 2))
    place("R40", bx + 13.97, by, 90, ref_at=(0, -2.54, None), val_at=(0, 2.54, None))
    W(pin("J8", 1), pin("R40", 1))
    nb = (bx + 22.86, by)
    W(pin("R40", 2), nb, (bx + 30.48, by))
    place("C3", bx + 22.86, by + 3.81)
    pwr("GND", pin("C3", 2))
    gl("BTN_GPIO", (bx + 30.48, by))


def blk_lights(ox, oy):
    box(ox, oy, ox + 240, oy + 56, "LIGHTS ON  (light sensing)",
        "Sense wires from the LAMP side of each light switch (a few mA; the lamps' own current never comes here).")
    ys = oy + 25.4
    chans = [("FRONT", "R17", "D18", "U7", "D28"), ("REAR", "R18", "D19", "U8", "D29"), ("WORK", "R19", "D20", "U9", "D38")]
    tops = []
    for i, (name, r, led, u, dz) in enumerate(chans):
        ux = ox + 40.64 + i * 60.96
        k = opto(ux, ys + 17.78, r, led, u, diode=dz, sw="GND", out=f"LT_{name}_GPIO")
        tops.append(k["top"])
    jx = ox + 220.98
    place("J11", jx, oy + 15.24, ref_at=(2.54, -5.08, None), val_at=(2.54, 5.08, None))
    for i, t in enumerate(tops):            # pin 1 (top row) to the farthest channel: no crossings
        a = pin("J11", i + 1)
        W(a, (t[0], a[1]), t)


def blk_pi(ox, oy):
    box(ox, oy, ox + 92, oy + 72, "TO RASPBERRY PI  (40-pin ribbon, pin 1 to pin 1)")
    jx, jy = ox + 41.91, oy + 38.1
    place("J1", jx, jy, ref_at=(1.27, -27.94, None), val_at=(1.27, 30.48, None))
    for n in range(1, 41):
        net = PART["J1"]["pins"].get(str(n))
        if net is None:
            continue
        a = pin("J1", n)
        left = n % 2 == 1
        b = (a[0] - 2.54, a[1]) if left else (a[0] + 2.54, a[1])
        W(a, b)
        if net in ("GND", "+3V3", "+5V"):
            pwr(net, b, side="left" if left else "right")
        else:
            gl(net, b, 180 if left else 0)


def blk_modules(ox, oy):
    box(ox, oy, ox + 92, oy + 62, "PLUG-IN MODULES")
    for ref, x, y in (("J10", ox + 25.4, oy + 30.48), ("J9", ox + 66.04, oy + 30.48)):
        place(ref, x, y, ref_at=(2.54, -15.24, None), val_at=(2.54, 16.51, None))
        for n, net in PART[ref]["pins"].items():
            if net is None:
                continue
            a = pin(ref, n)
            b = (a[0] - 2.54, a[1])
            W(a, b)
            if net in ("GND", "+3V3", "+5V"):
                pwr(net, b, side="left")
            else:
                gl(net, b, 180)
    text("J10: ADS1115 (VDD GND SCL SDA ADDR ALRT A0-A3)", ox + 2.54, oy + 56.0, 1.27)
    text("J9: MAX98357A (LRC BCLK DIN GAIN SD GND VIN)", ox + 2.54, oy + 58.6, 1.27)


def blk_tilt(ox, oy):
    box(ox, oy, ox + 92, oy + 50, "TILT SENSOR CONNECTOR (rev 2.6)",
        "Latching Molex Micro-Fit 3.0. LSM6DSOX board on a short cable (under ~30-50 cm), on the same I2C bus "
        "as the ADS1115.")
    jx, jy = ox + 74.93, oy + 30.48
    place("J13", jx, jy, ref_at=(2.54, -6.35, None), val_at=(2.54, 8.89, None))
    p1, p2, p3, p4 = (pin("J13", n) for n in (1, 2, 3, 4))
    W(p1, (p1[0] - 2.54, p1[1]))
    pwr("GND", (p1[0] - 2.54, p1[1]), side="left")
    for (pp, ref, top, dx) in [(p2, "R85", "+3V3", 15.24), (p3, "R83", "SDA", 25.4), (p4, "R84", "SCL", 35.56)]:
        x = pp[0] - dx
        W(pp, (x, pp[1]))
        place(ref, x, pp[1] - 3.81)
        if top == "+3V3":
            pwr("+3V3", pin(ref, 1))
        else:
            gl(top, pin(ref, 1), 90)
    text("1 GND   2 3V3   3 SDA   4 SCL  (cable soldered to the sensor board)", ox + 2.54, oy + 46.0, 1.27)


def blk_temp(ox, oy):
    box(ox, oy, ox + 88, oy + 50, "TEMPERATURE (rev 2.7)",
        "1-Wire on GPIO 4. U11 measures the breakout box's air; J14 takes external DS18B20 probes (cab, outside). "
        "Several probes can share J14.")
    ux, uy = ox + 15.24, oy + 27.94
    place("U11", ux, uy, ref_at=(-8.89, -1.27, "right"), val_at=(-8.89, 1.27, "right"))
    pwr("+3V3", pin("U11", 3))
    pwr("GND", pin("U11", 1))
    dq = pin("U11", 2)
    n1, n2 = (ux + 12.7, uy), (ux + 20.32, uy)
    W(dq, n1, n2)
    place("R86", n1[0], uy - 3.81, 180)
    pwr("+3V3", pin("R86", 2))
    W(n2, (n2[0], uy + 5.08))
    gl("W1_DQ", (n2[0], uy + 5.08), 270)
    place("R87", ux + 29.21, uy, 90, ref_at=(0, -2.54, None), val_at=(0, 2.54, None))
    W(n2, pin("R87", 1))
    jx = ux + 45.72
    place("J14", jx, uy, ref_at=(2.54, -6.35, None), val_at=(2.54, 6.35, None))
    W(pin("R87", 2), pin("J14", 2))
    g = pin("J14", 1)
    W(g, (g[0] - 1.27, g[1]))
    pwr("GND", (g[0] - 1.27, g[1]), side="left")
    p3 = pin("J14", 3)
    m = p3[0] - 3.81
    W(p3, (m, p3[1]), (m, uy + 7.62))
    place("R88", m - 3.81, uy + 7.62, 90, ref_at=(0, 2.54, None), val_at=(0, 4.8, None))
    pwr("+3V3", pin("R88", 1), side="left")
    text("J14: 1 GND   2 DQ   3 3V3", ox + 2.54, oy + 46.0, 1.27)


def blk_testpoints(ox, oy):
    box(ox, oy, ox + 212, oy + 34, "TEST POINTS", "Same labels as the board silkscreen.")
    tps = [p for p in PARTS if p["group"] == "tp"]
    for i, p in enumerate(tps):
        x, y = ox + 7.62 + i * 10.16, oy + 17.78
        net = p["pins"]["1"]
        place(p["ref"], x, y, ref_at=(0, -5.08, None), val_at=(0, -7.0, None), show_value=False)
        W((x, y), (x, y + 2.54))
        q = (x, y + 2.54)
        if net == "GND":
            pwr("GND", q)
        elif net.startswith("+"):
            pwr(net, q, down=True)
        else:
            gl(net, q, 270)


def blk_flags(ox, oy):
    """PWR_FLAGs: the supplies come in from the harness, the buck or the Pi, so tell ERC they're driven."""
    box(ox, oy, ox + 92, oy + 30, "SUPPLY FLAGS (ERC only)", "Supplies enter from the harness, the buck and the Pi.")
    for i, net in enumerate(["+12V_IN", "+12V_BAT", "+12V", "+12V_HORN", "+5V", "+3V3", "GND"]):
        x, y = ox + 7.62 + i * 12.7, oy + 21.59
        W((x, y), (x, y + 2.54))
        flag((x, y))
        if net == "GND":
            pwr("GND", (x, y + 2.54))
        else:
            pwr(net, (x, y + 2.54), down=True)


def blk_mech(ox, oy):
    box(ox, oy, ox + 36.83, oy + 20, "MOUNTING")
    for i in range(4):
        place(f"H{i + 1}", ox + 6.35 + i * 8.89, oy + 13.97, ref_at=(0, -3.81, None), val_at=(0, 3.81, None))


# ---------------------------------------------------------------- sheet layout (A2: 594 x 420 mm)
blk_power(12.7, 12.7)
blk_inputs(12.7, 69.85)
blk_hold(177.8, 12.7)
blk_analog(177.8, 129.54)
blk_lights(177.8, 200.66)
blk_testpoints(177.8, 261.62)
blk_mech(393.7, 261.62)
blk_tilt(177.8, 299.72)
blk_temp(274.32, 299.72)
blk_pi(434.34, 12.7)
blk_modules(434.34, 90.17)
blk_horn(434.34, 200.66)
blk_flags(434.34, 264.16)

# the two PWR_FLAGs from design.py (#FLG01 TMR_VDD, #FLG02 GND) are drawn by blk_hold / blk_flags under new refs
NOTES = ("Fuel mode:  A = sender only: JP1 1-2, fit JP2.   B = gauge + dash: JP1 2-3, JP2 off.\n"
         "Oil + tach: +12V -> 2.2k -> yellow status LED -> PC817 LED -> sensor wire. Switch closes to chassis = LED on = GPIO low.\n"
         "Filter + temp (monitored): fit a 4.7k resistor across each switch AT THE SWITCH. Wire reads ~1.65 V OK, ~0 V switch closed,\n"
         "3.3 V wire broken (NO SIGNAL). Their LEDs are driven by the Pi.\n"
         "F1: 5 A (Pi 4 or Pi 5).  D1 (TVS) clamps spikes and blows F1 if power is connected backwards.\n"
         "Power hold: +12V_IN is the CONSTANT battery feed. Q2 switches it to +12V while the key is on (IGN) or the Pi holds HOLD\n"
         "(GPIO26) high. At the end of shutdown the Pi raises KILL (GPIO16): Q4 cuts power. U6 cuts power ~3 min after key-off if\n"
         "the Pi never does. Key-off draw with everything off: under 0.1 mA.\n"
         "Lights: sense wires from the LAMP side of each light switch (inline 1 A fuse at the tap). Light on = yellow LED on = GPIO low.\n"
         "Tach: J12 COIL = ignition coil NEGATIVE terminal (spikes to ~400 V): R80+R81 -> 15 V zener + 1 uF -> PC817 U10.\n"
         "U10 and U4 (Hall) share TACH_GPIO: connect the coil OR a Hall sensor, not both. 4-cyl coil: pulses_per_rev = 2.\n"
         "Labels with the same name are connected (flag-shaped = between blocks). GND / +3V3 / +5V at the Pi header and modules\n"
         "are the same supplies as the ground and supply symbols.")
text(NOTES, 434.34, 157.48, 1.27, justify="left top")


# ================================================================ connectivity: split, junctions, check, name
pins_by_pt = defaultdict(list)
for q, ref, n in pin_at:
    pins_by_pt[q].append((ref, n))
contacts = set(pins_by_pt) | {q for q, _, _ in names_at} | {a for s in segs for a in s}


def on_seg(q, a, b):
    if a[0] == b[0] == q[0]:
        return min(a[1], b[1]) < q[1] < max(a[1], b[1])
    if a[1] == b[1] == q[1]:
        return min(a[0], b[0]) < q[0] < max(a[0], b[0])
    return False


split = []
for a, b in segs:
    cuts = sorted([q for q in contacts if on_seg(q, a, b)], key=lambda q: (abs(q[0] - a[0]) + abs(q[1] - a[1])))
    chain = [a] + cuts + [b]
    split += [(u, v) for u, v in zip(chain, chain[1:]) if u != v]
segs = sorted(set(tuple(sorted(s)) for s in split))

parent = {}


def find_(x):
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def union(a, b):
    parent[find_(a)] = find_(b)


for a, b in segs:
    union(a, b)
for q in contacts:
    find_(q)
deg = defaultdict(int)
for a, b in segs:
    deg[a] += 1
    deg[b] += 1
for q in contacts:
    if deg[q] + len(pins_by_pt.get(q, [])) >= 3 and deg[q] >= 2:
        items.append([Sym("junction"), [Sym("at"), q[0], q[1]], [Sym("diameter"), 0], [Sym("color"), 0, 0, 0, 0], U()])

clusters = defaultdict(lambda: {"pins": [], "names": set(), "pts": []})
for q in contacts:
    c = clusters[find_(q)]
    c["pts"].append(q)
    c["pins"] += pins_by_pt.get(q, [])
for q, net, kind in names_at:
    clusters[find_(q)]["names"].add((net, kind))

# names that mean the same net (the Pi header and modules label their supplies with local labels)
ALIAS = {}
groups = defaultdict(list)
errors = []
for key, c in clusters.items():
    nets = {PART[r]["pins"].get(n) for r, n in c["pins"] if r in PART}
    nets.discard(None)
    named = {ALIAS.get(n, n) for n, _ in c["names"]}
    allnets = nets | named
    if len(allnets) > 1:
        errors.append(f"short: {sorted(allnets)} at {c['pts'][:3]} pins {c['pins'][:6]}")
    if not allnets:
        if c["pins"] and all(PART[r]["pins"].get(n) is None for r, n in c["pins"]) and len(c["pts"]) == 1:
            continue                                    # an unused pin with its no-connect mark
        errors.append(f"unconnected group at {c['pts'][:3]} pins {c['pins']}")
        continue
    groups[next(iter(allnets))].append(key)
need = defaultdict(set)
for p in PARTS:
    if p["fp"] is None:
        continue
    for n, net in p["pins"].items():
        if net:
            need[net].add((p["ref"], n))
for net, refs in need.items():
    got = {x for k in groups.get(net, []) for x in clusters[k]["pins"]}
    missing = refs - got
    if missing:
        errors.append(f"{net}: pins not wired to it: {sorted(missing)}")
    parts_ = [k for k in groups.get(net, []) if clusters[k]["pins"] or True]
    named_parts = [k for k in parts_ if clusters[k]["names"]]
    if len(parts_) > 1 and len(named_parts) < len(parts_):
        errors.append(f"{net}: split into {len(parts_)} pieces, not all named")
for q in nc_at:
    if deg[q] or len(pins_by_pt[q]) > 1:
        errors.append(f"no-connect pin is wired at {q}")
if errors:
    print("\n".join(errors[:40]))
    raise SystemExit(f"schematic wiring check failed: {len(errors)} problem(s)")

# Name a net with a local label where it has a real stretch of horizontal wire to sit on, and always for the nets
# the PCB's net classes refer to by name. The rest (short links inside a block) keep KiCad's automatic names;
# gen_pcb.py reads every name back from the exported netlist.
from design import NETCLASSES
MUST_NAME = {m for _, (_, _, ms) in NETCLASSES.items() for m in ms}
net_names = {}
for net, keys in groups.items():
    kinds = {k for key in keys for _, k in clusters[key]["names"]}
    net_names[net] = net if kinds & {"power", "global"} else "/" + net
    for key in keys:
        c = clusters[key]
        if c["names"]:
            continue
        hs = [s for s in segs if find_(s[0]) == key and s[0][1] == s[1][1]]
        vs = [s for s in segs if find_(s[0]) == key and s[0][0] == s[1][0]]
        best = max(hs, key=lambda s: abs(s[1][0] - s[0][0])) if hs else None
        if best and (abs(best[1][0] - best[0][0]) >= 10.16 or net in MUST_NAME):
            a, b = best
            x0, x1 = min(a[0], b[0]), max(a[0], b[0])
            local(net, (max(x0 + 1.27, round(((x0 + x1) / 2 - tw(net) / 2) / 1.27) * 1.27), a[1]))
        elif net in MUST_NAME and vs:
            a, b = max(vs, key=lambda s: abs(s[1][1] - s[0][1]))
            local(net, (a[0], max(a[1], b[1]) - 1.27), 90)
        elif net in MUST_NAME:
            local(net, c["pts"][0])
for q in nc_at:
    items.append([Sym("no_connect"), [Sym("at"), q[0], q[1]], U()])
for a, b in segs:
    items.append([Sym("wire"), [Sym("pts"), [Sym("xy"), a[0], a[1]], [Sym("xy"), b[0], b[1]]],
                  [Sym("stroke"), [Sym("width"), 0], [Sym("type"), Sym("default")]], U()])

doc = [Sym("kicad_sch"), [Sym("version"), 20250114], [Sym("generator"), "eeschema"], [Sym("generator_version"), "9.0"],
       [Sym("uuid"), ROOT], [Sym("paper"), "A2"],
       [Sym("title_block"), [Sym("title"), "Bobcat Digital Dash - Breakout Board"], [Sym("date"), "2026-10-22"],
        [Sym("rev"), "2.7"], [Sym("comment"), 1, "Harness breakout between the machine wiring and the Raspberry Pi"],
        [Sym("comment"), 2, "Wired schematic: one box per circuit block, the same blocks as the board silkscreen"]],
       [Sym("lib_symbols")] + list(lib_syms.values())] + items + \
      [[Sym("sheet_instances"), [Sym("path"), "/", [Sym("page"), "1"]]], [Sym("embedded_fonts"), Sym("no")]]
open(OUT, "w").write(sexpr.dump(doc) + "\n")


# save the symbol UUIDs and net names so the PCB can link each footprint to its symbol
def pin_names(sym):
    out = {}

    def walk(node):
        for c in node:
            if isinstance(c, list) and c and c[0] == "pin":
                name, num = first(c, "name")[1], first(c, "number")[1]
                if name and name != "~":
                    out[num] = name
            elif isinstance(c, list) and c and c[0] == "symbol":
                walk(c)
    walk(sym)
    return out


sch_uuid = {}
for node in items:
    if node[0] == "symbol":
        ref = next(c[2] for c in node if isinstance(c, list) and c[0] == "property" and c[1] == "Reference")
        sch_uuid[ref] = next(c[1] for c in node if isinstance(c, list) and c[0] == "uuid")
names = {}
for p in PARTS:
    nc = [n for n, net in p["pins"].items() if net is None]
    if nc and p["fp"]:
        pn = pin_names(lib_symbol(p["lib"]))
        names[p["ref"]] = {n: pn[n] for n in nc if n in pn}
json.dump({"root": ROOT, "parts": {p["ref"]: sch_uuid[p["ref"]] for p in PARTS if p["ref"] in sch_uuid},
           "pin_names": names, "net_names": net_names}, open("sch_uuids.json", "w"), indent=1)
print("wrote", OUT, "with", len(sch_uuid), "symbols,", len(segs), "wire segments")

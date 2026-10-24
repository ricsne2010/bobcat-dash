"""Writes ../kicad/cht-board.kicad_sch (and sch_uuids.json for gen_pcb.py). Plain Python, no KiCad needed."""
import json
import os
import re
import uuid

from chtboard import NAME, REV, PARTS, ADDRESS

SYMDIR = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "kicad", NAME + ".kicad_sch")


def lib_symbol(lib_id):
    """A symbol's definition from KiCad's library, renamed to its full lib_id for lib_symbols."""
    lib, name = lib_id.split(":")
    t = open(os.path.join(SYMDIR, lib + ".kicad_sym")).read()
    i = t.index(f'\n\t(symbol "{name}"') + 2
    d = 0
    for j in range(i, len(t)):
        d += {"(": 1, ")": -1}.get(t[j], 0)
        if d == 0:
            return t[i:j + 1].replace(f'(symbol "{name}"', f'(symbol "{lib_id}"', 1)


def pins_of(lib_id):
    """pin number -> (x, y) in symbol coordinates (y up)."""
    s = lib_symbol(lib_id)
    return {n: (float(x), float(y)) for x, y, n in
            re.findall(r'\(pin \w+ \w+\s*\(at ([-\d.]+) ([-\d.]+) [-\d.]+\).*?\(number "(\w+)"', s, re.S)}


U = lambda: str(uuid.uuid4())
ROOT = U()
out, links = [], {}


def font(hide=False, justify=None):
    j = f" (justify {justify})" if justify else ""
    return f"(effects (font (size 1.27 1.27)){j}{' (hide yes)' if hide else ''})"


def prop(name, value, x, y, hide=False):
    return f'(property "{name}" "{value}" (at {x:.2f} {y:.2f} 0) {font(hide)})'


def place(ref, x, y, ref_at, val_at, mirror=False):
    """Places a symbol; returns pin number -> sheet position of the pin's end. Unused pins get a no-connect flag."""
    lib_id, value, fp, pins, desc = PARTS[ref]
    u = links[ref] = U()
    pin_uuids = " ".join(f'(pin "{n}" (uuid "{U()}"))' for n in pins_of(lib_id))
    out.append(f'(symbol (lib_id "{lib_id}") (at {x:.2f} {y:.2f} 0){" (mirror y)" if mirror else ""} (unit 1) '
               f'(exclude_from_sim no) '
               f'(in_bom {"no" if ref.startswith("H") else "yes"}) (on_board yes) (dnp no) (uuid "{u}") '
               f'{prop("Reference", ref, *ref_at)} {prop("Value", value, *val_at)} '
               f'{prop("Footprint", fp, x, y, True)} {prop("Datasheet", "~", x, y, True)} '
               f'{prop("Description", desc, x, y, True)} {pin_uuids} '
               f'(instances (project "{NAME}" (path "/{ROOT}" (reference "{ref}") (unit 1)))))')
    ends = {}
    for n, net in pins.items():
        px, py = pins_of(lib_id)[str(n)]
        ends[n] = at = (x + (-px if mirror else px), y - py)     # symbol y is up, sheet y is down
        if net is None:
            out.append(f'(no_connect (at {at[0]:.2f} {at[1]:.2f}) (uuid "{U()}"))')
    return ends


def wire(*pts):
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        out.append(f'(wire (pts (xy {x1:.2f} {y1:.2f}) (xy {x2:.2f} {y2:.2f})) '
                   f'(stroke (width 0) (type default)) (uuid "{U()}"))')


def label(net, x, y, just="left"):
    out.append(f'(label "{net}" (at {x:.2f} {y:.2f} 0) (effects (font (size 1.27 1.27)) (justify {just} bottom)) '
               f'(uuid "{U()}"))')


def text(s, x, y, size=1.27):
    out.append(f'(text "{s}" (exclude_from_sim no) (at {x:.2f} {y:.2f} 0) '
               f'(effects (font (size {size} {size})) (justify left)) (uuid "{U()}"))')




def stubs(ref, ends, side):
    """A short wire from every connected pin and its net's label: pins with the same label are joined."""
    for n, net in PARTS[ref][3].items():
        if net is None:
            continue
        x, y = ends[n]
        dx = {"left": -2.54, "right": 2.54}[side(n) if callable(side) else side]
        wire((x, y), (x + dx, y))
        label(net, x + dx, y, "left" if dx > 0 else "right")


# the four module sockets, left column; the AUX plug, the brake input and the address resistors on the right
for i in range(1, 5):
    x, y = 38.1, 38.1 + (i - 1) * 33.02
    e = place(f"M{i}", x, y, (x, y - 13.97), (x, y + 13.97))
    stubs(f"M{i}", e, "right")
    text(f"CYL {i}: I2C {ADDRESS[i]}", x - 25.4, y - 15.24, 1.27)
e = place("J1", 132.08, 45.72, (132.08, 36.83), (132.08, 54.61))
stubs("J1", e, lambda n: "left" if n % 2 else "right")
e = place("J2", 228.6, 76.2, (228.6, 69.85), (228.6, 82.55))
stubs("J2", e, "left")
e = place("U1", 190.5, 76.2, (190.5, 68.58), (190.5, 83.82))
stubs("U1", e, lambda n: "left" if n in (1, 2) else "right")
for ref, x, y in (("D1", 147.32, 76.2), ("D2", 147.32, 96.52)):
    e = place(ref, x, y, (x, y - 5.08), (x, y + 5.08))
    stubs(ref, e, lambda n: "left" if n == 1 else "right")
for ref, x, y in (("R1", 132.08, 124.46), ("R2", 160.02, 124.46)):
    e = place(ref, x, y, (x + 2.54, y - 2.54), (x + 2.54, y + 2.54))
    stubs(ref, e, "right")
for i in range(12):
    hx = 190.5 + (i % 6) * 10.16
    place(f"H{i + 1}", hx, 124.46 + (i // 6) * 12.7, (hx, 119.38 + (i // 6) * 12.7), (hx, 129.54 + (i // 6) * 12.7))

text("CHT + PARK BRAKE BOARD", 101.6, 17.78, 2.54)
text("Up to four Adafruit MCP9601 thermocouple amplifiers (5165), one per cylinder: each takes its Type K", 101.6, 22.86)
text("thermocouple in its own screw terminal. ADDR sets the address: socket 1 to GND 0x60, 2 by 22k 0x65,", 101.6, 26.67)
text("3 by 43k 0x66, 4 open 0x67. ALERT1-4 not used. Parking brake: +12V via 2.2k (breakout board) -> D1 -> U1 LED", 101.6, 30.48)
text("-> J2 SW; the switch closes to GND when the brake is set: BRAKE (GPIO 9) low. Pins with the same label are joined.", 101.6, 34.29)
text("H1-H4: M3 board mounting. H5-H12: M2.5, two per module, 11 mm standoffs.", 190.5, 144.78)

syms = sorted({p[0] for p in PARTS.values()})
doc = (f'(kicad_sch (version 20250114) (generator "eeschema") (generator_version "9.0") (uuid "{ROOT}") (paper "A3") '
       f'(title_block (title "M.O.S.S. CHT + Parking Brake Board - Bobcat M700") (date "2026-10-24") (rev "{REV}") '
       f'(comment 1 "Thermocouple amplifier carrier and parking brake input, on the breakout board AUX plug")) '
       f'(lib_symbols {" ".join(lib_symbol(s) for s in syms)}) '
       + " ".join(out) +
       ' (sheet_instances (path "/" (page "1"))) (embedded_fonts no))')
os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w").write(doc)
json.dump(links, open(os.path.join(HERE, "sch_uuids.json"), "w"), indent=1)
print("wrote", os.path.normpath(OUT))

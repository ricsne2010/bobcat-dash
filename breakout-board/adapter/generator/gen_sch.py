"""Writes ../kicad/ads1115-adapter.kicad_sch (and sch_uuids.json for gen_pcb.py). Plain Python, no KiCad needed."""
import json
import os
import re
import uuid

from adapter import NAME, REV, PARTS

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


def label(net, x, y):
    out.append(f'(label "{net}" (at {x:.2f} {y:.2f} 0) (effects (font (size 1.27 1.27)) (justify left bottom)) '
               f'(uuid "{U()}"))')


def text(s, x, y, size=1.27):
    out.append(f'(text "{s}" (exclude_from_sim no) (at {x:.2f} {y:.2f} 0) '
               f'(effects (font (size {size} {size})) (justify left)) (uuid "{U()}"))')


# J1 / J2 face right, J3 faces left; every connection is a drawn wire (named where it leaves J1 / J2)
e1 = place("J1", 50.8, 63.5, (50.8, 53.34), (50.8, 76.2), mirror=True)
e2 = place("J2", 50.8, 101.6, (50.8, 91.44), (50.8, 114.3), mirror=True)
e3 = place("J3", 152.4, 83.82, (152.4, 68.58), (152.4, 99.06))
by_net = {}
for ends, ref in ((e1, "J1"), (e2, "J2")):
    for n, at in ends.items():
        net = PARTS[ref][3][n]
        if net:
            by_net[net] = at
j3 = {net: e3[n] for n, net in PARTS["J3"][3].items()}
for k, net in enumerate(PARTS["J3"][3].values()):        # one vertical run per net, in J3 pin order
    (ax, ay), (bx, by) = by_net[net], j3[net]
    col = 81.28 + k * 5.08
    wire((ax, ay), (col, ay), (col, by), (bx, by))
    label(net, ax + 1.27, ay)
for i in range(4):
    place(f"H{i + 1}", 200.66 + i * 10.16, 66.04, (200.66 + i * 10.16, 60.96), (200.66 + i * 10.16, 71.12))

text("ADS1115 ADAPTER", 30.48, 30.48, 2.54)
text("Lets a 10-pin inline ADS1115 board (older Adafruit 1085 and most clones) plug into the breakout board's", 30.48, 38.1)
text("two-row ADS1115 sockets (rev 2.8: J15 + J10). Straight-through wiring: same signals, same address (0x48,", 30.48, 41.91)
text("ADDR is grounded on the breakout board), no software change. A+ / A- of the two-row pattern are not used.", 30.48, 45.72)
text("J1 and J2 are male pins underneath. J3 is the socket on top. Crossing wires without a dot are not joined.", 30.48, 127.0)
text("H1-H4: M2.5, line up with the breakout board's H5-H8: screw the adapter down on 11 mm standoffs.", 190.5, 81.28)

syms = sorted({p[0] for p in PARTS.values()})
doc = (f'(kicad_sch (version 20250114) (generator "eeschema") (generator_version "9.0") (uuid "{ROOT}") (paper "A4") '
       f'(title_block (title "Bobcat Digital Dash - ADS1115 Adapter") (date "2026-10-23") (rev "{REV}") '
       f'(comment 1 "10-pin inline ADS1115 board -> breakout board two-row ADS1115 socket")) '
       f'(lib_symbols {" ".join(lib_symbol(s) for s in syms)}) '
       + " ".join(out) +
       ' (sheet_instances (path "/" (page "1"))) (embedded_fonts no))')
os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w").write(doc)
json.dump(links, open(os.path.join(HERE, "sch_uuids.json"), "w"), indent=1)
print("wrote", os.path.normpath(OUT))

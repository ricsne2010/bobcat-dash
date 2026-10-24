"""Stage 1: place footprints, assign nets, outline, silkscreen. Run with KiCad's Python."""
import json
import math
import os
import sys

import pcbnew
from design import PARTS, NETCLASSES, DEFAULT_TRACK, DEFAULT_CLEAR, nets

FPDIR = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
OUT = sys.argv[1] if len(sys.argv) > 1 else "out/bobcat-dash-breakout.kicad_pcb"
W, H = 162.0, 134.0          # rev 2.0: +24 mm at the bottom for the power-hold band; rev 2.7: +12 mm wide (TEMP column)
# rev 2.8: a 25 mm strip added along the top (amp sites, logo, title). Everything below keeps its old coordinates:
# y runs from -TOP (the new top edge) to H, and V() shifts it all down so the board file still starts at y = 0.
TOP = 25.0
MM = pcbnew.FromMM


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y + TOP))


def SZ(w, h):                            # a size, not a position: no TOP shift
    return pcbnew.VECTOR2I(MM(w), MM(h))


# ---------------------------------------------------------------- placement: ref -> (x, y, rotation)
ADS_X = 123.0                        # ADS1115 module centre line (x)
STEREO_X, STEREO_ROW = 42.0, 26.0      # stereo amp module: centre line (x) and header row (y), beside the mono amp
J1_X, J1_Y = 36.0, -17.5               # ribbon header (was 50, 11 before the top strip)
POD_X = 62.0                           # rev 2.9: button pod plug J17 (pin 1) and its circuits, x 58..106
LED_DX, LED_DY = J1_X - 50, J1_Y - 11 + 2.5  # power LEDs move with it (2.5 mm lower: room for its label)
TILT_Y = 13.3                          # rev 2.9: TILT plug (pin 1) level with the ADC module's top socket row (J15)
TEMP_DY = 7.0                          # TEMP column down 7 mm, below the moved H18 (29 mm was tried: +3V3 wouldn't route)
CONN_Y = H - 10.54                   # harness connectors: plug face flush with the bottom edge
P = {
    # rev 2.2: H3 moved up like H4, so the row starts 5 mm further left and J5 can grow to 4 pins
    "J2": (8, CONN_Y, 0), "J3": (27, CONN_Y, 0), "J7": (41, CONN_Y, 0), "J5": (55, CONN_Y, 0),
    "J4": (79.1, CONN_Y, 0), "J6": (103, CONN_Y, 0), "J8": (117, CONN_Y, 0), "J11": (131, CONN_Y, 0),
    # rev 2.8: the ribbon header sits on the top edge (the ribbon goes straight up to the lid), power LEDs under it
    "J1": (J1_X, J1_Y, 90), "J9": (8, 26, 90),
    # rev 2.8: ADS1115 (Adafruit 1085, STEMMA QT) plugs straight in: bottom row J10, top row J15, 12.7 mm apart
    "J10": (ADS_X - 6.35, 26, 90), "J15": (ADS_X - 6.35, 26 - 12.7, 90),
    # rev 2.8: amp boards. MONO (Adafruit 3006) on J9 as before: its two holes on its far edge, 13.97 mm above the
    # row. STEREO (Adafruit 6513) in the new top strip on J16: holes at its four corners, the lower two in line
    # with its row. Fit one or the other.
    "H9": (8 + 1.27, 26 - 13.97, 0), "H10": (8 + 13.97, 26 - 13.97, 0),
    # rev 2.9: button pod plug (standing, against the ADC module), its 4 input filters and the fan driver,
    # in the space the ribbon header left
    "J17": (POD_X + 42.0, 6.6, 270),
    "R89": (POD_X - 2, 8.0, 270), "R90": (POD_X + 2, 8.0, 270), "R91": (POD_X + 6, 8.0, 270), "R92": (POD_X + 10, 8.0, 270),
    "C12": (POD_X - 2, 20.0, 270), "C13": (POD_X + 2, 20.0, 270), "C14": (POD_X + 6, 20.0, 270), "C15": (POD_X + 10, 20.0, 270),
    "D46": (POD_X + 16, 4.8, 0), "R95": (POD_X + 16, 10.8, 0), "D47": (POD_X + 28.5, 10.8, 0),
    "R93": (POD_X + 16, 16.0, 0), "R94": (POD_X + 16, 21.0, 0), "Q5": (POD_X + 18, 27.8, 0),
    "J16": (STEREO_X - 6.35, STEREO_ROW, 90),
    "H11": (STEREO_X - 10.16, STEREO_ROW, 0), "H12": (STEREO_X + 10.16, STEREO_ROW, 0),
    "H13": (STEREO_X - 10.16, STEREO_ROW - 13.97, 0), "H14": (STEREO_X + 10.16, STEREO_ROW - 13.97, 0),
    # its four corner holes, in line with the rows, 10.16 mm either side of centre (module holes are M2.5)
    "H5": (ADS_X - 10.16, 26 - 12.7, 0), "H6": (ADS_X + 10.16, 26 - 12.7, 0),
    "H7": (ADS_X - 10.16, 26, 0), "H8": (ADS_X + 10.16, 26, 0),
    # power / horn block (left)
    "F1": (11, 82.5, 0), "F2": (11, 68.5, 0), "D1": (11.5, 62.5, 0),
    "Q1": (31, 82, 0), "R20": (28, 74.5, 0), "R21": (28, 69, 0), "D25": (28, 88, 0),
    "R22": (28, 63.5, 0), "D26": (39.5, 63.5, 0),
    # power LEDs under the ribbon header
    "R1": (45 + LED_DX, 22 + LED_DY, 0), "D2": (55 + LED_DX, 22 + LED_DY, 0),
    "R2": (60 + LED_DX, 22 + LED_DY, 0), "D3": (70 + LED_DX, 22 + LED_DY, 0),
    "R3": (75 + LED_DX, 22 + LED_DY, 0), "D4": (85 + LED_DX, 22 + LED_DY, 0),
    "R4": (90 + LED_DX, 22 + LED_DY, 0), "D5": (100 + LED_DX, 22 + LED_DY, 0),
    # batt / fuel / aux / button block (right)
    "R32": (106, 44, 0), "R33": (106, 50.5, 0), "R34": (106, 57, 0), "R35": (106, 63.5, 0),
    "C2": (106, 70, 0), "D32": (106, 76.5, 0), "D33": (106, 83, 0),
    "R30": (119, 44, 0), "R31": (119, 50.5, 0), "C1": (119, 57, 0), "D30": (119, 63.5, 0), "D31": (119, 70, 0),
    "R40": (119, 76.5, 0), "C3": (119, 83, 0),
    "JP1": (133, 44, 0), "JP2": (139, 44, 0),
    "R15": (47, 58, 0),
    # rev 2.6: a latching Micro-Fit 3.0. Rev 2.9: moved to the right-hand strip under the E-BOX sensor (its own
    # TILT box): the three resistors standing in a row at the top, the plug under them, pins top to bottom
    # (its SDA / SCL join the I2C bus at the ADC socket a few cm away, instead of running down the whole strip)
    # the plug standing in the strip, its three resistors lying under the logo, each in line with its pin
    "J13": (154.8, TILT_Y, 270),
    "R85": (138.5, TILT_Y + 2.6, 0), "R83": (138.5, TILT_Y + 6.4, 0), "R84": (138.5, TILT_Y + 10.2, 0),
}
# optocoupler channels: one column each, lined up over their connectors
for x0, name, u, i in [(47, "TACH", "U4", 4), (61, "OIL", "U1", 1)]:
    P[u] = (x0, 66, 0)
    P[f"D{10 + i}"] = (x0 + 2.5, 74, 0)
    P[f"R{10 + i}"] = (x0, 80, 0)
    P[f"D{20 + i}"] = (x0, 86, 0)
# monitored switch columns (filter, temp): status LED stays in the same row as the others
for x0, i in [(75, 2), (89, 3)]:
    k = 2 * (i - 2)
    P[f"C{4 + (i - 2)}"] = (x0, 54, 0)
    P[f"R{50 + k}"] = (x0, 58.5, 0)
    P[f"R{51 + k}"] = (x0, 63, 0)
    P[f"D{34 + k}"] = (x0, 67.5, 0)
    P[f"D{10 + i}"] = (x0 + 2.5, 74, 0)
    P[f"R{10 + i}"] = (x0, 80, 0)
    P[f"D{35 + k}"] = (x0, 86, 0)
# test point strip
TP_LABELS = ["BAT IN", "12V ON", "HORN 12V", "5V", "3V3", "GND", "GND", "GND", "BATT", "FUEL",
             "ENG OIL", "HYD FILT", "HYD TEMP", "TACH", "HORN CTRL", "BTN"]
for i in range(16):
    P[f"TP{i + 1}"] = (8 + i * 8.8, 34.5, 0)
# H4 moves up from the corner (rev 2.1) to make room for the LIGHTS connector
P.update({"H1": (4.5, 4.5 - TOP, 0), "H2": (157.5, 4.5 - TOP, 0), "H3": (4.5, 117.0, 0), "H4": (157.5, 117.0, 0)})
# rev 2.8: extra M3 holes near the middle of each side, against vibration (top one beside the ribbon header)
P.update({"H15": (94.0, 4.5 - TOP, 0), "H16": (72.2, 117.0, 0), "H17": (4.5, 62.0, 0), "H18": (157.5, 33.5, 0),
          "H19": (70.0, 56.0, 0)})          # and one near the centre, where the board flexes most
# rev 2.7: TEMPERATURE column on the new right-hand strip (x 150-162): probe connector, its resistors,
# the board sensor and its pull-up, top to bottom
P.update({"J14": (154.8, 38.0 + TEMP_DY, 270), "R87": (153.6, 50.0 + TEMP_DY, 270), "R88": (158.4, 50.0 + TEMP_DY, 270),
          "U11": (153.5, 62.5 + TEMP_DY, 0), "R86": (156.0, 67.0 + TEMP_DY, 270)})
# rev 3.0: AUX plug to the CHT board (2x3 Micro-Fit, turned on its side) under the TEMP column; its two
# resistors standing in the strip between the power-hold test points and the column's edge line
AUX_X, AUX_Y = 157.8, 97.5                     # pin 1
P.update({"J18": (AUX_X, AUX_Y, 270), "R96": (148.0, 93.4, 270), "R97": (148.0, 103.6, 270)})

# coil tach input. Rev 2.4: everything that sees the raw coil voltage is in the boxed HIGH VOLTAGE corner on
# the left edge: its own plug J12 (plug face flush with the edge), R80 -> R81 folded back in two rows, then the
# 15 V clamp (C11, D45). Only the clamped (<= 15 V) signal leaves the corner, to R82 / D39 / U10 in the middle.
P.update({"J12": (10.53, 46.5, 270), "R80": (19.5, 44.5, 0), "R81": (32.2, 49.5, 180),
          "C11": (19.5, 54.5, 0), "D45": (27.3, 54.5, 0),
          "R82": (60.5, 47.5, 0), "D39": (71.5, 48.77, 0), "U10": (79.0, 47.5, 0)})

# light sensing (rev 2.1): right-hand strip, one block per light: optocoupler + LED, then resistor + diode
for i, (u, r, led, dz) in enumerate([("U7", "R17", "D18", "D28"), ("U8", "R18", "D19", "D29"), ("U9", "R19", "D20", "D38")]):
    y = 63.0 + i * 10.0
    P[u], P[led] = (129.5, y, 0), (141.0, y + 1.27, 0)
    P[r], P[dz] = (129.5, y + 6.5, 0), (141.0, y + 6.5, 0)

# power-hold band (rev 2.0): 12 columns x 3 rows between the old layout and the connectors
HOLD_ROWS = (95.0, 103.0, 111.0)
HOLD_COLS = [
    ["Q2", None, "D40"], ["R60", "R61", "R62"], ["R63", "R64", "Q3"], ["R65", "Q4", "R66"],
    ["C7", "R67", "D41"], ["R68", "D42", None], ["U6", None, None], ["C8", "R70", "R69"],
    ["R71", "D43", "C9"], ["R72", "R73", "C10"], ["R16", "D16", "D27"], ["U5", "R74", "D17"],
]
for c, col in enumerate(HOLD_COLS):
    x0 = 4.0 + c * 10.6
    for r, ref in enumerate(col):
        if ref is None:
            continue
        x, y = x0, HOLD_ROWS[r]
        if ref == "Q2":
            x, y = x0 + 1.5, 99.0                    # TO-220 standing up, between rows 1 and 2
        elif ref in ("Q3", "Q4"):
            x += 2.5
        elif ref in ("D16", "D17"):
            x += 1.5
        elif ref == "C7":
            x, y = x + 2.0, y + 0.8
        elif ref == "U6":
            y = HOLD_ROWS[0] - 1.0                   # DIP-16 spans all three rows
        P[ref] = (x, y, 0)
for i, ref in enumerate(["TP17", "TP18", "TP19", "TP20"]):
    P[ref] = (136.0, 94.0 + i * 6.0, 0)

PARTS = [p for p in PARTS if p["fp"]]          # skip schematic-only symbols (power flags)
# reference labels in the light-sensing strip: on the body (R, U), under the LED, beside the diode
LIGHT_REF_AT = {}
for u, r, led, dz in [("U7", "R17", "D18", "D28"), ("U8", "R18", "D19", "D29"), ("U9", "R19", "D20", "D38")]:
    LIGHT_REF_AT.update({u: (3.81, 1.27), r: (3.81, 0.0), led: (1.27, 3.3), dz: (6.8, 0.0)})
LIGHT_REF_AT.update({"R80": (6.35, 0.0), "R81": (-6.35, 0.0)})        # coil resistors: label on the body
FLAT_REF = {"R83", "R84", "R85"}         # rev 2.9: the TILT resistors lie flat: label along the body
VERT_REF = {"R86", "R87", "R88", "R89", "R90", "R91", "R92"}                                       # standing resistors: label along the body
VERT_CAP = {"C12", "C13", "C14", "C15"}
missing = [p["ref"] for p in PARTS if p["ref"] not in P]
assert not missing, missing

# ---------------------------------------------------------------- net names, exactly as the schematic has them
# (kicad-cli sch export netlist, run by build.sh). Supplies and labelled signals keep their design.py names
# (GND, +12V, /COIL_IN, ...); short nets inside a block get KiCad's own names (Net-(R61-Pad2)).
import re as _re
_nl = open(os.path.join(os.path.dirname(OUT) or ".", "netlist.net")).read()
PIN_NET = {}
for m in _re.finditer(r'\(net\s+\(code "\d+"\)\s+\(name "((?:[^"\\]|\\.)*)"\)(.*?)\n\t\t\)', _nl, _re.S):
    for r_, n_ in _re.findall(r'\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)', m.group(2)):
        PIN_NET[(r_, n_)] = m.group(1).replace('\\"', '"')
KNAME = {}
for p in PARTS:
    for num, net in p["pins"].items():
        if net:
            k = PIN_NET[(p["ref"], num)]
            assert KNAME.setdefault(net, k) == k, f"{net} has two names in the schematic"
PIN_NET = {k: v for k, v in PIN_NET.items() if any(p["ref"] == k[0] and p["pins"].get(k[1]) for p in PARTS)}

# ---------------------------------------------------------------- board + project settings
os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
board = pcbnew.NewBoard(OUT)
board.SetCopperLayerCount(2)
ds = board.GetDesignSettings()
ds.m_TrackMinWidth = MM(0.25)
ds.m_MinClearance = MM(0.25)
ds.m_ViasMinSize = MM(0.6)
ds.m_MinThroughDrill = MM(0.3)
ns = ds.m_NetSettings
dflt = ns.GetDefaultNetclass()
dflt.SetTrackWidth(MM(DEFAULT_TRACK)); dflt.SetClearance(MM(DEFAULT_CLEAR))
dflt.SetViaDiameter(MM(0.8)); dflt.SetViaDrill(MM(0.4))
for cname, (tw, cl, members) in NETCLASSES.items():
    nc = pcbnew.NETCLASS(cname)
    nc.SetTrackWidth(MM(tw)); nc.SetClearance(MM(cl))
    nc.SetViaDiameter(MM(1.2 if tw >= 1.0 else 0.9)); nc.SetViaDrill(MM(0.6 if tw >= 1.0 else 0.45))
    ns.SetNetclass(cname, nc)
    for m in members:
        ns.SetNetclassPatternAssignment(KNAME[m], cname)

netobj = {}
# create the nets in design.py's name order (the order the router has always seen them in)
_design_name = {v: k for k, v in KNAME.items()}
for name in sorted(set(PIN_NET.values()), key=lambda n: "/" + _design_name.get(n, n)):
    ni = pcbnew.NETINFO_ITEM(board, name)
    board.Add(ni)
    netobj[name] = ni

# 3D models KiCad doesn't ship. Molex's STEP for the TILT connector: download it free from molex.com (part
# 43650-0415, CAD models) into kicad/3d/. It isn't in the repository (Molex's terms), so without it KiCad just
# shows the pads. Rotation / offset found by rendering: pins in the pads, housing on the board, latch to the notch.
MODEL_3D = {"J13": ("${KIPRJMOD}/3d/436500415.stp", (90, 0, 0), (4.5, -2.0, 9.9)),
            # same Molex series, 3 pins: download 43650-0315 the same way (its STEP origin sits elsewhere)
            "J14": ("${KIPRJMOD}/3d/436500315.stp", (90, 0, 0), (0.0, 0.2, 9.9))}

link = json.load(open("sch_uuids.json"))
for p in PARTS:
    lib, name = p["fp"].split(":")
    fp = pcbnew.FootprintLoad(f"{FPDIR}/{lib}.pretty", name)
    fp.SetFPIDAsString(p["fp"])
    fp.SetReference(p["ref"])
    fp.SetValue(p["value"])
    fp.SetField("Description", p["desc"])
    fp.SetPath(pcbnew.KIID_PATH("/" + link["parts"][p["ref"]]))
    if p["ref"] in ("H5", "H6", "H7", "H8", "H11", "H12"):   # module standoff holes 3.81 mm from the sockets' end pins, as
        for g in list(fp.GraphicalItems()):          # on the module itself: drop their screw-head courtyards, which
            if g.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):   # overlap the sockets' by design (see PROJECT_RULES)
                fp.Remove(g)
    if p["ref"] in MODEL_3D:                         # manufacturer 3D model kept with the project (see README)
        path, mrot, moff = MODEL_3D[p["ref"]]
        for i in range(len(fp.Models())):            # index it: iterating gives copies, and changes are lost
            m = fp.Models()[i]
            m.m_Filename, m.m_Rotation, m.m_Offset = path, pcbnew.VECTOR3D(*mrot), pcbnew.VECTOR3D(*moff)
    x, y, rot = P[p["ref"]]
    fp.SetPosition(V(x, y))
    fp.SetOrientationDegrees(rot)
    board.Add(fp)
    for pad in fp.Pads():
        num = pad.GetNumber()
        net = p["pins"].get(num)
        if net:
            pad.SetNet(netobj[PIN_NET[(p["ref"], num)]])
        elif num:          # no-connect pin: KiCad's schematic names it "unconnected-(REF-PINNAME-PadN)"
            pname = link.get("pin_names", {}).get(p["ref"], {}).get(num) or f"Pin_{num}"
            nc = pcbnew.NETINFO_ITEM(board, f"unconnected-({p['ref']}-{pname}-Pad{num})")
            board.Add(nc)
            pad.SetNet(nc)
    ref = fp.Reference()
    ref.SetTextSize(SZ(1.0, 1.0)); ref.SetTextThickness(MM(0.15))
    if p["ref"] in LIGHT_REF_AT:                       # tight light-sensing strip: place labels by hand
        dx, dy = LIGHT_REF_AT[p["ref"]]
        ref.SetPosition(V(x + dx, y + dy)); ref.SetTextAngleDegrees(0)
    if p["ref"] in VERT_REF:
        ref.SetPosition(V(x, y + 3.81)); ref.SetTextAngleDegrees(90); ref.SetTextSize(SZ(0.8, 0.8))
    if p["ref"] in FLAT_REF:
        ref.SetPosition(V(x + 3.81, y)); ref.SetTextAngleDegrees(0); ref.SetTextSize(SZ(0.8, 0.8))
    if p["ref"] in ("R96", "R97"):       # rev 3.0: standing beside the AUX box: label on the left, along the body
        ref.SetPosition(V(x - 2.3, y + 3.81)); ref.SetTextAngleDegrees(90); ref.SetTextSize(SZ(0.8, 0.8))
    if p["ref"] in VERT_CAP:            # standing disc capacitors: label along the body
        ref.SetPosition(V(x, y + 2.5)); ref.SetTextAngleDegrees(90); ref.SetTextSize(SZ(0.8, 0.8))
    if p["ref"].startswith(("TP", "H")) or p["ref"] in ("F1", "F2", "J2", "J3", "J4", "J5", "J6", "J7", "J8", "J9", "J10", "J11", "J12", "J13", "J14", "J15", "J16", "J17", "J18"):
        ref.SetVisible(False)

# ---------------------------------------------------------------- copper-free rings under the standoffs
# rev 2.8: brass standoffs, screw heads and washers must sit on bare board, never on a trace or the ground pour
# (solder mask alone wears through under vibration). No tracks, vias or fill within these radii, both sides.
import math as _math
KEEPOUT_R = {"M3": 4.0, "M2.5": 3.0}
for p in PARTS:
    if not p["ref"].startswith("H"):
        continue
    hx, hy, _ = P[p["ref"]]
    rk = KEEPOUT_R["M2.5" if p["value"] == "M2.5" else "M3"]
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowTracks(True); z.SetDoNotAllowVias(True); z.SetDoNotAllowZoneFills(True)
    z.SetDoNotAllowPads(False); z.SetDoNotAllowFootprints(False)
    ls = pcbnew.LSET(); ls.AddLayer(pcbnew.F_Cu); ls.AddLayer(pcbnew.B_Cu); z.SetLayerSet(ls)
    ol = z.Outline(); ol.NewOutline()
    for k in range(32):
        a_ = 2 * _math.pi * k / 32
        v = V(hx + rk * _math.cos(a_), hy + rk * _math.sin(a_))
        ol.Append(v.x, v.y)
    z.SetZoneName(f"standoff {p['ref']}")
    board.Add(z)
    # a hole near an edge: also keep the strip between it and that edge clear, so no track squeezes past
    for x0, y0, x1, y1 in ((0, hy - rk, hx, hy + rk), (hx, hy - rk, W, hy + rk),
                           (hx - rk, -TOP, hx + rk, hy), (hx - rk, hy, hx + rk, H)):
        near = (x0 == 0 and hx - rk < 2) or (x1 == W and hx + rk > W - 2) or \
               (y0 == -TOP and hy - rk < -TOP + 2) or (y1 == H and hy + rk > H - 2)
        if not near:
            continue
        e = pcbnew.ZONE(board)
        e.SetIsRuleArea(True)
        e.SetDoNotAllowTracks(True); e.SetDoNotAllowVias(True); e.SetDoNotAllowZoneFills(True)
        e.SetDoNotAllowPads(False); e.SetDoNotAllowFootprints(False)
        e.SetLayerSet(ls)
        o = e.Outline(); o.NewOutline()
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            v = V(x, y); o.Append(v.x, v.y)
        e.SetZoneName(f"standoff {p['ref']} edge")
        board.Add(e)

# rev 2.9: a thin no-track border all round, so the router never runs copper inside the 0.5 mm edge clearance
EDGE_KEEP = 0.8
for x0, y0, x1, y1 in ((0, -TOP, W, -TOP + EDGE_KEEP), (0, H - EDGE_KEEP, W, H),
                       (0, -TOP, EDGE_KEEP, H), (W - EDGE_KEEP, -TOP, W, H)):
    e = pcbnew.ZONE(board)
    e.SetIsRuleArea(True)
    e.SetDoNotAllowTracks(True); e.SetDoNotAllowVias(True); e.SetDoNotAllowZoneFills(False)
    e.SetDoNotAllowPads(False); e.SetDoNotAllowFootprints(False)
    ls = pcbnew.LSET(); ls.AddLayer(pcbnew.F_Cu); ls.AddLayer(pcbnew.B_Cu); e.SetLayerSet(ls)
    o = e.Outline(); o.NewOutline()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        v = V(x, y); o.Append(v.x, v.y)
    e.SetZoneName("edge border")
    board.Add(e)

# ---------------------------------------------------------------- outline (rounded rectangle)
R_CORNER = 3.0


def edge_line(x1, y1, x2, y2):
    s = pcbnew.PCB_SHAPE(board); s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(V(x1, y1)); s.SetEnd(V(x2, y2)); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(MM(0.1)); board.Add(s)


def edge_arc(cx, cy, sx, sy, angle):
    s = pcbnew.PCB_SHAPE(board); s.SetShape(pcbnew.SHAPE_T_ARC)
    s.SetCenter(V(cx, cy)); s.SetStart(V(sx, sy)); s.SetArcAngleAndEnd(pcbnew.EDA_ANGLE(angle, pcbnew.DEGREES_T), True)
    s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(MM(0.1)); board.Add(s)


r = R_CORNER
T = -TOP
edge_line(r, T, W - r, T); edge_line(W, T + r, W, H - r); edge_line(W - r, H, r, H); edge_line(0, H - r, 0, T + r)
edge_arc(W - r, T + r, W - r, T, 90); edge_arc(W - r, H - r, W, H - r, 90)
edge_arc(r, H - r, r, H, 90); edge_arc(r, T + r, 0, T + r, 90)

# ---------------------------------------------------------------- silkscreen


def silk(text, x, y, size=1.0, bold=False, align="center", angle=0, layer=pcbnew.F_SilkS):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text); t.SetPosition(V(x, y)); t.SetLayer(layer)
    t.SetMirrored(layer == pcbnew.B_SilkS)                  # the back reads the right way round from behind
    t.SetTextSize(SZ(size, size)); t.SetTextThickness(MM(size * (0.2 if bold else 0.15)))
    t.SetHorizJustify({"center": pcbnew.GR_TEXT_H_ALIGN_CENTER, "left": pcbnew.GR_TEXT_H_ALIGN_LEFT,
                       "right": pcbnew.GR_TEXT_H_ALIGN_RIGHT}[align])
    if angle:
        t.SetTextAngleDegrees(angle)
    board.Add(t)


def silk_box(x1, y1, x2, y2, width=0.15):
    s = pcbnew.PCB_SHAPE(board); s.SetShape(pcbnew.SHAPE_T_RECT)
    s.SetStart(V(x1, y1)); s.SetEnd(V(x2, y2)); s.SetLayer(pcbnew.F_SilkS); s.SetWidth(MM(width)); board.Add(s)


# harness connectors: title + one label per pin
PIN_LABELS = {
    "J2": ("POWER IN", ["BAT+", "IGN", "GND"]), "J3": ("TO BUCK", ["+12V", "GND"]), "J7": ("HORN", ["+", "-"]),
    "J5": ("TACH", ["+12V", "SIG", "GND"]), "J4": ("SWITCHES", ["OIL", "FILT", "TEMP", "GND"]),
    "J6": ("FUEL", ["SEND", "GND"]), "J8": ("SILENCE", ["BTN", "GND"]), "J11": ("LIGHTS", ["FRONT", "REAR", "WORK"]),
}
for ref, (title, pins) in PIN_LABELS.items():
    x, y, _ = P[ref]
    for i, lab in enumerate(pins):
        silk(lab, x + i * 5.08, y - 3.6, 0.9, bold=True)
    silk(title, x + (len(pins) - 1) * 5.08 / 2, y - (7.8 if ref == "J4" else 5.6), 1.1, bold=True)


def silk_line(x1, y1, x2, y2, width=0.15):
    s = pcbnew.PCB_SHAPE(board); s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(V(x1, y1)); s.SetEnd(V(x2, y2)); s.SetLayer(pcbnew.F_SilkS); s.SetWidth(MM(width)); board.Add(s)


# J4: say which switches are ENGINE and which are HYDRAULIC, so they can't be mixed up
x4, y4, _ = P["J4"]
silk("ENGINE", x4, y4 - 5.6, 0.8, bold=True)
silk_line(x4 - 2.2, y4 - 4.75, x4 + 2.2, y4 - 4.75)
silk("HYDRAULIC", x4 + 5.08 * 1.5, y4 - 5.6, 0.8, bold=True)
silk_line(x4 + 5.08 - 2.2, y4 - 4.75, x4 + 2 * 5.08 + 2.2, y4 - 4.75)

# test point strip labels
for i, lab in enumerate(TP_LABELS):
    x, y, _ = P[f"TP{i + 1}"]
    silk(lab, x, y + 3.0, 0.85, bold=True)

# power LED labels
for led, lab in [("D2", "12V ON"), ("D3", "HORN/F2"), ("D4", "5V"), ("D5", "3V3")]:   # (moved with the LEDs)
    x, y, _ = P[led]
    silk(lab, x + 1.27, y + 3.6, 0.9, bold=True)
# channel status LED labels
for led, lab in [("D14", "TACH"), ("D11", "ENG OIL"), ("D12", "HYD FILT"), ("D13", "HYD TEMP")]:
    x, y, _ = P[led]
    silk(lab, x + 4.3, y + 0.4, 0.9, bold=True, align="left")
silk("HORN ON", P["D26"][0] + 1.27, P["D26"][1] + 3.6, 0.9, bold=True)
silk("KEY", P["D16"][0] + 1.27, P["D16"][1] + 2.9, 0.8, bold=True)
silk("COIL", P["D39"][0] + 1.27, P["D39"][1] + 3.0, 0.8, bold=True)
silk("COIL TACH", 89.0, 47.9, 0.8, bold=True, align="left")
silk("(from J12)", 89.0, 49.6, 0.8, align="left")
for led, lab in [("D18", "FRONT"), ("D19", "REAR"), ("D20", "WORK")]:
    silk(lab, P[led][0] + 3.6, P[led][1] + 0.4, 0.8, bold=True, align="left")
silk("HOLD", P["D17"][0] + 1.27, P["D17"][1] + 2.9, 0.8, bold=True)
for ref, lab in [("TP17", "FUSED 12V"), ("TP18", "IGN"), ("TP19", "HOLD"), ("TP20", "TIMER")]:
    x, y, _ = P[ref]
    silk(lab, x + 2.4, y + 0.4, 0.85, bold=True, align="left")

# module outlines
silk_box(6, 7, 26, 24.5); silk("MONO AMP", 16, 17.6, 1.1, bold=True); silk("MAX98357A", 16, 19.6, 0.9)
silk("Adafruit 3006", 16, 21.4, 0.8)
# stereo amp module outline (25.4 x 19.05 mm, row 2.54 mm in from its edge), pin names below its row
silk_box(STEREO_X - 12.7, STEREO_ROW - 16.51, STEREO_X + 12.7, STEREO_ROW + 2.2)
silk("STEREO AMP", STEREO_X, STEREO_ROW - 9.0, 1.1, bold=True); silk("MAX98357A x2", STEREO_X, STEREO_ROW - 7.0, 0.9)
silk("Adafruit 6513", STEREO_X, STEREO_ROW - 5.2, 0.8)
for i, lab in enumerate(["VDD", "GND", "BCLK", "LRC", "DIN", "GAIN"]):
    silk(lab, STEREO_X - 6.35 + i * 2.54, STEREO_ROW + 5.5, 0.8, align="left", angle=90)
silk("FIT ONE AMP ONLY  (mono or stereo)", 30.0, 4.6, 0.9, bold=True)   # rev 2.9: above both amp outlines
# rev 2.9: button pod plug J17: pin names beside the pins (like TEMP PROBE), title, fan LED
for i, lab in enumerate(["LEFT", "RIGHT", "OK", "BACK", "SILENCE", "GND", "FAN +12V", "FAN -"]):
    silk(lab, POD_X + 38.6, 6.6 + i * 3.0 + 0.4, 0.8, bold=True, align="right")
silk("BUTTON POD", POD_X + 30.0, 30.4, 0.9, bold=True)
silk("FAN ON", POD_X + 29.8, 14.2, 0.8, bold=True)
for i, lab in enumerate(["LRC", "BCLK", "DIN", "GAIN", "SD", "GND", "VIN"]):
    silk(lab, 8 + i * 2.54, 31.6, 0.8, align="left", angle=90)
# ADS1115 module outline (25.4 x 17.8 mm, its rows 2.54 mm in from its long edges), pin names outside it
silk_box(ADS_X - 12.7, 26 - 15.24, ADS_X + 12.7, 26 + 2.2)
silk("ADS1115", ADS_X, 18.6, 1.1, bold=True); silk("ADC module", ADS_X, 20.6, 0.9)
for i, lab in enumerate(["VIN", "GND", "SCL", "SDA", "ADDR", "ALRT"]):
    silk(lab, ADS_X - 6.35 + i * 2.54, 31.6, 0.8, align="left", angle=90)
for i, lab in enumerate(["A+", "A3", "A2", "A1", "A0", "A-"]):
    silk(lab, ADS_X - 6.35 + i * 2.54, 10.0, 0.8, align="left", angle=90)
silk("TO PI (40-pin ribbon)", J1_X + 24.0, J1_Y + 4.9, 1.0, bold=True)                # just under the header

# fuel jumper table

silk("FUEL MODE", 136, 52.1, 0.9, bold=True)
for k in range(3):                                   # JP1 pin numbers (pin 1 = square pad, at the top)
    silk(str(k + 1), P["JP1"][0] - 2.1, P["JP1"][1] + k * 2.54 + 0.4, 0.8, bold=True)
silk("A sender only:", 136, 53.9, 0.8); silk("JP1 1-2, JP2 ON", 136, 55.4, 0.8)
silk("B gauge + dash:", 136, 57.2, 0.8); silk("JP1 2-3, JP2 OFF", 136, 58.7, 0.8)

# fuse labels
silk("F1  MAIN  5A", P["F1"][0] + 5, P["F1"][1] - 3.2, 0.9, bold=True)
silk("F2  HORN  1A", P["F2"][0] + 5, P["F2"][1] - 3.2, 0.9, bold=True)

# title block
# rev 2.8: title block in the top strip, beside the logo (the ribbon to the Pi leaves the strip clear above J1)
# rev 2.9: right of the logo
TITLE_X = 133.5
silk("M.O.S.S.", TITLE_X, -16.0, 1.8, bold=True, align="left")     # Maintenance, Operations, and Service System
silk("BREAKOUT BOARD", TITLE_X, -12.8, 1.5, bold=True, align="left")
silk("Bobcat M700", TITLE_X, -9.8, 1.0, bold=True, align="left")
silk("rev 3.0  2026-10", TITLE_X, -7.6, 1.0, align="left")
silk("Project Moon Pi", TITLE_X, -5.4, 0.9, align="left")
# rev 2.7: TEMPERATURE column: probe pin names beside the connector
for i, lab in enumerate(["GND", "DQ", "3V3"]):
    silk(lab, 158.2, 38.0 + TEMP_DY + i * 3.0 + 0.4, 0.8, bold=True, align="left")
silk("PROBE", 155.9, 33.2 + TEMP_DY, 0.8, bold=True)
silk("E-BOX TEMP", 155.9, 79.8 + TEMP_DY, 0.8, bold=True)       # rev 2.9: E-BOX = the electronics box
silk("SENSOR", 155.9, 81.4 + TEMP_DY, 0.8, bold=True)
# rev 2.9: TILT sensor plug on the right-hand strip: pin names beside the pins, like the PROBE plug
for i, lab in enumerate(["GND", "3V3", "SDA", "SCL"]):
    silk(lab, 158.2, TILT_Y + i * 3.0 + 0.4, 0.8, bold=True, align="left")
silk("Every LED: lit = signal present.  HYD FILT/TEMP LED blinking = wire broken", 46.0, 41.2, 0.8, align="left")
silk("4.7k resistor across each HYD FILT/TEMP switch, at the switch", 46.0, 42.9, 0.8, align="left")

# ---------------------------------------------------------------- circuit group boxes (rev 2.4)
# Each block of the circuit gets an outline with its name set into a gap in the top (or bottom) line.


def text_width(text, size, bold):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text); t.SetTextSize(SZ(size, size)); t.SetTextThickness(MM(size * (0.2 if bold else 0.15)))
    return t.GetBoundingBox().GetWidth() / 1e6


def group_box(pts, title, tx, size=0.85, width=0.15, title_on=0, gap_pad=0.6, closed=True, show_title=True):
    """Outline through pts (x, y); the title sits centred at x = tx on edge number title_on, in a gap.
    show_title=False leaves the same gap with no text (the inner line of a double outline)."""
    edges = list(zip(pts, pts[1:] + ([pts[0]] if closed else [])))
    tw = text_width(title, size, True)
    for i, ((x1, y1), (x2, y2)) in enumerate(edges):
        if i == title_on:                       # horizontal edge with the title gap
            ty = y1
            a, b = sorted((x1, x2))
            g1, g2 = tx - tw / 2 - gap_pad, tx + tw / 2 + gap_pad
            if g1 > a:
                silk_line(a, ty, g1, ty, width)
            if g2 < b:
                silk_line(g2, ty, b, ty, width)
            if show_title:
                silk(title, tx, ty + size * 0.42, size, bold=True)
        else:
            silk_line(x1, y1, x2, y2, width)


def rect(x1, y1, x2, y2):
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


group_box(rect(43.0 + LED_DX, 16.9 + LED_DY, 104.0 + LED_DX, 26.9 + LED_DY), "POWER LEDS", 73.5 + LED_DX)
group_box(rect(3.0, 32.3, 146.5, 39.3), "TEST POINTS", 74.75)
# the rest share edges, so each line is drawn once:
#   inputs box | power box to its left, analog box to its right, lights box under the analog box's step,
#   power-hold box below all of them (its top line steps down under the lights strip)
group_box([(0.8, 57.7), (44.6, 57.7)], "POWER IN / FUSES / HORN DRIVER", 22.0, closed=False)
silk_line(44.6, 88.8, 44.6, 90.6)
group_box([(103.4, 44.0), (44.6, 44.0), (44.6, 88.8), (103.4, 88.8)],
          "ENGINE + HYDRAULIC INPUTS  (TACH, OIL, FILTER, TEMP)", 72.9, title_on=2, closed=False)
group_box([(149.75, 40.3), (103.4, 40.3), (103.4, 88.8), (128.05, 88.8), (128.05, 60.0)],
          "BATTERY / FUEL / BUTTON", 115.0, title_on=2, closed=False)
group_box([(128.05, 60.0), (149.75, 60.0)], "LIGHTS ON", 141.5, closed=False)
silk_line(128.05, 88.8, 128.05, 90.6)
group_box([(149.75, 114.75), (1.2, 114.75), (1.2, 90.6), (128.05, 90.6), (128.05, 91.7), (149.75, 91.7)],
          "POWER HOLD: stays on after key-off while the Pi saves and shuts down (3 min max)", 37.0,
          title_on=2, closed=False)       # open on the right: the board edge closes it, like the boxes above

# rev 2.7: the board is wider, so the blocks that ran to the old right edge get a right-hand line,
# and the new TEMPERATURE column has its own outline
silk_line(149.75, 40.3, 149.75, 114.75)
group_box(rect(150.4, 31.2 + TEMP_DY, 161.4, 83.4 + TEMP_DY), "TEMP", 155.9)
group_box(rect(136.2, TILT_Y - 3.8, 161.4, TILT_Y + 15.4), "TILT (I2C)", 148.8)
group_box(rect(150.4, 92.0, 161.4, 111.4), "AUX", 155.9)                 # rev 3.0: to the CHT board
silk("CHT + BRAKE", 155.9, 110.0, 0.8, bold=True)

# HIGH VOLTAGE corner: double outline, warning triangles, open to the board edge where J12 plugs in
HV = (0.0, 40.6, 39.6, 57.0)
for k, off in enumerate((0.0, 0.6)):
    x1, y1, x2, y2 = HV[0], HV[1] + off, HV[2] - off, HV[3] - off
    pts = [(x1 + 0.6, y1), (x2, y1), (x2, y2), (x1 + 0.6, y2)]
    group_box(pts, "HIGH VOLTAGE - IGNITION COIL", 22.0, size=1.0, width=0.25, closed=False, gap_pad=3.6,
              show_title=(k == 0))


def warn_triangle(cx, cy, h=2.3):
    w = h * 1.15
    tri = [(cx, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
    for a, b in zip(tri, tri[1:] + tri[:1]):
        silk_line(a[0], a[1], b[0], b[1], 0.2)
    silk("!", cx, cy + 0.55, 0.8, bold=True)


tw_hv = text_width("HIGH VOLTAGE - IGNITION COIL", 1.0, True)
warn_triangle(22.0 - tw_hv / 2 - 2.0, HV[1] + 0.3)
warn_triangle(22.0 + tw_hv / 2 + 2.0, HV[1] + 0.3)
silk("COIL", 14.2, 46.9, 0.8, bold=True, align="left")     # J12 pin labels, between the plug and R80/R81
silk("GND", 14.2, 51.98, 0.8, bold=True, align="left")

# ---------------------------------------------------------------- Project Moon Pi logo (back silkscreen)
# logo_silk.json comes from make_logo_silk.py. It's on the back, so it's mirrored left-right here
# and reads the right way round when you turn the board over. Placed in the largest pad-free area.
LOGO_CENTRE, LOGO_WIDTH = (116.0, -10.2), 30.0   # rev 2.9: larger, left of the title (30 mm is as big as the strip allows)


def add_logo(path, centre, width_mm, layer=pcbnew.B_SilkS, mirror=True):
    data = json.load(open(path))
    s = width_mm / data["width_px"]                         # mm per pixel
    cx, cy = centre
    x_left, y_top = cx - width_mm / 2, cy - data["height_px"] * s / 2
    ps = pcbnew.SHAPE_POLY_SET()
    eps = 0.0005                                            # rows overlap a hair so they merge cleanly
    for y, runs in data["rows"]:
        for x0, x1 in runs:
            if mirror:
                x0, x1 = data["width_px"] - x1, data["width_px"] - x0
            ps.NewOutline()
            for px, py in [(x0, y), (x1, y), (x1, y + 1), (x0, y + 1)]:
                ps.Append(MM(x_left + px * s), MM(y_top + py * s + (eps if py > y else -eps) + TOP))
    ps.Simplify()                                          # union all the pixel rows into shapes with holes
    ps.Fracture()                                          # silkscreen polygons can't have holes: bridge them
    for i in range(ps.OutlineCount()):                     # one shape per piece (a shape keeps one outline)
        piece = pcbnew.SHAPE_POLY_SET()
        piece.AddOutline(ps.COutline(i))
        shape = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_POLY)
        shape.SetPolyShape(piece); shape.SetFilled(True); shape.SetWidth(0); shape.SetLayer(layer)
        board.Add(shape)
    return ps.OutlineCount()


n = add_logo(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo_silk.json"), LOGO_CENTRE, LOGO_WIDTH,
             layer=pcbnew.F_SilkS, mirror=False)
print("logo:", n, "silkscreen shapes on top")

# rev 2.9: a few fun lines on the back (the owner's, plus three of Claude's), in pad-free spots at odd sizes and angles.
# Back silkscreen, mirrored so they read right when the board is turned over. (text, x, y, size, angle)
FUN = [("DON'T LET THE MAGIC SMOKE OUT", 87.4, -8.6, 2.6, 0),
       ("One small step for man,\none giant leap for skid-steer kind", 35.5, 3.1, 1.8, 0),
       ("do you lift, bro?", 139.5, 129.4, 2.0, 8),
       ("hi mom", 17.9, 63.9, 1.2, -15),
       ("Keep the shiny side up", 22.4, 129.4, 1.8, 0),                         # Claude's
       ("Houston, we have a breakout board", 147.3, 48.0, 1.4, 90),             # Claude's
       ("No bobcats were harmed in the making of this board", 86.3, 90.1, 1.1, 0)]   # Claude's
for text, x, y, size, angle in FUN:
    silk(text, x, y, size, bold=True, angle=angle, layer=pcbnew.B_SilkS)

# rev 2.9: and the dash's little skid steer (its tilt picture, dash.py SIDE_VIEW) climbing a dirt hill, on the back.
SKID_SIDE = {"body": [(-56, -14), (52, -14), (52, -46), (-56, -46)], "cab": [(-30, -46), (26, -46), (20, -100), (-26, -100)],
             "window": [(-18, -56), (16, -56), (12, -90), (-15, -90)], "engine": [(-56, -46), (-34, -46), (-34, -66), (-56, -66)],
             "arm": [(-42, -90), (-37, -94), (58, -49), (55, -44)], "bucket": [(52, -52), (76, -52), (82, -4), (56, -2), (50, -20)]}
SKID_WHEELS = [(-32, -18, 18), (32, -18, 18)]
HILL_AT, HILL_SCALE, HILL_SLOPE = (143.0, -0.5), 0.12, 20.0      # ground point (mm), mm per design unit, degrees


def hill_graphic(at, scale, slope):
    ox, oy = at
    c, s_ = math.cos(math.radians(-slope)), math.sin(math.radians(-slope))

    def pt(x, y):                                     # design units on the slope -> board mm, mirrored for the back
        rx, ry = x * c - y * s_, x * s_ + y * c
        return ox - rx * scale, oy + ry * scale

    def poly(pts, width=0.2, filled=False):
        sh = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_POLY)
        sh.SetPolyPoints([V(*q) for q in pts]); sh.SetLayer(pcbnew.B_SilkS)
        sh.SetWidth(MM(width)); sh.SetFilled(filled); board.Add(sh)

    def ring(x, y, r, width):
        sh = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_CIRCLE)
        sh.SetCenter(V(x, y)); sh.SetEnd(V(x + r, y)); sh.SetLayer(pcbnew.B_SilkS); sh.SetWidth(MM(width)); board.Add(sh)

    v = SKID_SIDE
    for k in ("body", "engine", "cab", "window", "bucket"):
        poly([pt(*q) for q in v[k]], 0.22)
    poly([pt(*q) for q in v["arm"]], 0.15, filled=True)
    for x, y, r in SKID_WHEELS:
        cx, cy = pt(x, y)
        ring(cx, cy, r * scale * 0.7, r * scale * 0.6)            # tyre: a thick ring with the hub showing
    # the hill: up the slope under the machine, over a rounded top, down the far side to flat ground
    up = [pt(x, 0) for x in range(-95, 131, 15)]
    top_x, top_y = up[-1]
    base_y = pt(-95, 0)[1]
    crest = [(top_x - 4.0 * math.sin(a / 12 * math.pi / 2), top_y - 0.6 * math.sin(a / 12 * math.pi)) for a in range(1, 13)]
    far = [(crest[-1][0] - 2.0, top_y + 1.2), (crest[-1][0] - 7.0, base_y)]
    poly(up + crest + far + [(up[0][0] + 2.0, base_y)], 0.15, filled=True)
    # flat ground either side, and a few clods kicked up by the back wheel
    for x0, x1 in ((up[0][0] + 5.0, up[0][0] - 1.0), (far[-1][0] + 0.5, far[-1][0] - 4.0)):
        poly([(x0, base_y), (x1, base_y), (x1, base_y + 0.25), (x0, base_y + 0.25)], 0.1, filled=True)
    bx, by = pt(-32, 0)
    for dx, dy, r in ((3.0, -2.2, 0.35), (4.6, -3.4, 0.28), (5.6, -1.6, 0.25), (3.8, -5.0, 0.22)):
        ring(bx + dx, by + dy, r / 2, r)


hill_graphic(HILL_AT, HILL_SCALE, HILL_SLOPE)

pcbnew.SaveBoard(OUT, board)

# The layer stack-up, with the colours the board is ordered in: BLUE solder mask, WHITE silkscreen, lead-free HASL
# (PCBWay's standard finish), 1.6 mm FR4. KiCad's Python can't set it, so it goes into the file as text; the 3D
# renders show it with  kicad-cli pcb render --use-board-stackup-colors.
SOLDER_MASK = "Blue"
_stack = f'''		(stackup
			(layer "F.SilkS" (type "Top Silk Screen") (color "White"))
			(layer "F.Paste" (type "Top Solder Paste"))
			(layer "F.Mask" (type "Top Solder Mask") (color "{SOLDER_MASK}") (thickness 0.01))
			(layer "F.Cu" (type "copper") (thickness 0.035))
			(layer "dielectric 1" (type "core") (thickness 1.51) (material "FR4") (epsilon_r 4.5) (loss_tangent 0.02))
			(layer "B.Cu" (type "copper") (thickness 0.035))
			(layer "B.Mask" (type "Bottom Solder Mask") (color "{SOLDER_MASK}") (thickness 0.01))
			(layer "B.Paste" (type "Bottom Solder Paste"))
			(layer "B.SilkS" (type "Bottom Silk Screen") (color "White"))
			(copper_finish "HAL lead-free")
			(dielectric_constraints no)
		)
'''
_text = open(OUT).read()
if "(stackup" not in _text:
    _i = _text.index("\t(setup\n") + len("\t(setup\n")
    open(OUT, "w").write(_text[:_i] + _stack + _text[_i:])
print("placed", len(PARTS), "footprints on", OUT)

# PROJECT_RULES: every footprint comes fresh from KiCad's library on each build, so "doesn't match the library"
# only ever flags the four ADS1115 standoff holes trimmed above. Silence that one check for this project.
_pro = os.path.splitext(OUT)[0] + ".kicad_pro"
_cfg = json.load(open(_pro))
_cfg.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rule_severities", {})[
    "lib_footprint_mismatch"] = "ignore"
json.dump(_cfg, open(_pro, "w"), indent=2)

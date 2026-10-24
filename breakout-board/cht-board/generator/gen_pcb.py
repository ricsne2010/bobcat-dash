"""Places the CHT + parking brake board (KiCad's Python):  gen_pcb.py out/cht-board.kicad_pcb
Routing and checks are done by build.sh (it reuses the breakout board's route.py)."""
import json
import os
import sys

import pcbnew

from chtboard import (PARTS, REV, W, H, MW, MH, MODULES, HOLES, BOARD_HOLES, STRIP, R_AT, ADDRESS, module_pin,
                      LOGO_CENTRE, LOGO_WIDTH)

FPDIR = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1]
MM = pcbnew.FromMM


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


board = pcbnew.BOARD()
board.SetCopperLayerCount(2)
ds = board.GetDesignSettings()
ds.m_TrackMinWidth = MM(0.25); ds.m_MinClearance = MM(0.25); ds.m_ViasMinSize = MM(0.6); ds.m_MinThroughDrill = MM(0.3)
dflt = ds.m_NetSettings.GetDefaultNetclass()
dflt.SetTrackWidth(MM(0.4)); dflt.SetClearance(MM(0.25)); dflt.SetViaDiameter(MM(0.8)); dflt.SetViaDrill(MM(0.4))

link = json.load(open(os.path.join(HERE, "sch_uuids.json")))
nets = {}
for ref, (lib_id, value, fpid, pins, desc) in PARTS.items():
    for net in pins.values():
        if net and net not in nets:
            nets[net] = pcbnew.NETINFO_ITEM(board, "/" + net)      # local labels in the schematic: "/NAME"
            board.Add(nets[net])


# where pin 1 goes and the footprint's rotation
ROT = {"J1": 0, "U1": 0, "D1": 0, "D2": 0, "J2": 90}            # J2 at 90: the plug opening faces +x
AT = {ref: (x, y, ROT[ref]) for ref, (x, y) in STRIP.items()}
AT.update({ref: (x, y, r) for ref, (x, y, r) in R_AT.items()})
for n in range(1, 5):
    x, y = module_pin(n, 1)
    AT[f"M{n}"] = (x, y, 270 if MODULES[n][2] else 90)      # pins run left to right (flipped: right to left)

for ref, (lib_id, value, fpid, pins, desc) in PARTS.items():
    lib, name = fpid.split(":")
    fp = pcbnew.FootprintLoad(f"{FPDIR}/{lib}.pretty", name)
    fp.SetFPIDAsString(fpid)
    fp.SetReference(ref); fp.SetValue(value); fp.SetField("Description", desc)
    fp.SetPath(pcbnew.KIID_PATH("/" + link[ref]))
    board.Add(fp)
    if ref.startswith("H"):
        fp.SetPosition(V(*HOLES[int(ref[1:]) - 1]))
    else:
        x, y, rot = AT[ref]
        fp.SetOrientationDegrees(rot)
        p1 = [pd for pd in fp.Pads() if pd.GetNumber() == "1"][0].GetPosition()
        fp.Move(V(x, y) - p1)
    for pd in fp.Pads():
        net = pins.get(int(pd.GetNumber())) if pd.GetNumber().isdigit() else None
        if net:
            pd.SetNet(nets[net])
        elif pd.GetNumber():
            nc_net = pcbnew.NETINFO_ITEM(board, f"unconnected-({ref}-Pin_{pd.GetNumber()}-Pad{pd.GetNumber()})")
            board.Add(nc_net); pd.SetNet(nc_net)
    fp.Value().SetVisible(False)
    r = fp.Reference()
    if ref.startswith(("H", "M", "J", "R", "D")):     # R1 / R2: values in the BOM; D1 is labelled BRAKE SET
        r.SetVisible(False)
    else:
        r.SetTextSize(V(0.8, 0.8)); r.SetTextThickness(MM(0.15))

# copper-free rings under the brass standoffs and screw heads (no tracks, vias or ground fill), both sides
import math
for i, (hx, hy) in enumerate(HOLES):
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowTracks(True); z.SetDoNotAllowVias(True); z.SetDoNotAllowZoneFills(True)
    z.SetDoNotAllowPads(False); z.SetDoNotAllowFootprints(False)
    ls = pcbnew.LSET(); ls.AddLayer(pcbnew.F_Cu); ls.AddLayer(pcbnew.B_Cu); z.SetLayerSet(ls)
    ol = z.Outline(); ol.NewOutline()
    for k in range(32):
        a = 2 * math.pi * k / 32
        rr = 4.0 if i < len(BOARD_HOLES) else 3.0
        v = V(hx + rr * math.cos(a), hy + rr * math.sin(a))
        ol.Append(v.x, v.y)
    z.SetZoneName(f"standoff H{i + 1}")
    board.Add(z)

# outline, 1.5 mm corner radius
r = 1.5


def seg(x1, y1, x2, y2):
    s = pcbnew.PCB_SHAPE(board); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(pcbnew.Edge_Cuts)
    s.SetStart(V(x1, y1)); s.SetEnd(V(x2, y2)); s.SetWidth(MM(0.1)); board.Add(s)


def arc(cx, cy, sx, sy):
    s = pcbnew.PCB_SHAPE(board); s.SetShape(pcbnew.SHAPE_T_ARC); s.SetLayer(pcbnew.Edge_Cuts)
    s.SetCenter(V(cx, cy)); s.SetStart(V(sx, sy)); s.SetArcAngleAndEnd(pcbnew.EDA_ANGLE(90, pcbnew.DEGREES_T), True)
    s.SetWidth(MM(0.1)); board.Add(s)


seg(r, 0, W - r, 0); seg(W, r, W, H - r); seg(W - r, H, r, H); seg(0, H - r, 0, r)
arc(W - r, r, W - r, 0); arc(W - r, H - r, W, H - r); arc(r, H - r, r, H); arc(r, r, 0, r)


def silk(text, x, y, size=0.8, angle=0, align="center", layer=pcbnew.F_SilkS, bold=False):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text); t.SetPosition(V(x, y)); t.SetLayer(layer)
    t.SetTextSize(V(size, size)); t.SetTextThickness(MM(size * (0.2 if bold else 0.15)))
    t.SetHorizJustify({"center": pcbnew.GR_TEXT_H_ALIGN_CENTER, "left": pcbnew.GR_TEXT_H_ALIGN_LEFT,
                       "right": pcbnew.GR_TEXT_H_ALIGN_RIGHT}[align])
    t.SetTextAngleDegrees(angle)
    if layer == pcbnew.B_SilkS:
        t.SetMirrored(True)
    board.Add(t)



def sline(x1, y1, x2, y2, w=0.15):
    s = pcbnew.PCB_SHAPE(board); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(pcbnew.F_SilkS)
    s.SetStart(V(x1, y1)); s.SetEnd(V(x2, y2)); s.SetWidth(MM(w)); board.Add(s)


# each module's outline, its cylinder and address, and which edge its thermocouple terminal is on
for n, (ox, oy, flip) in MODULES.items():
    for (a, b) in (((ox, oy), (ox + MW, oy)), ((ox + MW, oy), (ox + MW, oy + MH)),
                   ((ox + MW, oy + MH), (ox, oy + MH)), ((ox, oy + MH), (ox, oy))):
        sline(*a, *b, 0.12)
    cx = ox + MW / 2
    silk(f"CYL {n}   {ADDRESS[n]}", cx, oy + MH / 2 + (1.5 if flip else -1.5), 1.2, bold=True)
    silk("MCP9601", cx, oy + MH / 2 + (3.3 if flip else -3.3), 0.8)
    silk("THERMOCOUPLE", cx, oy + (MH - 1.6 if flip else 1.6), 0.8, bold=True)
    pin = module_pin(n, 1)
    silk("VIN", pin[0], pin[1] + (2.6 if flip else -1.9), 0.8, bold=True)
silk(f"M.O.S.S.  CHT + PARK BRAKE  rev {REV}", 35.2, H / 2 + 0.4, 0.8, bold=True)

# the right-hand strip
jx, jy = STRIP["J1"]
silk("CHT + PARK BRAKE BOARD", 72.8, 1.6, 0.85, bold=True)
silk("AUX TO BREAKOUT J18", jx + 3.0, jy + 8.0, 0.8, bold=True)
silk("1 GND  2 3V3  3 SDA", jx + 3.0, jy + 9.2, 0.8)
silk("4 SCL  5 BRK  6 12V", jx + 3.0, jy + 10.4, 0.8)
dx, dy = STRIP["D1"]
silk("BRAKE", dx + 3.4, dy - 0.2, 0.8, bold=True, align="left")
silk("SET", dx + 3.4, dy + 1.0, 0.8, bold=True, align="left")
bx, by = STRIP["J2"]
silk("PARK BRAKE", bx + 3.5, by - 10.4, 0.85, bold=True)
silk("SW", bx - 3.3, by + 1.6, 0.8, bold=True, align="right")
silk("GND", bx - 3.3, by - 5.08 - 2.4, 0.8, bold=True, align="right")
silk("11 mm M2.5 standoffs under each module", W / 2, H - 1.6, 0.8, layer=pcbnew.B_SilkS)
silk(f"M.O.S.S. CHT + PARK BRAKE BOARD  rev {REV}  2026-10", W / 2, 1.6, 0.8, layer=pcbnew.B_SilkS)


def add_logo(path, centre, width_mm, layer=pcbnew.B_SilkS, mirror=True):
    """The same Project Moon Pi logo as the breakout board (its logo_silk.json), mirrored for the back."""
    data = json.load(open(path))
    s = width_mm / data["width_px"]
    cx, cy = centre
    x_left, y_top = cx - width_mm / 2, cy - data["height_px"] * s / 2
    ps = pcbnew.SHAPE_POLY_SET()
    eps = 0.0005
    for y, runs in data["rows"]:
        for x0, x1 in runs:
            if mirror:
                x0, x1 = data["width_px"] - x1, data["width_px"] - x0
            ps.NewOutline()
            for px, py in [(x0, y), (x1, y), (x1, y + 1), (x0, y + 1)]:
                ps.Append(MM(x_left + px * s), MM(y_top + py * s + (eps if py > y else -eps)))
    ps.Simplify()
    ps.Fracture()
    for i in range(ps.OutlineCount()):
        piece = pcbnew.SHAPE_POLY_SET()
        piece.AddOutline(ps.COutline(i))
        shape = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_POLY)
        shape.SetPolyShape(piece); shape.SetFilled(True); shape.SetWidth(0); shape.SetLayer(layer)
        board.Add(shape)


LOGO = os.path.join(HERE, "..", "..", "generator", "logo_silk.json")
add_logo(LOGO, LOGO_CENTRE, LOGO_WIDTH, layer=pcbnew.F_SilkS, mirror=False)   # top, in the strip
add_logo(LOGO, (MODULES[1][0] + MW / 2, 10.3), 12.0)                         # on the back, behind CYL 1 (no pads there)
pcbnew.SaveBoard(OUT, board)

# blue solder mask, white silkscreen, lead-free HASL: the same stack-up as the main board (see its gen_pcb.py)
SOLDER_MASK = "Blue"
_stack = "".join([
    "\t\t(stackup\n",
    '\t\t\t(layer "F.SilkS" (type "Top Silk Screen") (color "White"))\n',
    '\t\t\t(layer "F.Paste" (type "Top Solder Paste"))\n',
    f'\t\t\t(layer "F.Mask" (type "Top Solder Mask") (color "{SOLDER_MASK}") (thickness 0.01))\n',
    '\t\t\t(layer "F.Cu" (type "copper") (thickness 0.035))\n',
    '\t\t\t(layer "dielectric 1" (type "core") (thickness 1.51) (material "FR4") (epsilon_r 4.5) (loss_tangent 0.02))\n',
    '\t\t\t(layer "B.Cu" (type "copper") (thickness 0.035))\n',
    f'\t\t\t(layer "B.Mask" (type "Bottom Solder Mask") (color "{SOLDER_MASK}") (thickness 0.01))\n',
    '\t\t\t(layer "B.Paste" (type "Bottom Solder Paste"))\n',
    '\t\t\t(layer "B.SilkS" (type "Bottom Silk Screen") (color "White"))\n',
    '\t\t\t(copper_finish "HAL lead-free")\n',
    "\t\t\t(dielectric_constraints no)\n",
    "\t\t)\n"])
_text = open(OUT).read()
if "(stackup" not in _text:
    _i = _text.index("\t(setup\n") + len("\t(setup\n")
    open(OUT, "w").write(_text[:_i] + _stack + _text[_i:])

# every footprint comes fresh from KiCad's library, so "doesn't match the library" only flags the trimmed holes
pro = os.path.splitext(OUT)[0] + ".kicad_pro"
cfg = json.load(open(pro)) if os.path.exists(pro) else {"meta": {"filename": os.path.basename(pro), "version": 3}}
cfg.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rule_severities", {})[
    "lib_footprint_mismatch"] = "ignore"
json.dump(cfg, open(pro, "w"), indent=2)
print("placed", len(PARTS), "footprints on", OUT)

"""Places the ADS1115 adapter board (KiCad's Python):  gen_pcb.py out/ads1115-adapter.kicad_pcb
Routing, ground fill and checks are done by build.sh (it reuses the breakout board's route.py)."""
import json
import os
import sys

import pcbnew

from adapter import (PARTS, REV, W, H, CX, ROW_A, ROW_P, ROW_S, HOLES, PIN1, BACK,
                     LABELS_A, LABELS_P, LABELS_S, LOGO_CENTRE, LOGO_WIDTH)

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

for ref, (lib_id, value, fpid, pins, desc) in PARTS.items():
    lib, name = fpid.split(":")
    fp = pcbnew.FootprintLoad(f"{FPDIR}/{lib}.pretty", name)
    fp.SetFPIDAsString(fpid)
    fp.SetReference(ref); fp.SetValue(value); fp.SetField("Description", desc)
    fp.SetPath(pcbnew.KIID_PATH("/" + link[ref]))
    board.Add(fp)
    if ref.startswith("H"):
        x, y = HOLES[int(ref[1]) - 1]
        fp.SetPosition(V(x, y))
        # 3.81 mm from the headers' end pins, exactly as on the ADS1115 module: drop the screw-head courtyard,
        # which overlaps the headers' by design (the "doesn't match library" check is off for this project)
        for g in list(fp.GraphicalItems()):
            if g.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
                fp.Remove(g)
    else:
        if ref in BACK:
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        # pick the rotation that runs pin 1 -> pin N left to right, then put pin 1 where it belongs
        for rot in (90, 270, 0, 180):
            fp.SetOrientationDegrees(rot)
            p = {pd.GetNumber(): pd.GetPosition() for pd in fp.Pads()}
            if p["2"].x > p["1"].x and p["2"].y == p["1"].y:
                break
        p1 = [pd for pd in fp.Pads() if pd.GetNumber() == "1"][0].GetPosition()
        tx, ty = PIN1[ref]
        fp.Move(V(tx, ty) - p1)
    for pd in fp.Pads():
        net = pins.get(int(pd.GetNumber())) if pd.GetNumber().isdigit() else None
        if net:
            pd.SetNet(nets[net])
        elif pd.GetNumber():
            nc_net = pcbnew.NETINFO_ITEM(board, f"unconnected-({ref}-Pin_{pd.GetNumber()}-Pad{pd.GetNumber()})")
            board.Add(nc_net); pd.SetNet(nc_net)
    fp.Reference().SetVisible(False)
    fp.Value().SetVisible(False)

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


# top: the 10-pin socket's names (between the socket and the analog row), title below the socket
x0, _ = PIN1["J3"]
for i, lab in enumerate(LABELS_S):
    silk(lab, x0 + i * 2.54, ROW_S - 1.9, 0.8, angle=90, align="left")
silk("ADS1115 ADAPTER", CX, ROW_S + 2.6, 0.9, bold=True)
silk(f"10-pin board -> 2-row socket  rev {REV}", CX, ROW_S + 3.9, 0.8)
# bottom: the two rows' names, as on the breakout board, between the rows (mirrored: read from underneath)
for row, labs, dy, al in ((ROW_A, LABELS_A, 2.1, "left"), (ROW_P, LABELS_P, -2.1, "right")):   # mirrored: ends swap
    for i, lab in enumerate(labs):
        silk(lab, CX - 6.35 + i * 2.54, row + dy, 0.8, angle=90, align=al, layer=pcbnew.B_SilkS)
for row, name in ((ROW_A, "J15"), (ROW_P, "J10")):            # which breakout board socket each row goes into
    silk(name, 1.8, row, 0.8, angle=90, layer=pcbnew.B_SilkS, bold=True)



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
add_logo(LOGO, LOGO_CENTRE, LOGO_WIDTH, layer=pcbnew.F_SilkS, mirror=False)   # top: beside the module, stays visible
add_logo(LOGO, LOGO_CENTRE, LOGO_WIDTH)                                       # and underneath
pcbnew.SaveBoard(OUT, board)

# every footprint comes fresh from KiCad's library, so "doesn't match the library" only flags the trimmed holes
pro = os.path.splitext(OUT)[0] + ".kicad_pro"
cfg = json.load(open(pro)) if os.path.exists(pro) else {"meta": {"filename": os.path.basename(pro), "version": 3}}
cfg.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rule_severities", {})[
    "lib_footprint_mismatch"] = "ignore"
json.dump(cfg, open(pro, "w"), indent=2)
print("placed", len(PARTS), "footprints on", OUT)

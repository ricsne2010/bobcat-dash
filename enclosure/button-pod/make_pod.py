"""Bobcat dash button pod: 3D model (CadQuery) -> STEP + STL for fabrication, and preview pictures.

    pip install cadquery matplotlib
    python3 make_pod.py            (writes the files next to this script)

Three parts, 5052 aluminium (or stainless), powder-coated:
  cover  2 mm sheet: a wedge with the button face tilted TILT degrees up from the base, open at the
         bottom with an inward flange (4 screws to the base). 5 holes for Eaton M22 buttons, labels
         engraved 0.4 mm deep: ALARM SILENCE (red mushroom) on top, OK / BACK, then the arrows.
  base   3 mm plate, square to the electrical box, bolted to the FRONT end of the box top. The cover sits
         on it turned ROTATE degrees toward the operator. Grommet hole for the cable into the box.
  arm    3 mm bent L-bracket under the overhang into the cab, down the box's seat-side panel (no welding).
  gusset 3 mm bent triangle with two tabs, clamped to the arm by the arm's own 4 bolts (no welding).

Machine coordinates (mm): X toward the rear of the machine (X = 0 at the box's front end), Y toward the
machine's right side, away from the cab (Y = 0 at the top edge of the box's seat-side panel; the box top runs
Y = 0..55; the cab, and the overhang, are at Y < 0), Z up from the box top.
Everything is a parameter below; check the Eaton M22 numbers against Eaton's sheet before ordering.
"""
import math
import os

import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- parameters
TILT = 37.5          # face angle up from the base (deg)
ROTATE = 0.0         # face turned from "straight to the rear" toward the cab / operator (deg)
T = 2.0              # cover sheet thickness (Eaton M22 clamps 1-6 mm panels)
TB = 3.0             # base plate thickness
AT = 3.0             # support arm + gusset thickness: 3 mm aluminium / steel; ~5-6 mm if 3D printed (ASA or PA12)
W = 112.0            # cover width (outside)
LF = 172.0           # face length along the slope
ROWS = {"arrows": 32.0, "okback": 84.0, "silence": 138.0}    # distance up the face from its low edge
PITCH = 46.0         # side-by-side button spacing (Eaton min 30)
HOLE = 22.5          # Eaton M22: 22.3 mm +0.4
BODY = 50.0          # button head + M22-A adapter + M22-K10 behind the panel, with wire room (check!)
HALF_BODY = 15.0
FLANGE = 12.0        # cover's inward bottom flange
ENGRAVE = 0.4
BOX_TOP_DEPTH = 55.0     # electrical box top, seat-side panel to back (outside)
PANEL_LEAN = 15.0 / 212  # the seat-side panel leans out 15 mm over its 212 mm height
# Raspberry Pi 5 inside, at the lower front end of the cover (behind the button bodies)
PI_L, PI_W = 85.0, 56.0          # board
PI_HOLES = [(3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5)]   # (along 85, along 56); HDMI / USB-C edge is y = 0
FAN = 40.0                       # exhaust fan on the back wall (40 mm, holes 32 mm apart, M3)
GLAND = 20.5                     # M20 cable gland for the HDMI cable, low on the back wall
OPENING = (60.0, 20.0)           # pass-through into the box (X by Y, machine): ribbon, buttons cable, Pi power
# The Pi lies flat, right way up, its 40-pin header along the box and lined up with the breakout board's J1 below.
# The ribbon leaves its plug upward, folds flat over the Pi's header edge and drops straight through the
# pass-through beside it to J1: folds across its width only, never a twist.
J1_X = 89.1                      # breakout board J1 centre along the box (machine X), board centred left-right
PI_EDGE_Y = 20.0                 # the Pi's header edge (machine Y); the pass-through starts just beyond it
PI_STANDOFF = 6.0
PI_LIP_EXTRA = 0.0               # extra front-lip height, if the Pi or its ribbon fold ever needs more room
FACE_CLEAR = 68.0                # the Pi stays this far (cover x) from the face's low edge: clear of the button bodies
EXTRA_DEPTH = 5.0                # deeper cover: keeps the Pi's standoffs off the cover's flange
FONT = None          # a .ttf for the engraving; None = pygame's FreeSans if installed, else CadQuery's default
for cand in [os.path.join(os.path.dirname(cq.__file__), "..", "pygame", "freesansbold.ttf")]:
    if os.path.exists(cand):
        FONT = os.path.abspath(cand)

t = math.radians(TILT)
UP = (math.cos(t), math.sin(t))          # up the face, in the cover's (x, z) profile
IN = (math.sin(t), -math.cos(t))         # into the cover, perpendicular to the face


def needed_lip_and_depth():
    """Front lip height and depth so every button body clears the base and the back wall."""
    pts = [(s * UP[0] + a * UP[0] + BODY * IN[0], s * UP[1] + a * UP[1] + BODY * IN[1])
           for s in ROWS.values() for a in (-HALF_BODY, HALF_BODY)]
    lip = max(20.0, 6.0 + T - min(z for _, z in pts)) + PI_LIP_EXTRA
    depth = max(max(x for x, _ in pts) + 6.0 + T, LF * UP[0] + 8.0) + EXTRA_DEPTH
    return lip, depth


HF, D = needed_lip_and_depth()
TOP_Z = HF + LF * UP[1]


# ---------------------------------------------------------------- cover (built in its own frame)
# cover frame: x from the face's low edge (operator side) toward the back, y across 0..W, z up from the base
def cover():
    prof = [(0, 0), (0, HF), (LF * UP[0], TOP_Z), (D, TOP_Z), (D, 0)]
    solid = cq.Workplane("XZ").polyline(prof).close().extrude(-W)            # XZ extrudes along -y
    shell = solid.faces("<Z").shell(-T)                                         # open bottom, walls T thick
    ring = (cq.Workplane("XY").rect(D, W, centered=False).extrude(T)
            .cut(cq.Workplane("XY").center(FLANGE, FLANGE).rect(D - 2 * FLANGE, W - 2 * FLANGE, centered=False)
                 .extrude(T)))
    body = shell.union(ring)
    for (x, y) in flange_holes():
        body = body.cut(cq.Workplane("XY").center(x, y).circle(2.25).extrude(T))   # M4 clearance

    # the face as a workplane: origin at the low edge's centre, x = to the viewer's right, y = up the face
    n = (-math.sin(t), 0, math.cos(t))
    face = cq.Plane(origin=(0, W / 2, HF), xDir=(0, -1, 0), normal=n)
    wp = lambda: cq.Workplane(face)
    holes = [(-PITCH / 2, ROWS["arrows"]), (PITCH / 2, ROWS["arrows"]), (-PITCH / 2, ROWS["okback"]),
             (PITCH / 2, ROWS["okback"]), (0, ROWS["silence"])]
    for (lx, ly) in holes:
        body = body.cut(wp().center(lx, ly).circle(HOLE / 2).extrude(-(T + 1)))
    # engraving: arrows as shapes, words as text, under each button (silence label above the mushroom)
    ay = ROWS["arrows"] - 22
    for sign in (-1, 1):
        cx = sign * PITCH / 2
        tri = [(cx + sign * 7, ay), (cx - sign * 5, ay + 6), (cx - sign * 5, ay - 6)]
        body = body.cut(wp().polyline(tri).close().extrude(-ENGRAVE))
    labels = [("OK", -PITCH / 2, ROWS["okback"] - 22, 8), ("BACK", PITCH / 2, ROWS["okback"] - 22, 8),
              ("ALARM SILENCE", 0, ROWS["silence"] + 27, 7)]
    for text, lx, ly, size in labels:
        kw = {"fontPath": FONT} if FONT else {}
        body = body.cut(wp().center(lx, ly).text(text, size, -ENGRAVE, combine=False, halign="center",
                                                    valign="center", **kw))
    # back wall (cover x = D): exhaust fan high, HDMI gland low behind the Pi's HDMI ports
    back = cq.Plane(origin=(D, W / 2, 0), xDir=(0, 1, 0), normal=(1, 0, 0))
    fz = TOP_Z - T - FAN / 2 - 6
    body = body.cut(cq.Workplane(back).center(0, fz).circle(FAN / 2 - 1).extrude(-(T + 1)))
    for dx in (-16, 16):
        for dz in (-16, 16):
            body = body.cut(cq.Workplane(back).center(dx, fz + dz).circle(1.7).extrude(-(T + 1)))
    gy, gz = PI_GLAND_Y - W / 2, FLANGE + GLAND / 2 + 8
    body = body.cut(cq.Workplane(back).center(gy, gz).circle(GLAND / 2).extrude(-(T + 1)))
    # intake: slots low on the cab-side wall (cover y = W), under the Pi, for a foam filter pad inside
    side = cq.Plane(origin=(0, W, 0), xDir=(-1, 0, 0), normal=(0, 1, 0))     # local y = up
    for i in range(5):
        body = body.cut(cq.Workplane(side).center(-(PI_X0 + 6 + i * 10), FLANGE + 16).slot2D(30, 4, angle=90)
                        .extrude(-(T + 1)))
    return body


def pi_holes():
    """The Pi's 4 mounting holes, MACHINE coordinates. Right way up, header edge (v = 56) toward the box's back
    wall, long side along the box (u toward the rear of the machine)."""
    return [(PI_XL + u, PI_EDGE_Y - PI_W + v) for u, v in PI_HOLES]


def pi_outline():
    """The Pi board's corners, machine coordinates."""
    y0 = PI_EDGE_Y - PI_W
    return [(PI_XL, y0), (PI_XL + PI_L, y0), (PI_XL + PI_L, PI_EDGE_Y), (PI_XL, PI_EDGE_Y)]


def flange_holes():
    m = T + (FLANGE - T) / 2
    return [(m + 4, m), (m + 4, W - m), (D - m, m), (D - m, W - m)]


# ---------------------------------------------------------------- placing the cover on the machine
ANG = 180.0 - ROTATE        # cover +x (into the cover) points forward (the face looks back, turned toward the cab)


def to_machine(x, y):
    a = math.radians(ANG)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


corners = [to_machine(x, y) for x, y in [(0, 0), (0, W), (D, 0), (D, W)]]
PI_XL = J1_X - 32.5              # the Pi's left end (machine X): its header's centre is 32.5 mm from it
OFF_X = PI_XL + PI_L + FACE_CLEAR                            # cover placed so the Pi sits clear of the button bodies
SIDE_GAP = 0.0       # cover's outer wall to the box's back (outer) wall: 0 = flush with it
OFF_Y = (BOX_TOP_DEPTH - SIDE_GAP) - max(c[1] for c in corners)


def M(x, y):
    mx, my = to_machine(x, y)
    return mx + OFF_X, my + OFF_Y


FOOT = [M(x, y) for x, y in [(0, 0), (D, 0), (D, W), (0, W)]]
PI_X0 = OFF_X - (PI_XL + PI_L)   # cover x where the Pi starts (for the intake slots under it)
PI_GLAND_Y = OFF_Y - (PI_EDGE_Y - PI_W) - 8.0          # HDMI gland behind the Pi's HDMI edge (cab side)
# the plate reaches past both ends of the cover, for bolts you can get at with the cover on
BX0, BX1 = max(2.0, min(p[0] for p in FOOT) - 26), min(218.0, max(p[0] for p in FOOT) + 26)
BY0, BY1 = min(p[1] for p in FOOT), BOX_TOP_DEPTH   # flush with the cover on the cab side and the box's back wall


def inside(pt, poly):
    x, y = pt
    s = 0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        s += (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1) > 0
    return s in (0, len(poly))


def base():
    plate = cq.Workplane("XY").center(BX0, BY0).rect(BX1 - BX0, BY1 - BY0, centered=False).extrude(TB)
    for (x, y) in flange_holes():                               # cover screws: M4 (tap, or PEM nuts)
        mx, my = M(x, y)
        plate = plate.cut(cq.Workplane("XY").center(mx, my).circle(1.65).extrude(TB))   # 3.3 mm = M4 tap drill
    for (x, y) in BOLTS:                                        # to the box top: M5
        plate = plate.cut(cq.Workplane("XY").center(x, y).circle(2.75).extrude(TB))
    cx, cy = CABLE
    plate = plate.cut(cq.Workplane("XY").center(cx, cy).rect(*OPENING).extrude(TB))   # pass-through to the box
    for (mx, my) in pi_holes():                                 # Pi standoffs: tapped M2.5 (flat underneath)
        plate = plate.cut(cq.Workplane("XY").center(mx, my).circle(1.025).extrude(TB))   # 2.05 mm = M2.5 tap drill
    for (x, y) in ARM_BOLTS:
        plate = plate.cut(cq.Workplane("XY").center(x, y).circle(2.75).extrude(TB))
    return plate


# box-top bolts and the cable hole
CABLE_R = 8.0            # (kept for the README text)


def to_cover(X, Y):
    a = math.radians(ANG)
    x, y = X - OFF_X, Y - OFF_Y
    return x * math.cos(-a) - y * math.sin(-a), x * math.sin(-a) + y * math.cos(-a)


def pick_points():
    """Opening: under the cover, between its front flange and the Pi, over the box top (6 mm from its edges).
    Box bolts: over the box top but beside the cover (reachable with it on), spread out."""
    ox, oy = OPENING
    cable = (J1_X, PI_EDGE_Y + 1.0 + oy / 2)        # just beyond the Pi's header edge, in line with J1
    cs = [to_cover(cable[0] + sx * ox / 2, cable[1] + sy * oy / 2) for sx in (-1, 1) for sy in (-1, 1)]
    if not all(FLANGE + 1 <= x <= D - FLANGE - 1 and FLANGE + 1 <= y <= W - FLANGE - 1 for x, y in cs):
        raise SystemExit("pass-through would cut into the cover's flange: check J1_X / PI_HEADER_Y")
    if not (6 <= cable[1] - oy / 2 and cable[1] + oy / 2 <= BOX_TOP_DEPTH - 6):
        raise SystemExit("pass-through too close to the box top's edges")
    for hx, hy in pi_holes():                       # round 4.5 mm standoffs: clear of the opening and the flange
        dx = max(abs(hx - cable[0]) - ox / 2, 0); dy = max(abs(hy - cable[1]) - oy / 2, 0)
        if math.hypot(dx, dy) < 2.25:
            raise SystemExit("a Pi standoff would stand in the pass-through")
        x, y = to_cover(hx, hy)
        if not (FLANGE + 2.25 <= x <= D - FLANGE - 2.25 and FLANGE + 2.25 <= y <= W - FLANGE - 2.25):
            raise SystemExit(f"a Pi standoff would sit on the cover's flange (cover x {x:.1f}, y {y:.1f})")

    def clear(X, Y):
        x, y = to_cover(X, Y)
        return not (-8 <= x <= D + 8 and -8 <= y <= W + 8)
    ys = (BOX_TOP_DEPTH - 14, 12)
    xs_ok = [X for X in range(int(BX0) + 8, int(BX1) - 8) if all(clear(X, Y) for Y in ys)]
    front = [X for X in xs_ok if X < min(p[0] for p in FOOT)]
    rear = [X for X in xs_ok if X > max(p[0] for p in FOOT)]
    if not front:
        raise SystemExit("no room in front of the cover for the box bolts")
    x1 = min(front)
    # rear pair: beside the cover if it fits, otherwise just inside it (reached with the cover off: 4 screws)
    x2 = max(rear) if rear else max(p[0] for p in FOOT) - FLANGE - 8
    return [(x1, ys[0]), (x1, ys[1]), (x2, ys[0]), (x2, ys[1])], cable


BOLTS, CABLE = pick_points()

# support arm: an L-bracket with a gusset, under the middle of the overhang, down the seat-side panel
ARM_W, ARM_DROP = 30.0, 72.0
ARM_REACH = min(90.0, -BY0 - 1.0)         # under the overhang (Y < 0), out to the plate's edge
ARM_X0 = (min(p[0] for p in FOOT) + max(p[0] for p in FOOT)) / 2 - ARM_W / 2
ARM_BOLTS = [(ARM_X0 + ARM_W / 2, -15.0), (ARM_X0 + ARM_W / 2, -(ARM_REACH - 12.0))]


def arm():
    """Under the overhang (Y < 0), ONE bent piece, no welding: a top leg bolted under the plate and a leg down the
    seat-side panel (its face is the Y = 0 plane at the top, leaning out toward the cab as it goes down)."""
    lean = -math.degrees(math.atan(PANEL_LEAN))          # rotating about +X by a negative angle leans toward -Y
    top = cq.Workplane("XY").center(ARM_X0, -ARM_REACH).rect(ARM_W, ARM_REACH, centered=False).extrude(-AT)
    for (x, y) in ARM_BOLTS:
        top = top.cut(cq.Workplane("XY").center(x, y).circle(2.75).extrude(-AT))
    leg = cq.Workplane("XY").box(ARM_W, AT, ARM_DROP, centered=False).translate((ARM_X0, -AT, -ARM_DROP))
    for z in ARM_PANEL_Z:
        leg = leg.cut(cq.Workplane("XZ").center(ARM_X0 + ARM_W / 2, z).circle(2.75).extrude(10, both=True))
    leg = leg.rotate((ARM_X0, 0, 0), (ARM_X0 + 1, 0, 0), lean)
    return top.union(leg)


ARM_PANEL_Z = (-22.0, -58.0)      # the 2 screws through the leg into the panel
GUS_X, GUS_TAB = 4.0, 20.0        # gusset plate 4 mm in from the bracket's edge; its tabs fold over 20 mm


def gusset():
    """The triangle: a separate bent piece, bolted on. A tab along its top edge sits under the bracket's top leg,
    a tab along its upright edge sits on the bracket's leg; the bracket's own 4 bolts clamp both tabs."""
    lean = -math.degrees(math.atan(PANEL_LEAN))
    x0 = ARM_X0 + GUS_X
    zb = -(ARM_DROP - 10)
    k = PANEL_LEAN
    # the triangle, in the YZ plane, just inside both tabs
    tri = (cq.Workplane("YZ").polyline([(-2 * AT, -2 * AT), (-(ARM_REACH - 10), -2 * AT),
                                         (-2 * AT + k * zb, zb)]).close().extrude(AT).translate((x0, 0, 0)))
    # top tab: under the top leg, folded over toward +X
    ttab = (cq.Workplane("XY").center(x0, -(ARM_REACH - 10)).rect(GUS_TAB, ARM_REACH - 10 - AT - 1.5, centered=False)
            .extrude(-AT).translate((0, 0, -AT)))
    for (x, y) in ARM_BOLTS:
        ttab = ttab.cut(cq.Workplane("XY").center(x, y).circle(2.75).extrude(-2 * AT - 1))
    # upright tab: against the leg's cab-side face, leaning with it
    utab = (cq.Workplane("XY").box(GUS_TAB, AT, ARM_DROP - 10 - AT - 1.5, centered=False)
            .translate((x0, -2 * AT, -(ARM_DROP - 10))))
    for z in ARM_PANEL_Z:
        utab = utab.cut(cq.Workplane("XZ").center(ARM_X0 + ARM_W / 2, z).circle(2.75).extrude(10, both=True))
    utab = utab.rotate((ARM_X0, 0, 0), (ARM_X0 + 1, 0, 0), lean)
    return tri.union(ttab).union(utab)


def placed_cover():
    c = cover()
    c = c.rotate((0, 0, 0), (0, 0, 1), ANG).translate((OFF_X, OFF_Y, TB))
    return c


def main():
    parts = {"cover": placed_cover(), "base": base(), "arm": arm(), "gusset": gusset()}
    assy = cq.Assembly()
    colors = {"cover": cq.Color(0.25, 0.27, 0.3), "base": cq.Color(0.6, 0.62, 0.65), "arm": cq.Color(0.6, 0.62, 0.65),
              "gusset": cq.Color(0.7, 0.55, 0.3)}
    for name, p in parts.items():
        cq.exporters.export(p, os.path.join(HERE, f"pod-{name}.step"))
        cq.exporters.export(p, os.path.join(HERE, f"pod-{name}.stl"), tolerance=0.05, angularTolerance=0.1)
        assy.add(p, name=name, color=colors[name])
    assy.save(os.path.join(HERE, "pod-assembly.step"))
    # the cover flat on the bench, for the fabricator (its own frame)
    cq.exporters.export(cover(), os.path.join(HERE, "pod-cover-own-frame.step"))
    fx = [p[0] for p in FOOT]
    fy = [p[1] for p in FOOT]
    print(f"cover: {W:.0f} wide x {D:.0f} deep x {TOP_Z + T:.0f} tall, face {TILT} deg, turned {ROTATE} deg")
    print(f"front lip {HF:.0f} mm; footprint X {min(fx):.0f}..{max(fx):.0f}, Y {min(fy):.0f}..{max(fy):.0f}"
          f" -> overhang into the cab {-min(fy):.0f} mm")
    print(f"base plate {BX1 - BX0:.0f} x {BY1 - BY0:.0f} mm; box bolts {[tuple(round(v) for v in b) for b in BOLTS]};"
          f" opening {OPENING[0]:.0f} x {OPENING[1]:.0f} at {tuple(round(v) for v in CABLE)}")
    pio = pi_outline()
    print(f"Pi (right way up, {PI_STANDOFF:.0f} mm standoffs): machine X {min(p[0] for p in pio):.0f}..{max(p[0] for p in pio):.0f},"
          f" Y {min(p[1] for p in pio):.0f}..{max(p[1] for p in pio):.0f}; header over J1 at X {J1_X}; standoff holes "
          f"{[tuple(round(v) for v in h) for h in pi_holes()]}")


if __name__ == "__main__":
    main()

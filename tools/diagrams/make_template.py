"""Printable 1:1 drilling template for the breakout board (rev 3.0, 162 x 159 mm).

    pip install reportlab
    python3 make_template.py        -> ../../breakout-board/docs/mounting-template.pdf

The page is exactly US Letter and everything is drawn in real millimetres. The PDF asks print dialogs to default
to "Actual size" (/PrintScaling /None), but a dialog can still be overridden, so the page carries check rulers:
measure them before you drill. Geometry comes from the generator (gen_pcb.py): update it here if the board changes.
"""
import os

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch, mm
from reportlab.pdfgen import canvas

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "breakout-board", "docs",
                   "mounting-template.pdf")

BOARD_W, BOARD_H, CORNER = 162.0, 159.0, 3.0
HOLES = [("H1", 4.5, 4.5), ("H2", 157.5, 4.5), ("H3", 4.5, 142.0), ("H4", 157.5, 142.0),   # board mm, y down
         # rev 2.8: mid-side holes and one near the centre, against vibration
         ("H15", 94.0, 4.5), ("H16", 72.2, 142.0), ("H17", 4.5, 87.0), ("H18", 157.5, 58.5), ("H19", 70.0, 81.0)]
HOLE_D = 3.2
# Connector footprints (board mm, x0, y0, x1, y1), for planning where the wires come and go.
_Z = [   # rev 2.7 coordinates; rev 2.8 added a 25 mm strip on top, so they shift down 25 mm below
    ("TO PI (ribbon)", 30.4, -23.8, 89.9, -13.8), ("TILT", 151.0, 9.4, 157.8, 26.2),
    ("COIL", 0.0, 42.4, 13.1, 55.7), ("TEMP\nPROBE", 151.0, 41.1, 157.8, 54.9), ("AUX", 151.0, 93.4, 160.8, 107.6),
    ("POWER", 3.9, 120.9, 22.3, 134.0), ("5V", 22.9, 120.9, 36.2, 134.0), ("HORN", 36.9, 120.9, 50.2, 134.0),
    ("TACH", 50.9, 120.9, 69.3, 134.0), ("SWITCHES", 75.0, 120.9, 98.4, 134.0), ("FUEL", 98.9, 120.9, 112.2, 134.0),
    ("SILENCE", 112.9, 120.9, 126.2, 134.0), ("LIGHTS", 126.9, 120.9, 145.3, 134.0),
    ("MONO AMP", 6.0, 7.0, 26.0, 26.8), ("STEREO AMP", 29.3, 9.5, 54.7, 28.5), ("ADC", 110.3, 10.8, 135.7, 28.5),
]
ZONES = [(n, a, b + 25.0, c, d + 25.0) for n, a, b, c, d in _Z]

PAGE_W, PAGE_H = letter
OX = (PAGE_W / mm - BOARD_W) / 2          # board's top-left corner on the page, mm
OY_TOP = 33.0                             # mm down from the top of the page


def P(x, y):
    """Board mm (y down) -> PDF points (y up)."""
    return (OX + x) * mm, PAGE_H - (OY_TOP + y) * mm


def ruler_mm(c, x, y, length=100):
    c.setLineWidth(0.3)
    c.line(x * mm, y * mm, (x + length) * mm, y * mm)
    for i in range(length + 1):
        h = 4 if i % 10 == 0 else 2.5 if i % 5 == 0 else 1.5
        c.line((x + i) * mm, y * mm, (x + i) * mm, (y + h) * mm)
        if i % 10 == 0:
            c.setFont("Helvetica", 6)
            c.drawCentredString((x + i) * mm, (y + 5) * mm, str(i // 10))
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(x * mm, (y - 4) * mm, f"{length} mm (10 cm): must measure exactly {length} mm")


def ruler_in(c, x, y, inches=6):
    c.setLineWidth(0.3)
    c.line(x * mm, y * mm, x * mm + inches * inch, y * mm)
    for i in range(inches * 8 + 1):
        h = 4 if i % 8 == 0 else 3 if i % 4 == 0 else 2 if i % 2 == 0 else 1.3
        px = x * mm + i * inch / 8
        c.line(px, y * mm, px, (y + h) * mm)
        if i % 8 == 0:
            c.setFont("Helvetica", 6)
            c.drawCentredString(px, (y + 5) * mm, str(i // 8))
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(x * mm, (y - 4) * mm, f"{inches} inches: must measure exactly {inches} in")


def dim(c, x0, y0, x1, y1, text, off):
    """Dimension line between two board points, offset sideways by `off` mm."""
    c.setLineWidth(0.25)
    c.setStrokeGray(0.25)
    if y0 == y1:   # horizontal
        a, b = P(x0, y0 + off), P(x1, y1 + off)
        c.line(*P(x0, y0), *a)
        c.line(*P(x1, y1), *b)
        c.line(*a, *b)
        for p, d in ((a, 1), (b, -1)):
            c.line(p[0], p[1], p[0] + d * 1.5 * mm, p[1] + 0.7 * mm)
            c.line(p[0], p[1], p[0] + d * 1.5 * mm, p[1] - 0.7 * mm)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString((a[0] + b[0]) / 2, a[1] + 1.2 * mm, text)
    else:          # vertical
        a, b = P(x0 + off, y0), P(x1 + off, y1)
        c.line(*P(x0, y0), *a)
        c.line(*P(x1, y1), *b)
        c.line(*a, *b)
        for p, d in ((a, -1), (b, 1)):
            c.line(p[0], p[1], p[0] + 0.7 * mm, p[1] + d * 1.5 * mm)
            c.line(p[0], p[1], p[0] - 0.7 * mm, p[1] + d * 1.5 * mm)
        c.saveState()
        c.translate(a[0] + 1.2 * mm if off > 0 else a[0] - 1.2 * mm, (a[1] + b[1]) / 2)
        c.rotate(90 if off < 0 else -90)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(0, 0, text)
        c.restoreState()
    c.setStrokeGray(0)


def main():
    c = canvas.Canvas(OUT, pagesize=letter, pageCompression=1)
    c.setTitle("Bobcat dash breakout board - drilling template (1:1)")
    c.setAuthor("bobcat-dash")
    c.setViewerPreference("PrintScaling", "None")      # print dialogs default to Actual size / 100 %

    # Heading
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 11 * mm, "BREAKOUT BOARD DRILLING TEMPLATE  -  FULL SIZE 1:1")
    c.setFont("Helvetica", 8.5)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 15.5 * mm,
                        "Print on US Letter at \"Actual size\" / 100 %  (NOT \"Fit\", \"Shrink oversized pages\" or "
                        "\"Scale to fit\").  Check both rulers before drilling.")
    c.drawCentredString(PAGE_W / 2, PAGE_H - 19 * mm,
                        "Board rev 3.0, 162 x 159 mm (6.378 x 6.260 in).  Viewed from the FRONT (parts side): tape it to "
                        "the box's back wall as you'll see the board.")

    # TOP marker
    c.setFont("Helvetica-Bold", 10)
    tx, ty = P(BOARD_W / 2, 0)
    c.drawCentredString(tx, ty + 8.5 * mm, "TOP OF BOX  (narrow end)   -   top edge about 10 mm below the inside top wall")
    c.setLineWidth(0.8)
    c.line(tx, ty + 3 * mm, tx, ty + 7.5 * mm)
    c.line(tx, ty + 7.5 * mm, tx - 1.5 * mm, ty + 5.5 * mm)
    c.line(tx, ty + 7.5 * mm, tx + 1.5 * mm, ty + 5.5 * mm)

    # Board outline (rounded corners)
    x0, y1 = P(0, 0)
    x1, y0 = P(BOARD_W, BOARD_H)
    c.setLineWidth(0.6)
    c.roundRect(x0, y0, x1 - x0, y1 - y0, CORNER * mm, stroke=1, fill=0)

    # Centre lines (to line the board up with the middle of the box)
    c.setDash([6, 2, 1, 2])
    c.setLineWidth(0.25)
    c.setStrokeGray(0.45)
    c.line(*P(BOARD_W / 2, -3), *P(BOARD_W / 2, BOARD_H + 3))
    c.line(*P(-3, BOARD_H / 2), *P(BOARD_W + 3, BOARD_H / 2))
    c.setDash()
    c.setStrokeGray(0)
    c.setFont("Helvetica", 6)
    c.setFillGray(0.4)
    c.drawString(*(v + 0.8 * mm for v in P(BOARD_W / 2, BOARD_H / 2 - 1.2)), "board centre")
    c.setFillGray(0)

    # Connector zones (where wires plug in: leave room for plugs + wire bend)
    for name, a, b, cc, d in ZONES:
        p0, p1 = P(a, d), P(cc, b)
        c.setFillGray(0.92)
        c.setStrokeGray(0.6)
        c.setLineWidth(0.3)
        c.rect(p0[0], p0[1], p1[0] - p0[0], p1[1] - p0[1], stroke=1, fill=1)
        c.setFillGray(0.3)
        lines = name.split("\n")
        fs = 5.5
        c.setFont("Helvetica", fs)
        cx, cy = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
        for i, ln in enumerate(lines):
            c.drawCentredString(cx, cy - (i - (len(lines) - 1) / 2) * fs * 1.1 - fs * 0.35, ln)
    c.setFillGray(0)
    c.setStrokeGray(0)
    c.setFont("Helvetica-Oblique", 7)
    c.setFillGray(0.3)
    lx, ly = P(BOARD_W / 2, BOARD_H - 27)
    c.drawCentredString(lx, ly, "Harness plugs (Phoenix MSTB) all along this edge: wires leave DOWNWARD, toward the "
                                "deep end of the box.")
    c.drawCentredString(lx, ly - 3.5 * mm, "Top edge ~10 mm below the inside top wall leaves ~40 mm (1-1/2\") below "
                                           "the board for plugs, wire bends and tie-downs.")
    c.setFillGray(0)

    # Mounting holes: crosshair, 3.2 mm circle, centre dot, label
    for ref, hx, hy in HOLES:
        x, y = P(hx, hy)
        c.setLineWidth(0.25)
        c.line(x - 6 * mm, y, x + 6 * mm, y)
        c.line(x, y - 6 * mm, x, y + 6 * mm)
        c.setLineWidth(0.4)
        c.circle(x, y, HOLE_D / 2 * mm, stroke=1, fill=0)
        c.circle(x, y, 3.0 * mm, stroke=1, fill=0)            # ~6 mm: standoff footprint
        c.circle(x, y, 0.35 * mm, stroke=0, fill=1)           # centre-punch here
        c.setFont("Helvetica-Bold", 7)
        dx = 4 * mm if hx < BOARD_W / 2 else -4 * mm
        if ref == "H19":
            c.drawString(x + 4 * mm, y - 1 * mm, "H19 (near centre)")
        elif ref in ("H17", "H18"):
            c.drawCentredString(x + dx * 1.8, y - 1 * mm, ref)
        else:
            c.drawCentredString(x + dx * 1.6, y + (3.8 * mm if hy < 50 else -5.5 * mm), ref)

    # Dimensions
    dim(c, 4.5, 142, 157.5, 142, "153.0 mm  (6.024\")  hole centre to hole centre", 23)
    dim(c, 157.5, 4.5, 157.5, 142, "137.5 mm  (5.413\")  hole centres", 12)
    dim(c, 0, 0, 0, BOARD_H, "159.0 mm  (6.260\")  board height", -11)

    c.setFont("Helvetica", 7)
    c.setFillGray(0.25)
    hx, hy = P(4.5, 95)
    c.drawString(hx + 5 * mm, hy - 7.5 * mm, "9 holes, all M3: 4 corners, 4 near the middle of each side, 1 near the centre.")
    c.drawString(hx + 5 * mm, hy - 10.5 * mm, "Edge holes 4.5 mm in from the top/side edges; bottom row 17 mm up from the bottom edge.")
    c.setFillGray(0)

    # Check rulers + notes, below the board
    base = (PAGE_H / mm) - OY_TOP - BOARD_H - 22
    ruler_mm(c, 15, base)
    ruler_in(c, 15, base - 15)

    notes = [
        "Before drilling:  1) Both rulers must measure exactly.  Also check 153.0 mm between the H1 and H2 hole centres.  "
        "If anything is off, reprint at Actual size.",
        "2) Tape the sheet flat on the box's back wall, TOP toward the narrow end, centred left-right, its top edge "
        "~10 mm below the inside top wall.",
        "3) Centre-punch the dot in each hole.  Drill 1/8\" (3.2 mm) for M3 screws through the wall, or 2.5 mm to tap M3 "
        "into thick metal.",
        "4) Mount on 9 M3 standoffs (10 mm or taller, all the same height): the board's back must not touch the box.  "
        "Outer circle = ~6 mm standoff.",
        "Grey zones: plugs and modules.  The Pi ribbon plugs in on the top edge and goes straight up to the lid; COIL "
        "(high voltage) left, TILT and TEMP PROBE right.",
    ]
    c.setFont("Helvetica", 7.2)
    for i, t in enumerate(notes):
        c.drawString(12 * mm, (base - 26 - i * 4.0) * mm, t)

    c.setFont("Helvetica", 6)
    c.setFillGray(0.45)
    c.drawRightString(PAGE_W - 10 * mm, 8 * mm, "github.com/ricsne2010/bobcat-dash  -  breakout-board/docs/"
                                                "mounting-template.pdf")
    c.showPage()
    c.save()
    print("wrote", os.path.normpath(OUT))


if __name__ == "__main__":
    main()

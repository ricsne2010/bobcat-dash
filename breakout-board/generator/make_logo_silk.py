#!/usr/bin/env python3
"""Convert the Project Moon Pi logo into 1-bit silkscreen artwork for the board.

  python3 make_logo_silk.py            (needs numpy + Pillow; reads ../../splash/logo-original.png)

Writes logo_silk.png (preview) and logo_silk.json (run-length rows that gen_pcb.py turns into
silkscreen polygons). A board's silkscreen is one colour with no shading, so:
  * rings, lettering, stars, swoosh and lunar horizon are taken from the picture (bright + red parts),
  * the Earth becomes a clean outline with simplified continents and clouds,
  * the lander is redrawn as a silhouette (the photo-style original doesn't survive the conversion),
  * the swoosh, lander and flames get a thin dark gap around them, so they read as "in front",
  * nothing thinner than the board maker's minimum line / gap is left.
"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_FILE = os.path.join(HERE, "..", "..", "splash", "logo-original.png")
OUT_PX = 600                          # stored width; gen_pcb.py scales it to the board size

SRC = np.asarray(Image.open(SRC_FILE).convert("RGB")).astype(float)
R, G, B = SRC[..., 0], SRC[..., 1], SRC[..., 2]
L = 0.299 * R + 0.587 * G + 0.114 * B
MX, MN = SRC.max(-1), SRC.min(-1)
SAT = (MX - MN) / np.maximum(MX, 1)
def disk(r):
    y, x = np.mgrid[-r:r + 1, -r:r + 1]
    return [(dy, dx) for dy, dx in zip(y.ravel(), x.ravel()) if dy * dy + dx * dx <= r * r + r]

def shift_or(m, offs):
    out = np.zeros_like(m); H, W = m.shape
    for dy, dx in offs:
        out[max(dy, 0):H + min(dy, 0), max(dx, 0):W + min(dx, 0)] |= m[max(-dy, 0):H + min(-dy, 0), max(-dx, 0):W + min(-dx, 0)]
    return out

def dilate(m, r): return shift_or(m, disk(r)) if r > 0 else m
def erode(m, r): return ~dilate(~m, r) if r > 0 else m
def opening(m, r): return dilate(erode(m, r), r)     # removes white bits thinner than ~2r
def closing(m, r): return erode(dilate(m, r), r)     # fills black gaps narrower than ~2r

def clean(m, min_line_px, min_gap_px):
    m = opening(m, max(1, min_line_px // 2))
    m = closing(m, max(1, min_gap_px // 2))
    return m

def drop_small(m, min_px):
    """Remove white islands smaller than min_px pixels (4-connected flood fill, run-based)."""
    H, W = m.shape
    seen = np.zeros_like(m)
    out = m.copy()
    ys, xs = np.nonzero(m)
    for y0, x0 in zip(ys, xs):
        if seen[y0, x0]:
            continue
        stack = [(y0, x0)]; seen[y0, x0] = True; comp = []
        while stack:
            y, x = stack.pop(); comp.append((y, x))
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < H and 0 <= nx < W and m[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True; stack.append((ny, nx))
        if len(comp) < min_px:
            for y, x in comp:
                out[y, x] = False
    return out


H, W = L.shape
yy, xx = np.mgrid[0:H, 0:W]
LINE, GAP = 6, 6                       # px at source scale (~34.6 px/mm at 26 mm): ~0.18 mm
ECX, ECY, ER = 519, 485, 225           # Earth circle (fitted)
MOON_Y = 700                           # lunar horizon is below this

red = clean((R > 140) & (G < 100) & (B < 100) & (R > 1.8 * G), LINE, GAP)
light = (L > 150) & (SAT < 0.35)

# --- Earth: outline + simplified continents, only where the moon surface doesn't cover it
earth_disc = (np.hypot(xx - ECX, yy - ECY) <= ER + 6) & (yy < MOON_Y - 10)
ring = (np.abs(np.hypot(xx - ECX, yy - ECY) - ER) <= 3.5) & (yy < MOON_Y - 10)
land = (G > B * 0.85) & (G > R * 0.95) & (L > 60) & (L < 200)
land = opening(land & (np.hypot(xx - ECX, yy - ECY) <= ER - 12), 3)      # drop speckle, keep big shapes
land = closing(land, 4)
clouds = opening((L > 175) & (SAT < 0.3) & (np.hypot(xx - ECX, yy - ECY) <= ER - 12) & (yy < MOON_Y - 10), 3)
earth_detail = land | clouds

# --- lander: redrawn as a clean silhouette (white) with the windows cut out
img = Image.new("L", (W, H), 0); d = ImageDraw.Draw(img)
def leg(pts, w): d.line(pts, fill=255, width=w, joint="curve")
d.rounded_rectangle([470, 499, 565, 516], radius=7, fill=255)                 # top cap
d.ellipse([436, 506, 600, 572], fill=255)                                     # dome/body
d.rectangle([436, 528, 600, 560], fill=255)
d.rectangle([428, 560, 606, 571], fill=255)                                   # lower rim
d.rectangle([488, 571, 548, 604], fill=255)                                   # engine block
d.polygon([(478, 604), (558, 604), (548, 620), (488, 620)], fill=255)         # nozzle skirt
for pts in [[(440, 572), (400, 586), (360, 688)], [(596, 572), (636, 586), (676, 688)],   # outer legs (knee)
            [(462, 574), (424, 662)], [(574, 574), (612, 662)]]:                          # inner legs
    leg(pts, 11)
for x0, y0, x1, y1 in [(338, 682, 382, 698), (404, 656, 444, 670), (592, 656, 632, 670), (654, 682, 698, 698)]:
    d.rounded_rectangle([x0, y0, x1, y1], radius=6, fill=255)                 # foot pads
lander = np.asarray(img) > 0
win = Image.new("L", (W, H), 0); dw = ImageDraw.Draw(win)
for x in (455, 478, 556, 580):
    dw.rectangle([x - 7, 530, x + 7, 550], fill=255)                          # windows
dw.ellipse([505, 525, 531, 551], fill=255)                                    # round hatch
dw.rectangle([436, 557, 600, 561], fill=255)                                  # seam under the window band
lander &= ~(np.asarray(win) > 0)
flames = Image.new("L", (W, H), 0); df = ImageDraw.Draw(flames)
for cx, top, half, bot in [(518, 626, 13, 738), (447, 640, 9, 716), (589, 640, 9, 716)]:
    df.polygon([(cx - half, top), (cx + half, top), (cx + 3, bot), (cx - 3, bot)], fill=255)
flames = np.asarray(flames) > 0
# keep Earth detail clear of the lander: no blobs sitting on it or between its legs
earth_detail &= ~dilate(lander | flames, 24) & ~((xx > 330) & (xx < 712) & (yy > 600))
earth_art = ring | earth_detail

# --- the rest of the light artwork (rings, text, stars, moon surface), minus the redrawn areas
lander_zone = (xx > 330) & (xx < 712) & (yy > 488) & (yy < 745)
base = clean(light & ~earth_disc & ~lander_zone, LINE, GAP) | (clean(light, LINE, GAP) & lander_zone & (yy > 712))
base |= earth_art

# --- stack: moon/rings/earth < flames < lander < swoosh, each with a dark gap around it
def over(under, top, gap=GAP + 2): return (under & ~dilate(top, gap)) | top
art = over(base, flames)
art = over(art, lander)
art = over(art, red)
art = opening(art, 2)
art = drop_small(art, 120)              # specks under ~0.3 mm across don't print cleanly

# crop to the artwork, store as run-length rows
ys, xs = np.nonzero(art)
art = art[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
small = np.asarray(Image.fromarray(art.astype(np.uint8) * 255).resize(
    (OUT_PX, round(OUT_PX * art.shape[0] / art.shape[1])), Image.LANCZOS)) > 127
Image.fromarray((small * 255).astype(np.uint8)).save(os.path.join(HERE, "logo_silk.png"))
rows = []
for y, row in enumerate(small):
    padded = np.concatenate([[False], row, [False]])
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    if len(edges):
        rows.append([y, edges.reshape(-1, 2).tolist()])
json.dump({"width_px": small.shape[1], "height_px": small.shape[0], "rows": rows},
          open(os.path.join(HERE, "logo_silk.json"), "w"), separators=(",", ":"))
print(f"logo_silk: {small.shape[1]}x{small.shape[0]} px, {sum(len(r[1]) for r in rows)} runs, "
      f"silk coverage {100 * small.mean():.0f}%")

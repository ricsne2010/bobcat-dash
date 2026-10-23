#!/usr/bin/env python3
"""Fit a picture to the screen for the boot splash.

  python3 tools/fit_splash.py my_picture.jpg --size 1024x768
  python3 tools/fit_splash.py my_picture.jpg --size 1920x1080 --mode cover

Writes splash/splash.png at exactly the screen's resolution. The same file is used by:
  * the Pi's boot splash (Plymouth shows it pixel-for-pixel, it doesn't scale), and
  * the dash, which shows it at start-up before fading into the gauges.

--mode contain  (default) the whole picture is visible; any leftover space is filled with a
                plain border colour taken from the picture's own edges, so it blends in.
--mode cover    the picture fills the whole screen; whatever doesn't fit is trimmed off
                the edges (top/bottom or left/right), keeping the centre.
--background    border colour for contain mode: "auto" (default) or a colour like "#000000".
--margin        empty space around the picture in contain mode, in % of the screen (default 0).

Needs Pillow: on the Pi  sudo apt install python3-pil,  elsewhere  pip install pillow.
"""
import argparse
import os
import sys

from PIL import Image, ImageColor, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, "..", "splash", "splash.png")


def border_colour(img):
    """Median colour of the outermost pixels, so a letterbox border blends with the picture."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    px = [rgb.getpixel((x, y)) for x in range(0, w, max(1, w // 200)) for y in (0, h - 1)]
    px += [rgb.getpixel((x, y)) for y in range(0, h, max(1, h // 200)) for x in (0, w - 1)]
    return tuple(sorted(c[i] for c in px)[len(px) // 2] for i in range(3))


def fit(src, size, mode="contain", background="auto", margin=0.0):
    img = ImageOps.exif_transpose(Image.open(src))      # honour phone/camera rotation
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
    W, H = size
    bg = border_colour(img) if background == "auto" else ImageColor.getrgb(background)[:3]
    canvas = Image.new("RGB", (W, H), bg)
    if mode == "cover":
        out = ImageOps.fit(img, (W, H), method=Image.LANCZOS, centering=(0.5, 0.5))
        canvas.paste(out, (0, 0), out if out.mode == "RGBA" else None)
    else:
        bw, bh = int(W * (1 - 2 * margin / 100)), int(H * (1 - 2 * margin / 100))
        scale = min(bw / img.width, bh / img.height)
        out = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
        canvas.paste(out, ((W - out.width) // 2, (H - out.height) // 2), out if out.mode == "RGBA" else None)
    return canvas, img.size, out.size, bg


def main():
    ap = argparse.ArgumentParser(description="Fit a picture to the screen for the boot splash")
    ap.add_argument("picture")
    ap.add_argument("--size", default="1024x768", help="screen resolution, e.g. 1024x768 or 1920x1080")
    ap.add_argument("--mode", choices=["contain", "cover"], default="contain")
    ap.add_argument("--background", default="auto")
    ap.add_argument("--margin", type=float, default=0.0)
    ap.add_argument("-o", "--out", default=DEFAULT_OUT)
    a = ap.parse_args()
    W, H = (int(v) for v in a.size.lower().split("x"))
    canvas, orig, placed, bg = fit(a.picture, (W, H), a.mode, a.background, a.margin)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    canvas.save(a.out, optimize=True)
    print(f"{a.picture}: {orig[0]}x{orig[1]} -> picture {placed[0]}x{placed[1]} on a {W}x{H} screen "
          f"({a.mode}, border colour #{bg[0]:02x}{bg[1]:02x}{bg[2]:02x})")
    if placed[0] > orig[0] * 1.5 or placed[1] > orig[1] * 1.5:
        print("note: the picture was enlarged a lot and may look soft. A bigger original will look sharper.")
    print(f"wrote {os.path.abspath(a.out)}")


if __name__ == "__main__":
    sys.exit(main())

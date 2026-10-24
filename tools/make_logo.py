"""Makes the logo pictures the dash and its web pages use from splash/logo-original.png (the Project Moon Pi
patch on black): the black around the patch becomes transparent (the red swoosh that sticks out is kept).
  splash/logo.png        512 px (dash About screen, web Software page)
  splash/logo-small.png  128 px (dash header, web page header, exported report)
Run again only if the original picture changes:  python3 tools/make_logo.py
"""
import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, "splash", "logo-original.png")


def main():
    im = Image.open(SRC).convert("RGB")
    w, h = im.size
    # inside the patch's white rim: keep everything; outside it: keep only what isn't near-black (the swoosh)
    disc = Image.new("L", im.size, 0)
    r = w * 0.424
    ImageDraw.Draw(disc).ellipse((w / 2 - r, h / 2 - r, w / 2 + r, h / 2 + r), fill=255)
    bright = im.convert("L").point(lambda v: 255 if v > 48 else 0)
    alpha = Image.composite(Image.new("L", im.size, 255), bright, disc).filter(ImageFilter.GaussianBlur(1.2))
    im.putalpha(alpha)
    im = im.crop(alpha.point(lambda v: 255 if v > 20 else 0).getbbox())
    side = max(im.size)                     # square, centred
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    for name, px in (("logo.png", 512), ("logo-small.png", 128)):
        sq.resize((px, px), Image.LANCZOS).save(os.path.join(HERE, "splash", name), optimize=True)
        print("wrote splash/" + name)


if __name__ == "__main__":
    main()

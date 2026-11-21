"""App icons for the installable app (PWA): gold TSLAW mark on a deep navy tile.
Run:  python scripts/make_icons.py
"""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "static", "icons")
os.makedirs(OUT, exist_ok=True)
logo = Image.open(os.path.join(ROOT, "static", "favicon.png")).convert("RGBA")
bbox = logo.getchannel("A").point(lambda a: 255 if a > 20 else 0).getbbox()
logo = logo.crop(bbox)


def tile(size, logo_frac, ring=True):
    S = size * 4  # draw large, then downsample for smooth edges
    yy, xx = np.mgrid[0:S, 0:S] / S
    d = np.sqrt((xx - .5) ** 2 + (yy - .32) ** 2)
    top, bot = np.array([26, 64, 133]), np.array([9, 24, 56])
    t = np.clip(d / .85, 0, 1)[..., None]
    bg = Image.fromarray((top * (1 - t) + bot * t).astype(np.uint8), "RGB").convert("RGBA")
    # gold gradient shaped like the logo
    w = int(S * logo_frac)
    h = int(w * logo.height / logo.width)
    mask = logo.resize((w, h), Image.LANCZOS).getchannel("A")
    gy, gx = np.mgrid[0:h, 0:w]
    g = np.clip((gx / w * .6 + gy / h * .4), 0, 1)[..., None]
    c1, c2, c3 = np.array([243, 226, 176]), np.array([217, 188, 120]), np.array([142, 114, 56])
    gold = np.where(g < .5, c1 * (1 - g * 2) + c2 * (g * 2), c2 * (1 - (g - .5) * 2) + c3 * ((g - .5) * 2))
    gold_img = Image.fromarray(gold.astype(np.uint8), "RGB").convert("RGBA")
    gold_img.putalpha(mask)
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    glow.paste(Image.new("RGBA", (w, h), (220, 192, 128, 120)), ((S - w) // 2, (S - h) // 2), mask)
    bg.alpha_composite(glow.filter(ImageFilter.GaussianBlur(S * .03)))
    bg.alpha_composite(gold_img, ((S - w) // 2, (S - h) // 2))
    if ring:
        dr = ImageDraw.Draw(bg)
        m = S * .085
        dr.ellipse([m, m, S - m, S - m], outline=(201, 169, 97, 150), width=max(2, int(S * .008)))
    return bg.resize((size, size), Image.LANCZOS)


for name, size, frac, ring in [("icon-192.png", 192, .56, True), ("icon-512.png", 512, .56, True),
                               ("icon-maskable-512.png", 512, .46, False), ("apple-touch-icon.png", 180, .56, False),
                               ("favicon-32.png", 32, .74, False)]:
    img = tile(size, frac, ring)
    if name == "apple-touch-icon.png":
        img = img.convert("RGB")  # iOS wants no transparency
    img.save(os.path.join(OUT, name))
    print(name, img.size)

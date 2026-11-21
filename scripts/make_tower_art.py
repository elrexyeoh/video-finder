"""Turns the corporate skyline artwork (art/corporate-skyline-source.jpg, a phone screenshot of the
company's splash screen) into static/tower-art.webp: gold lines on a transparent background, with a
soft navy plate in the middle so other background lines don't cross the corporate tower.
Run:  python scripts/make_tower_art.py
"""
import os

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.join(os.path.dirname(__file__), "..")
SRC = os.path.join(ROOT, "art", "corporate-skyline-source.jpg")
OUT = os.path.join(ROOT, "static", "tower-art.webp")
TOP, BOTTOM = 652, 1252   # below the logo ring, above the phone's home bar
SCALE = 2

im = Image.open(SRC).convert("RGB").crop((0, TOP, 590, BOTTOM))
im = im.resize((im.width * SCALE, im.height * SCALE), Image.LANCZOS)
px = np.asarray(im).astype(np.float32)

# Background estimate: heavy blur of the dark navy, so it follows the original gradient.
bg = np.asarray(im.filter(ImageFilter.MinFilter(9)).filter(ImageFilter.GaussianBlur(24))).astype(np.float32)
bg = np.minimum(bg, px)

# How much of each pixel is gold line: lines are warm (red high), the background is blue-dark.
warm = px[..., 0] - bg[..., 0]
alpha = np.clip((warm - 6) / 125, 0, 1) ** 0.85
a = np.maximum(alpha, 1e-3)[..., None]
rgb = np.clip((px - bg * (1 - a)) / a, 0, 255)  # un-mix the line colour from the background
# restore the warm gold of the original artwork (un-mixing drifts bright lines towards white)
lum = rgb.mean(axis=2, keepdims=True) / 255
gold = np.array([226, 196, 128], np.float32)
rgb = np.clip(0.45 * rgb + 0.55 * gold * (0.55 + 0.6 * lum), 0, 255)

h, w = alpha.shape
yy, xx = np.mgrid[0:h, 0:w]
# soft navy plate: strongest behind the buildings, fading towards the sides and top
plate = np.clip(1 - np.abs((xx - w / 2) / (w * 0.62)) ** 3, 0, 1) * np.clip((yy - h * 0.25) / (h * 0.35), 0, 1) * 0.78
navy = np.array([9, 26, 56], np.float32)
out_a = alpha + plate * (1 - alpha)
out_rgb = (rgb * alpha[..., None] + navy * (plate * (1 - alpha))[..., None]) / np.maximum(out_a, 1e-3)[..., None]
# fade out the very bottom (the source is cut there) and the left/right edges
fade = np.clip((h - yy) / (h * 0.06), 0, 1) * np.clip(np.minimum(xx, w - xx) / (w * 0.04), 0, 1)
out_a = out_a * fade

rgba = np.dstack([out_rgb, out_a * 255]).astype(np.uint8)
Image.fromarray(rgba, "RGBA").save(OUT, "WEBP", quality=84, method=6)
print(OUT, Image.open(OUT).size, f"{os.path.getsize(OUT)/1024:.0f} KB")

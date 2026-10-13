"""Abstract preview art for the demo library (no real models, people or brands)."""
import math
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFilter

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "previews")
os.makedirs(out, exist_ok=True)
PALETTES = [
    ((247, 168, 192), (155, 127, 209), (124, 195, 221)), ((255, 196, 140), (230, 90, 110), (60, 40, 90)),
    ((120, 200, 170), (40, 110, 130), (20, 30, 60)), ((250, 230, 180), (200, 120, 70), (70, 40, 40)),
    ((150, 190, 255), (70, 90, 200), (25, 20, 60)), ((220, 240, 200), (110, 170, 90), (30, 60, 40)),
    ((255, 210, 230), (240, 120, 160), (90, 40, 80)), ((200, 220, 230), (120, 140, 160), (40, 45, 60)),
]


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def art(n):
    rnd = random.Random(n * 7919)
    pal = PALETTES[n % len(PALETTES)]
    w, h = 300, 400
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        t = y / h
        c = lerp(pal[0], pal[1], t * 1.4) if t < 0.7 else lerp(pal[1], pal[2], (t - 0.7) / 0.3)
        for x in range(w):
            px[x, y] = c
    d = ImageDraw.Draw(im, "RGBA")
    style = n % 4
    if style == 0:  # sun and layered hills
        d.ellipse((w * 0.55, h * 0.12, w * 0.85, h * 0.12 + w * 0.3), fill=(255, 245, 235, 230))
        for i in range(5):
            y0 = h * (0.55 + i * 0.09)
            pts = [(0, h)] + [(x, y0 + 18 * math.sin(x / (30 + i * 9) + n + i)) for x in range(0, w + 10, 10)] + [(w, h)]
            d.polygon(pts, fill=lerp(pal[1], pal[2], i / 5) + (235,))
    elif style == 1:  # floating circles
        for i in range(9):
            r = rnd.randint(18, 70)
            x, y = rnd.randint(0, w), rnd.randint(0, h)
            d.ellipse((x - r, y - r, x + r, y + r), outline=(255, 255, 255, 200), width=3)
    elif style == 2:  # paper-cut waves
        for i in range(7):
            y0 = h * (0.3 + i * 0.1)
            pts = [(0, h)] + [(x, y0 + 14 * math.sin(x / 22 + i * 1.7)) for x in range(0, w + 6, 6)] + [(w, h)]
            d.polygon(pts, fill=lerp(pal[0], pal[2], i / 7) + (220,))
    else:  # tower and stars
        for _ in range(40):
            x, y = rnd.randint(0, w), rnd.randint(0, int(h * 0.55))
            d.ellipse((x, y, x + 2, y + 2), fill=(255, 255, 255, 200))
        d.rectangle((w * 0.42, h * 0.38, w * 0.58, h * 0.85), fill=(245, 240, 235, 240))
        d.polygon([(w * 0.38, h * 0.38), (w * 0.5, h * 0.27), (w * 0.62, h * 0.38)], fill=(200, 70, 70, 240))
        d.rectangle((0, h * 0.85, w, h), fill=lerp(pal[2], (0, 0, 0), 0.3) + (255,))
    im = im.filter(ImageFilter.GaussianBlur(0.6))
    im.save(os.path.join(out, f"{n}.png"))


for i in range(1, 17):
    art(i)
print("previews written to", out)

"""Draws the Model Librarian icon: a row of holographic spines on an ink shelf,
the tallest carrying Prompto's red orb and the last one leaning, on a white
rounded tile with a lavender hairline. It shares Prompto's gradient, orb and
tile (EY4O/prompto, tools/make-icons.py) so the two tools match.

    python tools/make-icon.py      # docs/images/icon.png and js/assets/logo-64.png

Needs Pillow and NumPy. Everything is drawn on a 512 grid at 4x and scaled
down with LANCZOS.
"""

import os

import numpy as np
from PIL import Image, ImageDraw

SS = 4                      # supersampling factor
G = 512 * SS                # drawing grid
INK = (16, 17, 23)
HOLO = [(0.0, "#f7dccf"), (0.3, "#f4a7c0"), (0.62, "#b9a3e3"), (1.0, "#8fcfe3")]
ORB = [(0.0, "#fff1f1"), (0.22, "#ffb3b3"), (0.6, "#f26d6d"), (1.0, "#c23b4a")]

SHELF_Y = 400
BOOKS = [(100, 158, 176), (166, 228, 138)]      # (left, right, top) of the banded books
HERO = (236, 316, 84)                           # the tallest book, with the orb
LEAN = {"w": 56, "h": 214, "angle": -14, "cx": 360, "cy": SHELF_Y - 104}
BAND_ALPHA = 115


def S(v):
    return v * SS


def rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)


def ramp(t, stops):
    """Colour at t (array, 0..1) along gradient stops."""
    t = np.clip(t, 0, 1)
    out = np.zeros(t.shape + (3,), dtype=np.float32)
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        m = (t >= a) & (t <= b)
        k = ((t - a) / (b - a))[..., None]
        out[m] = (rgb(ca) * (1 - k) + rgb(cb) * k)[m]
    return out


def layer(color_fn, mask):
    """An RGBA layer: colours from color_fn(xx, yy), alpha from an L mask."""
    yy, xx = np.mgrid[0:G, 0:G].astype(np.float32)
    a = np.asarray(mask, dtype=np.float32)[..., None]
    return Image.fromarray(np.concatenate([color_fn(xx, yy), a], axis=2).astype(np.uint8), "RGBA")


def rounded(draw, box, radius, fill):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle([S(x0), S(y0), S(x1), S(y1)], radius=S(radius), fill=fill)


def tile(img):
    ImageDraw.Draw(img).rounded_rectangle([S(16), S(16), S(496), S(496)], radius=S(108),
                                          fill=(255, 255, 255, 255), outline=(220, 219, 227, 255), width=S(10))


def lean_canvas(mode):
    """A blank canvas the size of the leaning book, drawn upright and rotated by place()."""
    w, h = LEAN["w"], LEAN["h"]
    return Image.new(mode, (S(w), S(h)), 0 if mode == "L" else (0, 0, 0, 0)), w, h


def place(shape):
    shape = shape.rotate(LEAN["angle"], expand=True, resample=Image.BICUBIC)
    return shape, (S(LEAN["cx"]) - shape.width // 2, S(LEAN["cy"]) - shape.height // 2)


def spines(img):
    """All four books cut from one holographic sheet: one diagonal sweep across the row."""
    mask = Image.new("L", (G, G), 0)
    d = ImageDraw.Draw(mask)
    for x0, x1, top in BOOKS + [HERO]:
        rounded(d, (x0, top, x1, SHELF_Y), 18, 255)
    lean, w, h = lean_canvas("L")
    ImageDraw.Draw(lean).rounded_rectangle([0, 0, S(w), S(h)], radius=S(18), fill=255)
    lean, at = place(lean)
    mask.paste(255, at, lean)
    bx0, by0, bx1, by1 = S(100), S(84), S(400), S(SHELF_Y)
    img.alpha_composite(layer(lambda xx, yy: ramp(((xx - bx0) / (bx1 - bx0) + (yy - by0) / (by1 - by0)) / 2, HOLO), mask))


def bands(img):
    """Two faint ink bands on each book except the one with the orb."""
    over = Image.new("RGBA", (G, G), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for x0, x1, top in BOOKS:
        for y in (top + 34, SHELF_Y - 48):
            rounded(d, (x0 + 14, y, x1 - 14, y + 9), 4.5, INK + (BAND_ALPHA,))
    img.alpha_composite(over)
    lean, w, h = lean_canvas("RGBA")
    ld = ImageDraw.Draw(lean)
    for y in (34, h - 48):
        ld.rounded_rectangle([S(14), S(y), S(w - 14), S(y + 9)], radius=S(4.5), fill=INK + (BAND_ALPHA,))
    lean, at = place(lean)
    img.alpha_composite(lean, at)


def orb(img, cx, cy, radius):
    X, Y, R = S(cx), S(cy), S(radius)
    mask = Image.new("L", (G, G), 0)
    ImageDraw.Draw(mask).ellipse([X - R, Y - R, X + R, Y + R], fill=255)
    # radial gradient: focus at (34%, 30%) of the orb's box, radius 75% of its width
    fx, fy, fr = X - R + 0.34 * 2 * R, Y - R + 0.30 * 2 * R, 0.75 * 2 * R
    img.alpha_composite(layer(lambda xx, yy: ramp(np.hypot(xx - fx, yy - fy) / fr, ORB), mask))


def icon():
    img = Image.new("RGBA", (G, G), (0, 0, 0, 0))
    tile(img)
    spines(img)
    bands(img)
    x0, x1, top = HERO
    orb(img, (x0 + x1) / 2, top + 62, 32)
    rounded(ImageDraw.Draw(img), (84, SHELF_Y, 428, SHELF_Y + 20), 10, INK + (255,))
    return img


def save(img, size, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.resize((size, size), Image.LANCZOS).save(path, optimize=True)
    print("wrote", path)


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    art = icon()
    big = os.path.join(root, "docs", "images", "icon.png")
    save(art, 512, big)
    # The window header and toolbar button use the 512px icon scaled to 64.
    small = os.path.join(root, "js", "assets", "logo-64.png")
    Image.open(big).convert("RGBA").resize((64, 64), Image.LANCZOS).save(small, optimize=True)
    print("wrote", small)


if __name__ == "__main__":
    main()

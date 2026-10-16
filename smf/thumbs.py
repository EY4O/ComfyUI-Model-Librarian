"""Small WebP thumbnails of model previews, for the Library cards.

Preview images next to models are often full-size PNGs of several MB; a
Library page shows a hundred of them. A thumbnail is made once per preview
(and again when the preview changes) and kept in this install's data folder
(`thumbs/`). Videos and previews that are already small are served as they are.
"""
from __future__ import annotations

import hashlib
import os
import threading

from . import config

SMALL = 150 * 1024        # previews this small are served as is
MAX_FILES = 6000          # oldest thumbnails go first beyond this
_lock = threading.Lock()


def folder() -> str:
    d = os.path.join(config.local_dir(), "thumbs")
    os.makedirs(d, exist_ok=True)
    return d


def _prune(d: str) -> None:
    try:
        files = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".webp")]
        if len(files) <= MAX_FILES:
            return
        files.sort(key=lambda p: os.path.getmtime(p))
        for p in files[: len(files) - MAX_FILES]:
            os.remove(p)
    except OSError:
        pass


def thumb_for(src: str, width: int = 448) -> str:
    """Path of a thumbnail of `src` (made if needed), or `src` itself when it's
    a video, already small, or can't be read as an image."""
    width = max(64, min(1024, int(width)))
    try:
        st = os.stat(src)
    except OSError:
        return src
    if st.st_size <= SMALL or src.lower().endswith((".mp4", ".webm", ".gif")):
        return src
    key = hashlib.sha1(f"{os.path.normcase(src)}|{st.st_size}|{st.st_mtime_ns}|{width}".encode()).hexdigest()
    d = folder()
    out = os.path.join(d, key + ".webp")
    if os.path.isfile(out):
        return out
    try:
        from PIL import Image, ImageOps
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((width, width * 2))
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
            tmp = out + f".{threading.get_ident()}.tmp"
            im.save(tmp, "WEBP", quality=80, method=4)
        os.replace(tmp, out)
    except Exception:
        return src
    with _lock:
        _prune(d)
    return out

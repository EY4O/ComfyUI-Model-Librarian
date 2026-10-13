"""Model Librarian's own recipe store (no LoRA Manager needed).

Lives in the shared data folder (`recipes/`), so every ComfyUI install that
shares Stability Matrix's folders sees the same recipes. One JSON file per
recipe (`<id>.json`, the shared recipe format) plus an optional thumbnail
(`<id>.webp`). Deleting moves both into `recipes/_deleted/` instead of
removing them.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import time
import uuid

from . import config
from .recipe_parse import clean

_ID = re.compile(r"^[a-f0-9]{12}$")
THUMB_PX = 512


def folder() -> str:
    d = os.path.join(config.data_dir(), "recipes")
    os.makedirs(d, exist_ok=True)
    return d


def _path(rid: str, ext: str = ".json") -> str:
    if not _ID.match(rid or ""):
        raise ValueError("bad recipe id")
    return os.path.join(folder(), rid + ext)


def _write(p: str, data: bytes) -> None:
    tmp = p + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, p)


def make_thumbnail(image: bytes) -> bytes | None:
    """512px WebP thumbnail (Pillow ships with ComfyUI); None if it can't."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(image))
        im.thumbnail((THUMB_PX, THUMB_PX))
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        out = io.BytesIO()
        im.save(out, "WEBP", quality=82)
        return out.getvalue()
    except Exception:
        return None


def thumb_data_url(thumb: bytes | None) -> str | None:
    return "data:image/webp;base64," + base64.b64encode(thumb).decode() if thumb else None


def _from_data_url(s: str | None) -> bytes | None:
    if not s or not isinstance(s, str) or "," not in s or not s.startswith("data:image/"):
        return None
    try:
        return base64.b64decode(s.split(",", 1)[1])
    except ValueError:
        return None


def summary(r: dict) -> dict:
    return {
        "id": r.get("id"), "title": r.get("title") or "Untitled recipe", "created": r.get("created"),
        "format": r.get("format"), "base_model": r.get("base_model"), "source_url": (r.get("source") or {}).get("url"),
        "model": ((r.get("model") or {}).get("name") or (r.get("model") or {}).get("file")),
        "lora_count": len(r.get("loras") or []), "tags": r.get("tags") or [], "fav": bool(r.get("fav")),
        "lm_id": r.get("lm_id"), "media": r.get("media") or "image",
        "has_thumb": os.path.isfile(_path(r["id"], ".webp")) if r.get("id") else False,
    }


def list_recipes() -> list[dict]:
    out = []
    for fn in os.listdir(folder()):
        if fn.endswith(".json") and _ID.match(fn[:-5]):
            try:
                with open(os.path.join(folder(), fn), encoding="utf-8") as f:
                    out.append(summary(json.load(f, parse_constant=lambda _c: None)))
            except (OSError, ValueError):
                continue
    return sorted(out, key=lambda r: r.get("created") or 0, reverse=True)


def get(rid: str) -> dict | None:
    try:
        with open(_path(rid), encoding="utf-8") as f:
            return clean(json.load(f))  # files saved before NaN cleaning
    except (OSError, ValueError):
        return None


def save(recipe: dict, thumb_data_url_: str | None = None) -> dict:
    r = clean(dict(recipe))
    r["id"] = r.get("id") if _ID.match(str(r.get("id") or "")) and get(r["id"]) else uuid.uuid4().hex[:12]
    r["created"] = r.get("created") or time.time()
    r["schema"] = r.get("schema") or "recipe/1"
    thumb = _from_data_url(thumb_data_url_)
    if thumb and not (thumb[:4] == b"RIFF" and thumb[8:12] == b"WEBP" and len(thumb) < 400_000):
        thumb = make_thumbnail(thumb)  # any image type -> a 512px WebP (the file is served as .webp)
    if thumb:
        _write(_path(r["id"], ".webp"), thumb)
    _write(_path(r["id"]), json.dumps(r, ensure_ascii=False, indent=1).encode("utf-8"))
    return r


EDITABLE = ("title", "tags", "notes", "fav", "lm_id")


def update(rid: str, patch: dict) -> dict | None:
    r = get(rid)
    if r is None:
        return None
    for k in EDITABLE:
        if k in patch:
            v = patch[k]
            if k == "tags":
                v = [str(t).strip() for t in (v or []) if str(t).strip()][:50]
            elif k == "fav":
                v = bool(v)
            elif k == "lm_id":  # the copy of this recipe in LoRA Manager
                v = str(v)[:64] if v else None
            else:
                v = str(v or "")[:2000]
            r[k] = v
    r["updated"] = time.time()
    _write(_path(rid), json.dumps(r, ensure_ascii=False, indent=1).encode("utf-8"))
    return r


def delete(rid: str) -> bool:
    p = _path(rid)
    if not os.path.isfile(p):
        return False
    trash = os.path.join(folder(), "_deleted")
    os.makedirs(trash, exist_ok=True)
    for ext in (".json", ".webp"):
        src = _path(rid, ext)
        if os.path.isfile(src):
            shutil.move(src, os.path.join(trash, rid + ext))
    return True


def thumb_path(rid: str) -> str | None:
    p = _path(rid, ".webp")
    return p if os.path.isfile(p) else None

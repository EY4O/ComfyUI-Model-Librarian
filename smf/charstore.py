"""Characters: the one list Model Librarian, its Chrome extension, the Character Select node and the Gallery share.

characters.json in Model Librarian's shared data folder (.sm_model_fetcher), each character's picture beside it in
characters/<id>.webp. Whoever writes it holds the file's lock (characters.json.lock, the way smf/config.py's
update_json does) while it reads, changes and writes the whole file.

    {"v": 1, "characters": [{
      "id": "chr_1a2b3c4d", "name": "Aurelia", "series": "Lighthouse Tales", "tag": "aurelia_(lighthouse_tales)",
      "aliases": [], "appearance": ["silver hair", "long hair", "blue eyes"],
      "outfits": {"default": ["white dress", "straw hat"]},
      "lora": null, "image": "characters/chr_1a2b3c4d.webp",
      "source": {"site": "danbooru", "post": "1234567", "url": "https://danbooru.donmai.us/posts/1234567", "post_count": 4800, "solo": true},
      "created": 1761566400.0, "updated": 1761566400.0}]}

Pure functions only (no files, no locks): the same file is smf/charstore.py in ComfyUI-Model-Librarian and
mlgallery/charstore.py in Model-Librarian-Gallery. Keep the two identical.
"""
from __future__ import annotations

import binascii
import re
import secrets

FILE = "characters.json"
PICTURES = "characters"  # the folder beside FILE
VERSION = 1
CAPS = {"text": 100, "tag": 120, "tags": 80, "outfits": 24, "url": 2000, "picture": 300_000, "characters": 5000}
SITES = ("danbooru", "safebooru", "gelbooru", "e621", "e926")


def empty() -> dict:
    return {"v": VERSION, "characters": []}


def norm(tag) -> str:
    """A tag as Danbooru writes it and as a prompt does are the same tag: aurelia_(lighthouse_tales) = Aurelia (Lighthouse Tales)."""
    return re.sub(r"\s+", " ", str(tag or "").replace("_", " ")).strip().lower()


def new_id() -> str:
    return "chr_" + secrets.token_hex(4)


def _text(v, cap: int) -> str:
    return re.sub(r"[\x00-\x1f]+", " ", str(v or "")).strip()[:cap]


def _tags(v) -> list[str]:
    """A list of prompt tags: trimmed, spaces for underscores, no repeats, capped."""
    out, seen = [], set()
    for t in v if isinstance(v, list) else []:
        t = _text(t, CAPS["tag"]).replace("_", " ")
        if t and norm(t) not in seen:
            seen.add(norm(t))
            out.append(t)
    return out[: CAPS["tags"]]


def clean_import(raw) -> dict | None:
    """What the Chrome extension sends for one character, checked and capped:
    {tag, name, series, appearance, outfit: {name, tags}, mode: "outfit" | "new", source: {site, post, url, post_count, solo}}.
    None when there's no tag or name to file it under."""
    if not isinstance(raw, dict):
        return None
    tag = _text(raw.get("tag"), CAPS["tag"]).replace(" ", "_")
    name = _text(raw.get("name"), CAPS["text"]) or _text(tag.replace("_", " "), CAPS["text"])
    if not tag and not name:
        return None
    o = raw.get("outfit") if isinstance(raw.get("outfit"), dict) else {}
    s = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    url = _text(s.get("url"), CAPS["url"])
    try:
        count = max(0, int(s.get("post_count") or 0))
    except (TypeError, ValueError):
        count = 0
    return {
        "tag": tag, "name": name, "series": _text(raw.get("series"), CAPS["text"]),
        "appearance": _tags(raw.get("appearance")),
        "outfit": {"name": _text(o.get("name"), CAPS["text"]).lower() or "default", "tags": _tags(o.get("tags"))},
        "mode": "new" if raw.get("mode") == "new" else "outfit",
        "source": {"site": s.get("site") if s.get("site") in SITES else None, "post": _text(s.get("post"), 40) or None,
                   "url": url if url.startswith("https://") else None, "post_count": count, "solo": bool(s.get("solo"))},
    }


def find(data: dict, tag) -> dict | None:
    """The character with this booru tag (the first one, when a fresh copy was made too)."""
    k = norm(tag)
    return next((c for c in data.get("characters") or [] if k and norm(c.get("tag")) == k), None) if k else None


def _unique(name: str, taken) -> str:
    low = {str(t).lower() for t in taken}
    if name.lower() not in low:
        return name
    n = 2
    while f"{name} {n}".lower() in low:
        n += 1
    return f"{name} {n}"


def apply_import(data: dict, imp: dict, now: float, cid: str | None = None) -> tuple[dict, bool]:
    """Files a cleaned import into the list (changed in place) -> (the character, made new).

    mode "outfit" with the tag already there: the new appearance tags join its own and the post's outfit is added
    under its name (" 2" and so on when that name is taken). Otherwise a new character (its name made unique)."""
    if not isinstance(data.get("characters"), list):
        data["characters"] = []
    data["v"] = VERSION
    outfit = imp["outfit"]
    have = find(data, imp["tag"]) if imp["mode"] == "outfit" else None
    if have:
        known = {norm(t) for t in have.get("appearance") or []}
        have["appearance"] = list(have.get("appearance") or []) + [t for t in imp["appearance"] if norm(t) not in known]
        have["appearance"] = have["appearance"][: CAPS["tags"]]
        outfits = have.get("outfits") if isinstance(have.get("outfits"), dict) else {}
        if outfit["tags"] and len(outfits) < CAPS["outfits"]:
            outfits[_unique(outfit["name"], outfits)] = outfit["tags"]
        have["outfits"] = outfits
        if not (have.get("source") or {}).get("url"):
            have["source"] = imp["source"]
        have["updated"] = now
        return have, False
    c = {
        "id": cid or new_id(), "name": _unique(imp["name"], [x.get("name") or "" for x in data["characters"]]),
        "series": imp["series"], "tag": imp["tag"], "aliases": [], "appearance": imp["appearance"],
        "outfits": {outfit["name"]: outfit["tags"]} if outfit["tags"] else {},
        "lora": None, "image": None, "source": imp["source"], "created": now, "updated": now,
    }
    data["characters"].append(c)
    del data["characters"][: max(0, len(data["characters"]) - CAPS["characters"])]
    return c, True


def picture(data_url) -> tuple[bytes, str] | None:
    """A picture sent as a data: URL -> (its bytes, its extension), only a small WebP, JPEG or PNG."""
    if not isinstance(data_url, str) or not data_url.startswith("data:image/") or "," not in data_url:
        return None
    try:
        b = binascii.a2b_base64(data_url.split(",", 1)[1])
    except (ValueError, binascii.Error):
        return None
    if not b or len(b) > CAPS["picture"]:
        return None
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return b, "webp"
    if b[:3] == b"\xff\xd8\xff":
        return b, "jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return b, "png"
    return None


def picture_path(cid: str, ext: str) -> str:
    """Where a character's picture goes, relative to the folder FILE is in (and what its `image` says)."""
    return f"{PICTURES}/{re.sub(r'[^a-z0-9_]', '', str(cid).lower())}.{ext}"


def merge(shared, local) -> dict:
    """Two copies of the list as one (Model Librarian moving its local data into the shared folder): by id, newer wins."""
    out = {c.get("id"): c for c in (shared or {}).get("characters") or [] if isinstance(c, dict)}
    for c in (local or {}).get("characters") or []:
        if isinstance(c, dict) and (c.get("updated") or 0) > ((out.get(c.get("id")) or {}).get("updated") or 0):
            out[c.get("id")] = c
    return {"v": VERSION, "characters": list(out.values())}


def summary(c: dict) -> dict:
    """What the extension needs to know a character is there: its tag, name and outfits."""
    return {"id": c.get("id"), "name": c.get("name"), "series": c.get("series"), "tag": c.get("tag"),
            "outfits": list((c.get("outfits") or {}).keys()), "has_image": bool(c.get("image"))}

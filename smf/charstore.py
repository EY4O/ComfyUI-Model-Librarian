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
      "created": 1761566400.0, "updated": 1761566400.0,
      "changed": {"name": 1761566400.0, "appearance": 1761566400.0, ...}}],
     "deleted": [{"id": "chr_9z8y7x6w", "at": 1761570000.0}]}

`changed` says when each part (PARTS) last changed, so when the Gallery and the list both changed a character, each
part keeps the side that changed it last (merge_parts). `deleted` remembers the characters deleted, so a deletion in
one place reaches the other instead of the character coming back.

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
PARTS = ("name", "series", "tag", "aliases", "appearance", "outfits", "lora", "image")
DELETED_KEPT = 1000  # deletions remembered


def empty() -> dict:
    return {"v": VERSION, "characters": []}


def norm(tag) -> str:
    """A tag as Danbooru writes it and as a prompt does are the same tag: aurelia_(lighthouse_tales) = Aurelia (Lighthouse Tales)."""
    return re.sub(r"\s+", " ", str(tag or "").replace("_", " ")).strip().lower()


def name_key(name) -> str:
    """A name for telling names apart: its words in any order, its series in brackets left out. Danbooru puts a family
    name first (vale_lumen), you may not (Lumen Vale): one name."""
    return " ".join(sorted(re.sub(r"\s*\(.*\)$", "", norm(name).replace("-", " ")).split()))


def by_name(data: dict, name) -> dict | None:
    """The character called this (its words in any order) that has no booru tag yet."""
    k = name_key(name)
    return next((c for c in data.get("characters") or [] if k and not norm(c.get("tag")) and name_key(c.get("name")) == k), None) if k else None


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
    {tag, name, series, appearance, outfit: {name, tags}, mode: "outfit" | "new" | "link", target: (link) a character's id,
    source: {site, post, url, post_count, solo}}.
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
        "mode": raw.get("mode") if raw.get("mode") in ("new", "link") else "outfit",
        "target": str(raw.get("target")) if raw.get("mode") == "link" and re.fullmatch(r"chr_[a-z0-9]{1,40}", str(raw.get("target") or "")) else None,
        "source": {"site": s.get("site") if s.get("site") in SITES else None, "post": _text(s.get("post"), 40) or None,
                   "url": url if url.startswith("https://") else None, "post_count": count, "solo": bool(s.get("solo"))},
    }


def check(data) -> dict:
    """The list as read, made safe to change: anything in it that isn't a character left out. ValueError when it isn't a
    list at all, or is from a newer Model Librarian or Gallery (its format may have changed in ways this one can't keep)."""
    if not isinstance(data, dict):
        raise ValueError("The character list isn't readable")
    try:
        v = int(data.get("v") or VERSION)
    except (TypeError, ValueError):
        v = VERSION
    if v > VERSION:
        raise ValueError("The character list is from a newer Model Librarian or Gallery: update this one")
    data["characters"] = [c for c in data.get("characters") or [] if isinstance(c, dict) and c.get("id")] if isinstance(data.get("characters"), list) else []
    data["deleted"] = [d for d in data.get("deleted") or [] if isinstance(d, dict) and d.get("id")] if isinstance(data.get("deleted"), list) else []
    data["v"] = VERSION
    return data


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


def changed_at(c: dict, part: str) -> float:
    """When this part of the character last changed (a character from before `changed`: when it last changed at all)."""
    t = (c.get("changed") or {}).get(part)
    return float(t if isinstance(t, (int, float)) else c.get("updated") or c.get("created") or 0)


def stamp(c: dict, parts, now: float) -> None:
    """These parts changed now."""
    ch = c.get("changed") if isinstance(c.get("changed"), dict) else {}
    for p in parts:
        ch[p] = now
    c["changed"] = ch
    c["updated"] = max(float(c.get("updated") or 0), now)


def merge_parts(a: dict, b: dict) -> dict:
    """One character from two copies of it (the list's and the Gallery's): each part from whichever changed it last
    (a on a tie); everything else from a."""
    out = dict(a)
    ch = {}
    for p in PARTS:
        ta, tb = changed_at(a, p), changed_at(b, p)
        if tb > ta:
            out[p] = b.get(p)
        ch[p] = max(ta, tb)
    out["changed"] = ch
    out["updated"] = max([float(a.get("updated") or 0), float(b.get("updated") or 0)] + list(ch.values()))
    return out


def delete(data: dict, cid: str, now: float) -> bool:
    """Takes a character out of the list and remembers it was deleted -> whether it was there."""
    check(data)
    before = len(data.get("characters") or [])
    data["characters"] = [c for c in data.get("characters") or [] if c.get("id") != cid]
    gone = [d for d in data.get("deleted") or [] if isinstance(d, dict) and d.get("id") != cid] + [{"id": cid, "at": now}]
    data["deleted"] = gone[-DELETED_KEPT:]
    return len(data["characters"]) < before


def deleted_ids(data: dict) -> set:
    return {d.get("id") for d in data.get("deleted") or [] if isinstance(d, dict)}


def apply_import(data: dict, imp: dict, now: float, cid: str | None = None) -> tuple[dict, bool]:
    """Files a cleaned import into the list (changed in place) -> (the character, made new).

    mode "outfit" with the tag already there: the new appearance tags join its own and the post's outfit is added
    under its name (" 2" and so on when that name is taken). No character with the tag, but one of the same name (its
    words in any order: one you made yourself, say) without a tag: that one, its tag and series filled in, its name
    yours. mode "link": the character you picked (target), the same way (its tag filled in when it has none). Otherwise a
    new character (its name made unique)."""
    check(data)
    outfit = imp["outfit"]
    have = find(data, imp["tag"]) if imp["mode"] == "outfit" else None
    picked = next((c for c in data["characters"] if c.get("id") == imp.get("target")), None) if imp["mode"] == "link" and imp.get("target") else None
    if picked:
        have = picked
        parts = []
        if not norm(have.get("tag")):
            have["tag"] = imp["tag"]
            parts.append("tag")
        if not have.get("series") and imp["series"]:
            have["series"] = imp["series"]
            parts.append("series")
        stamp(have, parts, now)
    elif not have and not find(data, imp["tag"]):
        have = by_name(data, imp["name"])
        if have:
            have["tag"] = imp["tag"]
            parts = ["tag"]
            if not have.get("series") and imp["series"]:
                have["series"] = imp["series"]
                parts.append("series")
            stamp(have, parts, now)
    if have:
        known = {norm(t) for t in have.get("appearance") or []}
        more = [t for t in imp["appearance"] if norm(t) not in known]
        have["appearance"] = (list(have.get("appearance") or []) + more)[: CAPS["tags"]]
        outfits = have.get("outfits") if isinstance(have.get("outfits"), dict) else {}
        added = bool(outfit["tags"] and len(outfits) < CAPS["outfits"])
        if added:
            outfits[_unique(outfit["name"], outfits)] = outfit["tags"]
        have["outfits"] = outfits
        if not (have.get("source") or {}).get("url"):
            have["source"] = imp["source"]
        stamp(have, (["appearance"] if more else []) + (["outfits"] if added else []), now)
        return have, False
    c = {
        "id": cid or new_id(), "name": _unique(imp["name"], [x.get("name") or "" for x in data["characters"]]),
        "series": imp["series"], "tag": imp["tag"], "aliases": [], "appearance": imp["appearance"],
        "outfits": {outfit["name"]: outfit["tags"]} if outfit["tags"] else {},
        "lora": None, "image": None, "source": imp["source"], "created": now, "updated": now, "changed": {p: now for p in PARTS},
    }
    data["characters"].append(c)
    for old in data["characters"][: max(0, len(data["characters"]) - CAPS["characters"])]:  # (too many: the oldest go, as deleted)
        delete(data, old["id"], now)
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
    """Two copies of the list as one (Model Librarian moving its local data into the shared folder): by id, each part
    from the copy that changed it last; a character either deleted stays deleted."""
    out = {c.get("id"): c for c in (shared or {}).get("characters") or [] if isinstance(c, dict)}
    for c in (local or {}).get("characters") or []:
        if isinstance(c, dict):
            out[c.get("id")] = merge_parts(out[c.get("id")], c) if c.get("id") in out else c
    gone = {}
    for d in list((shared or {}).get("deleted") or []) + list((local or {}).get("deleted") or []):
        if isinstance(d, dict) and d.get("id"):
            gone[d["id"]] = max(d.get("at") or 0, (gone.get(d["id"]) or {}).get("at") or 0)
    keep = [c for i, c in out.items() if i not in gone]
    return {"v": VERSION, "characters": keep, "deleted": [{"id": i, "at": t} for i, t in sorted(gone.items(), key=lambda x: x[1])][-DELETED_KEPT:]}


def summary(c: dict) -> dict:
    """What the extension needs to know a character is there (its tag, name and outfits), and to link one to yours (aliases)."""
    return {"id": c.get("id"), "name": c.get("name"), "aliases": list(c.get("aliases") or []), "series": c.get("series"), "tag": c.get("tag"),
            "outfits": list((c.get("outfits") or {}).keys()), "has_image": bool(c.get("image"))}

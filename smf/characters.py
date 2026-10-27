"""Your characters, as the Chrome extension files them from Danbooru (and other boorus): name, preset tags, outfits.

The list is characters.json in the shared data folder, shared with Model Librarian Gallery; its format and the
merge rules are in charstore.py (the Gallery has the same file). Pictures go in characters/ beside it.
"""
from __future__ import annotations

import os
import re
import time

from . import charstore, config

config.register_merger(charstore.FILE, charstore.merge)


def _folder() -> str:
    return os.path.join(config.data_dir(), charstore.PICTURES)


def load() -> dict:
    data = config.read_json(charstore.FILE, None)
    if not isinstance(data, dict) or not isinstance(data.get("characters"), list):
        return charstore.empty()
    return {**data, "characters": [c for c in data["characters"] if isinstance(c, dict) and c.get("id")]}  # (an entry edited by hand into something else is left out)


def listing() -> list[dict]:
    return [charstore.summary(c) for c in load()["characters"]]


def for_picker() -> list[dict]:
    """Every character as the node's picker shows it, A to Z."""
    out = [{k: c.get(k) for k in ("id", "name", "series", "tag", "appearance", "outfits", "lora", "updated")} | {"has_image": bool(c.get("image"))}
           for c in load()["characters"]]
    return sorted(out, key=lambda c: str(c.get("name") or "").lower())


def get(cid: str) -> dict | None:
    return next((c for c in load()["characters"] if c.get("id") == cid), None)


def save_import(raw, picture=None) -> dict:
    """One character from the extension -> {character, created}. ValueError when it isn't one."""
    imp = charstore.clean_import(raw)
    if not imp:
        raise ValueError("That isn't a character.")
    pic = charstore.picture(picture)
    out = {}

    def change(data):
        now = time.time()
        c, created = charstore.apply_import(data, imp, now)
        if pic and not c.get("image"):  # (named after the character; written before the list names it)
            rel = charstore.picture_path(c["id"], pic[1])
            os.makedirs(_folder(), exist_ok=True)
            with open(os.path.join(config.data_dir(), *rel.split("/")), "wb") as f:
                f.write(pic[0])
            c["image"] = rel
            charstore.stamp(c, ["image"], now)
        out.update(character=dict(c), created=created)

    config.update_json(charstore.FILE, charstore.empty(), change)
    return out


def trained_words(lora: str) -> list[str]:
    """A LoRA's trigger words from its metadata (CivitAI's, Stability Matrix's or LoRA Manager's sidecars), split on commas."""
    from . import smmeta
    try:
        import folder_paths
        full = folder_paths.get_full_path("loras", lora)
    except Exception:
        full = None
    words = smmeta.merged_info(full).get("trained_words") if full and os.path.isfile(full) else None
    if isinstance(words, str):
        words = [words]
    out = []
    for w in words or []:
        for part in str(w).split(","):
            part = part.strip()
            if part and part.lower() not in {x.lower() for x in out}:
                out.append(part)
    return out[:12]


def loras() -> list[str]:
    """The LoRAs ComfyUI has, by the names its loaders take."""
    try:
        import folder_paths
        return list(folder_paths.get_filename_list("loras"))
    except Exception:
        return []


def set_lora(cid: str, name: str | None, trigger=None) -> dict:
    """Links a LoRA to the character (None: unlinks it) -> the character. Its trigger words: those given, else its
    metadata's. LookupError: no such character; ValueError: a LoRA ComfyUI doesn't have."""
    asked = name = str(name or "").strip()
    if name:  # (as ComfyUI names it: the Library writes / where ComfyUI may write \)
        want = name.replace("\\", "/").lower()
        name = next((n for n in loras() if n.replace("\\", "/").lower() == want), None)
        if not name:
            raise ValueError(f"{asked} isn't in your loras folder")
    if not isinstance(trigger, list):  # (none given: its metadata's)
        trigger = trained_words(name) if name else []
    words = []  # (as trained: underscores and all)
    for w in trigger if isinstance(trigger, list) else []:
        w = str(w).strip()[: charstore.CAPS["tag"]]
        if w and w.lower() not in {x.lower() for x in words}:
            words.append(w)
    trigger = words[:12]
    out = {}

    def change(data):
        charstore.check(data)
        c = next((x for x in data["characters"] if x.get("id") == cid), None)
        if not c:
            return
        c["lora"] = {"name": name, "trigger": trigger} if name else None
        charstore.stamp(c, ["lora"], time.time())
        out["character"] = dict(c)

    config.update_json(charstore.FILE, charstore.empty(), change)
    if "character" not in out:
        raise LookupError(cid)
    return out["character"]


def picture_file(cid: str) -> str | None:
    c = get(cid)
    rel = (c or {}).get("image")
    if not rel or not re.fullmatch(charstore.PICTURES + r"/[a-z0-9_]+\.(webp|jpg|png)", str(rel)):  # (nothing outside its folder)
        return None
    for d in dict.fromkeys([config.data_dir(), config.local_dir()]):  # (filed before the data moved to the shared folder: still here)
        p = os.path.join(d, *str(rel).split("/"))
        if os.path.isfile(p):
            return p
    return None

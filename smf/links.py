"""Models you linked by hand: "this recipe's ILFF7Tifa is my Tifa_IL_v2".

When a recipe names a model Model Librarian can't match (another name, a hash
of a kind it can't compare), you pick the file you have, or paste a link for
it. The link is remembered by name and hash in the shared data folder
(model_links.json), so the next recipe or workflow naming it resolves on its own.
"""
from __future__ import annotations

import re
import time

from . import config

FILE = "model_links.json"


def _merge(shared, local):
    out = shared or {"links": {}}
    for k, v in (local.get("links") or {}).items():
        if (v or {}).get("updated", 0) > ((out["links"].get(k) or {}).get("updated", 0)):
            out["links"][k] = v
    return out


config.register_merger(FILE, _merge)


def norm(name: str | None) -> str:
    """Name without folders, extension, case or punctuation."""
    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"\.(safetensors|sft|ckpt|pt|pth|bin|gguf)$", "", base, flags=re.I)
    return re.sub(r"[^a-z0-9]", "", base.lower())


def _keys(kind: str, names, hashes) -> list[str]:
    out = [f"{kind}:name:{n}" for n in {norm(x) for x in names if x} if len(n) >= 2]
    out += [f"{kind}:hash:{h}" for h in {str(x).lower() for x in hashes if x} if len(h) >= 8]
    return out


def lookup(kind: str, names=(), hashes=()) -> dict | None:
    """-> {file, folder, ...} for a linked model, or None."""
    links = (config.read_json(FILE, None) or {}).get("links") or {}
    for k in _keys(kind, names, hashes):
        if links.get(k):
            return links[k]
    return None


def link(kind: str, names, hashes, file: str, folder: str | None = None, url: str | None = None) -> dict:
    rec = {"file": file, "folder": folder, "url": url, "updated": time.time()}

    def mut(d):
        for k in _keys(kind, names, hashes):
            d.setdefault("links", {})[k] = rec

    config.update_json(FILE, {"links": {}}, mut)
    return rec


def unlink(kind: str, names=(), hashes=()) -> int:
    gone = []

    def mut(d):
        for k in _keys(kind, names, hashes):
            if d.setdefault("links", {}).pop(k, None):
                gone.append(k)

    config.update_json(FILE, {"links": {}}, mut)
    return len(gone)


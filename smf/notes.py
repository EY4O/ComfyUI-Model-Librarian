"""Your own notes on models: a rating (0-5), a note and your own tags.

Stored in the shared data folder (notes.json), so every ComfyUI using the
Stability Matrix folders sees them. Keyed by model type and file name, so they
follow a model when Organize or the storage tiers move it.
"""
from __future__ import annotations

import time

from . import config

FILE = "notes.json"
MAX_NOTE = 4000
MAX_TAGS = 30


def key(section: str, name: str) -> str:
    return f"{section}:{name.replace(chr(92), '/').rsplit('/', 1)[-1].lower()}"


def _merge(shared, local):
    out = shared or {"models": {}}
    for k, v in (local.get("models") or {}).items():
        if (v or {}).get("updated", 0) > ((out["models"].get(k) or {}).get("updated", 0)):
            out["models"][k] = v
    return out


config.register_merger(FILE, _merge)


def load() -> dict:
    return (config.read_json(FILE, None) or {}).get("models") or {}


def clean(patch: dict, current: dict | None = None) -> dict:
    """Validated fields from a patch, merged onto the current notes."""
    out = dict(current or {})
    if "rating" in patch:
        try:
            out["rating"] = max(0, min(5, int(patch["rating"] or 0)))
        except (TypeError, ValueError):
            raise ValueError("rating must be 0-5")
    if "note" in patch:
        out["note"] = str(patch["note"] or "")[:MAX_NOTE]
    if "tags" in patch:
        tags = patch["tags"] if isinstance(patch["tags"], list) else str(patch["tags"] or "").split(",")
        seen, kept = set(), []
        for t in tags:
            t = str(t).strip()[:40]
            if t and t.lower() not in seen:
                seen.add(t.lower())
                kept.append(t)
        out["tags"] = kept[:MAX_TAGS]
    return out


def save(section: str, name: str, patch: dict) -> dict:
    k = key(section, name)
    result = {}

    def mut(d):
        models = d.setdefault("models", {})
        n = clean(patch, models.get(k))
        n["updated"] = time.time()
        if not n.get("rating") and not n.get("note") and not n.get("tags"):
            models.pop(k, None)  # nothing left: don't keep an empty record
        else:
            models[k] = n
        result.update(n)
    config.update_json(FILE, {"models": {}}, mut)
    return {k2: v for k2, v in result.items() if k2 != "updated"}


def annotate(entries: list[dict]) -> list[dict]:
    """Adds `notes` ({rating, note, tags}) to library entries that have any."""
    all_notes = load()
    for e in entries:
        n = all_notes.get(key(e["section"], e["name"]))
        if n:
            e["notes"] = {k: v for k, v in n.items() if k != "updated"}
        else:
            e.pop("notes", None)
    return entries

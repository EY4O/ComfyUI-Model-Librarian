"""Personal source registry: remembers where every model came from.

Keyed by lower-cased file name (and indexed by SHA256), so a renamed or
generically named file resolves instantly the next time a workflow needs it.
"""
from __future__ import annotations

import time

from . import config

_FILE = "registry.json"


def _empty() -> dict:
    return {"version": 1, "entries": {}}


def _load() -> dict:
    return config.read_json(_FILE, _empty())


def _merge(shared: dict | None, local: dict) -> dict:
    out = shared or _empty()
    for k, e in (local.get("entries") or {}).items():
        cur = out["entries"].get(k)
        if not cur or (e.get("updated") or 0) > (cur.get("updated") or 0):
            out["entries"][k] = e
    return out


config.register_merger(_FILE, _merge)


def all_entries() -> list[dict]:
    return sorted(_load()["entries"].values(), key=lambda e: e.get("added", 0), reverse=True)


def lookup(filename: str) -> dict | None:
    base = filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return _load()["entries"].get(base)


def lookup_hash(sha256: str) -> dict | None:
    sha256 = (sha256 or "").lower()
    if not sha256:
        return None
    for e in _load()["entries"].values():
        if (e.get("sha256") or "").lower() == sha256:
            return e
    return None


def remember(filename: str, url: str, *, source: str, sha256: str | None = None,
             size: int | None = None, folder: str | None = None, page_url: str | None = None,
             title: str | None = None) -> dict:
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    out = {}

    def mut(data):
        prev = data["entries"].get(base.lower(), {})
        out.update({
            "filename": base,
            "url": url,
            "source": source,
            "sha256": (sha256 or prev.get("sha256") or "").lower() or None,
            "size": size or prev.get("size"),
            "folder": folder or prev.get("folder"),
            "page_url": page_url or prev.get("page_url"),
            "title": title or prev.get("title"),
            "added": prev.get("added") or time.time(),
            "updated": time.time(),
        })
        data["entries"][base.lower()] = out

    config.update_json(_FILE, _empty(), mut)
    return out


def forget(filename: str) -> bool:
    removed = []
    config.update_json(_FILE, _empty(),
                       lambda data: removed.append(data["entries"].pop(filename.lower(), None)))
    return removed[0] is not None

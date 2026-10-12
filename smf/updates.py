"""Update alerts: newer CivitAI versions of the models you have.

Every model with CivitAI metadata (a model id and version id, from Stability
Matrix's .cm-info.json or LoRA Manager's .metadata.json) is checked against
CivitAI's model page, once per model id, cached for a day in the shared data
folder (updates.json). An update is a newer published version for the same
base model, so an SDXL LoRA isn't flagged because a Flux port was posted.
Versions you already have, or dismissed, aren't shown.
"""
from __future__ import annotations

import asyncio
import re
import time

from . import config, library, net

CACHE = "updates.json"
TTL = 24 * 3600
POLITE = 0.3  # seconds between CivitAI calls
_EMPTY = {"models": {}, "dismissed": {}, "last_check": 0}


def _merge(shared, local):
    out = shared or {"models": {}, "dismissed": {}, "last_check": 0}
    for mid, rec in (local.get("models") or {}).items():
        if (rec or {}).get("checked", 0) > ((out["models"].get(mid) or {}).get("checked", 0)):
            out["models"][mid] = rec
    out["dismissed"] = {**(local.get("dismissed") or {}), **(out.get("dismissed") or {})}
    out["last_check"] = max(out.get("last_check", 0), local.get("last_check", 0))
    return out


config.register_merger(CACHE, _merge)


def load() -> dict:
    d = config.read_json(CACHE, None) or {}
    return {**_EMPTY, **d}


def versions_of(model: dict) -> list[dict]:
    """Published versions with files, newest first (CivitAI's own order)."""
    out = []
    for v in (model or {}).get("modelVersions") or []:
        if v.get("status") not in (None, "Published") or not v.get("files"):
            continue
        out.append({"id": v.get("id"), "name": v.get("name") or "", "base_model": v.get("baseModel") or "",
                    "published": v.get("publishedAt") or v.get("createdAt")})
    return out


# Words in a version name that mark a variant rather than a newer release: authors
# often post high/low-noise halves, precisions or step counts as separate versions.
_MARKS = {"high", "low", "hn", "ln", "h", "l", "hi", "lo", "fp8", "fp16", "fp32", "bf16", "nf4", "int8",
          "i2v", "t2v", "ti2v", "gguf", "lite", "turbo", "distilled", "pos", "positive", "neg", "negative"}
_MARK_RE = re.compile(r"\d+steps?|q\d+(?:_?k(?:_?[msl])?)?|\d+b")


def variant(name: str) -> frozenset:
    toks = re.findall(r"[a-z0-9]+", (name or "").lower())
    return frozenset(t for t in toks if t in _MARKS or _MARK_RE.fullmatch(t))


def update_for(e: dict, cache: dict, have: set) -> dict | None:
    """The newest version of the same variant and base model that's newer than
    this file's, or None (also when you already have a newer one of it)."""
    mid, vid = e.get("model_id"), e.get("version_id")
    if not mid or not vid:
        return None
    rec = (cache.get("models") or {}).get(str(mid))
    if not rec or not rec.get("versions"):
        return None
    vs = rec["versions"]
    ids = [v["id"] for v in vs]
    try:
        idx = ids.index(int(vid))
    except (ValueError, TypeError):
        return None  # this version isn't listed any more: can't tell what's newer
    base, kind = vs[idx]["base_model"], variant(vs[idx]["name"])
    newer = [v for v in vs[:idx] if v["base_model"] == base and variant(v["name"]) == kind]
    if not newer or any(v["id"] in have for v in newer):
        return None  # nothing newer, or you keep an older copy next to a newer one you have
    pick = newer[0]
    if str(pick["id"]) == str((cache.get("dismissed") or {}).get(str(mid))):
        return None
    return {**pick, "model_id": int(mid), "newer_count": len(newer), "model_name": rec.get("name") or "",
            "page_url": f"https://civitai.com/models/{mid}?modelVersionId={pick['id']}"}


def annotate(entries: list[dict]) -> list[dict]:
    """Adds `update` to library entries that have a newer version."""
    cache = load()
    have = {int(e["version_id"]) for e in entries if str(e.get("version_id") or "").isdigit()}
    for e in entries:
        u = update_for(e, cache, have)
        if u:
            e["update"] = u
        else:
            e.pop("update", None)
    return entries


def dismiss(model_id: int, version_id: int) -> None:
    config.update_json(CACHE, dict(_EMPTY), lambda d: d.setdefault("dismissed", {}).__setitem__(str(int(model_id)), int(version_id)))


# ------------------------------------------------------------ check job
_job: dict = {"status": "idle"}


def job_status() -> dict:
    out = {k: v for k, v in _job.items() if not k.startswith("_")}
    out["last_check"] = load().get("last_check", 0)
    out["stale"] = time.time() - out["last_check"] > TTL
    return out


async def check(force: bool = False, sections: list[str] | None = None) -> dict:
    if _job.get("status") == "running":
        return job_status()
    _job.clear()
    _job.update(status="running", done=0, total=0, updates=0, errors=0, current=None, started=time.time())
    _job["_task"] = asyncio.ensure_future(_check(force, sections or list(library.SECTIONS)))
    return job_status()


def cancel() -> None:
    t = _job.get("_task")
    if t and not t.done():
        t.cancel()


async def _check(force: bool, sections: list[str]):
    try:  # only reads files and asks CivitAI, so it doesn't take the move lock
        entries = []
        for s in sections:
            entries += await asyncio.to_thread(library.build, s)
        cache = load()
        now = time.time()
        mids = sorted({int(e["model_id"]) for e in entries if str(e.get("model_id") or "").isdigit() and e.get("version_id")})
        todo = [m for m in mids if force or now - ((cache["models"].get(str(m)) or {}).get("checked", 0)) > TTL]
        _job["total"] = len(todo)
        for mid in todo:
            _job["current"] = mid
            try:
                model = await net.get_json(f"{net.CIVITAI_BASE}/api/v1/models/{mid}")
                rec = {"checked": time.time(), "name": (model or {}).get("name") or "", "versions": versions_of(model)}
                if model is None:
                    rec["gone"] = True  # 404: removed from CivitAI
                config.update_json(CACHE, dict(_EMPTY), lambda d, m=mid, r=rec: d.setdefault("models", {}).__setitem__(str(m), r))
            except asyncio.CancelledError:
                raise
            except Exception as ex:
                _job["errors"] += 1
                _job["error"] = str(ex)
            _job["done"] += 1
            await asyncio.sleep(POLITE)
        config.update_json(CACHE, dict(_EMPTY), lambda d: d.__setitem__("last_check", time.time()))
        _job["updates"] = sum(1 for e in annotate(entries) if e.get("update"))
        _job["status"] = "done"
    except asyncio.CancelledError:
        _job["status"] = "cancelled"
    except Exception as ex:
        _job["status"], _job["error"] = "error", str(ex)
    finally:
        _job["current"] = None

"""Turn a LoRA Manager recipe analysis into downloads for SM's shared folders.

LoRA Manager reads the image (/api/lm/recipes/analyze-image) and stores the
recipe. Its own import only downloads LoRAs, into a folder you pick; this
plans every resource the image used (LoRAs and the checkpoint), finds the exact
file on CivitAI by version id or hash, and files it in the base-model folder
the organizer would choose.
"""
from __future__ import annotations

import asyncio
import os

from . import basemodel, hashing, organize, paths, sources

_LOOKUPS = asyncio.Semaphore(4)  # be polite to the CivitAI API


def _filename(name: str) -> str:
    return name if paths.is_model_value(name) else name + ".safetensors"


def _local(entry: dict, kind: str, inv: paths.Inventory) -> tuple[str | None, str | None]:
    """-> (what we found, how) for a resource that's already on disk."""
    if entry.get("existsLocally") or entry.get("inLibrary"):
        return os.path.basename(entry.get("localPath") or "") or entry.get("file_name") or "yes", "LoRA Manager"
    p = hashing.find_by_sha(entry.get("hash") or "")
    if p:
        return os.path.basename(p), "hash"
    name = (entry.get("file_name") or "").strip()
    if name:
        if kind == "lora":
            state, _, n = inv.find_lm(name)
            if state == "present":
                return n, "file name"
        else:
            for folder in ("checkpoints", "diffusion_models"):
                state, _, n, _ = inv.find(_filename(name), folder)
                if state != "missing":
                    return n, "file name"
    return None, None


async def _candidate(entry: dict, kind: str) -> tuple[dict | None, str | None]:
    vid = entry.get("id") or entry.get("modelVersionId")
    h = (entry.get("hash") or "").lower()
    note = None
    try:
        async with _LOOKUPS:
            if vid:
                c = await sources.civitai_by_version(vid, h)
                if c:
                    return c, None
            if h:
                c = await sources.civitai_by_hash(h)
                if c:
                    return c, None
    except Exception as ex:  # rate limit, network: still try the other routes
        note = f"CivitAI lookup failed: {ex}"
    url = entry.get("downloadUrl") or ""
    name = (entry.get("file_name") or "").strip()
    if url.startswith("https://"):
        return sources._cand("civitai", url, _filename(name or "model"), confidence="medium",
                             title=entry.get("name")), note
    if name:
        cands = await sources.resolve(_filename(name), "loras" if kind == "lora" else "checkpoints")
        if cands:
            return cands[0], note
    return None, note


async def _plan_one(entry: dict, kind: str, inv: paths.Inventory) -> dict:
    item = {
        "kind": kind, "name": entry.get("name") or entry.get("file_name") or "?",
        "version": entry.get("version") or "", "weight": entry.get("weight"),
        "base_model": entry.get("baseModel") or "", "hash": entry.get("hash") or None,
        "status": "missing", "local": None, "matched_by": None, "download": None, "note": None,
        "page_url": None,
    }
    if entry.get("modelId"):
        item["page_url"] = f"https://civitai.com/models/{entry['modelId']}" + (
            f"?modelVersionId={entry['id']}" if entry.get("id") else "")
    local, how = _local(entry, kind, inv)
    if local:
        item.update(status="present", local=local, matched_by=how)
        return item
    c, note = await _candidate(entry, kind)
    item["note"] = note
    if not c or not c.get("url"):
        item["status"] = "unavailable"
        item["note"] = note or ("Removed from CivitAI" if entry.get("isDeleted") else "No download source found")
        return item
    folder = "loras" if kind == "lora" else (c.get("folder") or "checkpoints")
    if folder not in ("checkpoints", "diffusion_models", "loras"):
        folder = "loras" if kind == "lora" else "checkpoints"
    base = (c.get("meta") or {}).get("baseModel") or item["base_model"]
    fam = basemodel.from_text(base) if base else None
    fname = os.path.basename((c.get("filename") or _filename(item["name"])).replace("\\", "/"))
    rel = f"{organize.folder_for(fam)}/{fname}" if fam else fname
    try:
        dest, shared = paths.dest_path(folder, rel)
    except ValueError as ex:
        item.update(status="unavailable", note=str(ex))
        return item
    if os.path.exists(dest):
        item.update(status="present", local=rel, matched_by="already downloaded")
        return item
    item["base_model"] = base
    item["page_url"] = item["page_url"] or c.get("page_url")
    if entry.get("isEarlyAccess"):
        item["note"] = "Early access on CivitAI — the download may need a purchase"
    item["download"] = {
        "url": c["url"], "folder": folder, "rel": rel, "sha256": c.get("sha256"), "size": c.get("size"),
        "source": c.get("source") or "civitai", "page_url": c.get("page_url"), "title": c.get("title"),
        "meta": c.get("meta"), "confidence": c.get("confidence"), "dest": dest, "shared": shared,
    }
    return item


async def plan(loras: list[dict], checkpoint: dict | None) -> dict:
    inv = await asyncio.to_thread(paths.Inventory)
    jobs = [_plan_one(e, "lora", inv) for e in loras if isinstance(e, dict)]
    if isinstance(checkpoint, dict) and (checkpoint.get("name") or checkpoint.get("hash")
                                         or checkpoint.get("id") or checkpoint.get("file_name")):
        jobs.insert(0, _plan_one(checkpoint, "checkpoint", inv))
    return {"items": list(await asyncio.gather(*jobs))}

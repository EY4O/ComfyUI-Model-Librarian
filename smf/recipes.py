"""Recipes: read an image (or a CivitAI link), plan every model it used, and
download what's missing into SM's shared folders — no LoRA Manager needed.

The recipe itself comes from `recipe_parse` (shared recipe format). Each
model/LoRA/VAE is matched against what's installed (hash, then file name) and
otherwise found on CivitAI by version id or hash — the exact file — falling
back to the normal name search. Downloads are filed in the base-model folder
the organizer would choose.
"""
from __future__ import annotations

import asyncio
import os
import re
from urllib.parse import urlparse

from . import basemodel, hashing, library, net, organize, paths, recipe_parse, recipe_store, sources

_LOOKUPS = asyncio.Semaphore(4)  # be polite to the CivitAI API
MAX_IMAGE = 40 * 1024 * 1024
KIND_FOLDERS = {"lora": ("loras",), "checkpoint": ("checkpoints", "diffusion_models"), "vae": ("vae",)}


def _filename(name: str) -> str:
    return name if paths.is_model_value(name) else name + ".safetensors"


def _comfy_name(path: str, kind: str) -> str | None:
    """The name ComfyUI lists for a file (path relative to its model folder)."""
    rp = os.path.normcase(os.path.realpath(path))
    for section in KIND_FOLDERS.get(kind, ()):
        for root in library.roots(section):
            r = os.path.normcase(os.path.realpath(root)) + os.sep
            if rp.startswith(r):
                return os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    return None


def _local(entry: dict, kind: str, inv: paths.Inventory) -> tuple[str | None, str | None, str | None]:
    """-> (what we found, how, ComfyUI name) for a resource that's already on disk."""
    if entry.get("existsLocally") or entry.get("inLibrary"):
        lp = entry.get("localPath") or ""
        return os.path.basename(lp) or entry.get("file_name") or "yes", "LoRA Manager", (_comfy_name(lp, kind) if lp else None)
    p = hashing.find_by_sha(entry.get("hash") or "")
    if p:
        return os.path.basename(p), "hash", _comfy_name(p, kind)
    name = (entry.get("file_name") or "").strip()
    if name:
        if kind == "lora":
            state, _, n = inv.find_lm(name)
            if state == "present":
                return n, "file name", n
        else:
            for folder in KIND_FOLDERS.get(kind, ()):
                state, _, n, _ = inv.find(_filename(name), folder)
                if state != "missing":
                    return n, "file name", n
    return None, None, None


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
        cands = await sources.resolve(_filename(name), KIND_FOLDERS.get(kind, ("checkpoints",))[0])
        if cands:
            return cands[0], note
    return None, note


async def _plan_one(entry: dict, kind: str, inv: paths.Inventory) -> dict:
    item = {
        "kind": kind, "name": entry.get("name") or entry.get("file_name") or "?",
        "file": entry.get("file_name"), "version": entry.get("version") or "",
        "weight": entry.get("weight"), "clip_weight": entry.get("clip_weight"),
        "base_model": entry.get("baseModel") or "", "hash": entry.get("hash") or None,
        "status": "missing", "local": None, "comfy_name": None, "matched_by": None, "download": None, "note": None,
        "page_url": None,
    }
    if entry.get("modelId"):
        item["page_url"] = f"https://civitai.com/models/{entry['modelId']}" + (
            f"?modelVersionId={entry['id']}" if entry.get("id") else "")
    if entry.get("downloadable") is False:
        item.update(status="unavailable", note="Not a downloadable model (e.g. NovelAI's own models)")
        return item
    local, how, comfy = _local(entry, kind, inv)
    if local:
        item.update(status="present", local=local, matched_by=how, comfy_name=comfy)
        return item
    c, note = await _candidate(entry, kind)
    item["note"] = note
    if not c or not c.get("url"):
        item["status"] = "unavailable"
        item["note"] = note or ("Removed from CivitAI" if entry.get("isDeleted") else "No download source found")
        return item
    folder = {"lora": "loras", "vae": "vae"}.get(kind) or (c.get("folder") or "checkpoints")
    if folder not in ("checkpoints", "diffusion_models", "loras", "vae"):
        folder = KIND_FOLDERS.get(kind, ("checkpoints",))[0]
    base = (c.get("meta") or {}).get("baseModel") or item["base_model"]
    fam = basemodel.from_text(base) if base else None
    fname = os.path.basename((c.get("filename") or _filename(item["name"])).replace("\\", "/"))
    rel = f"{organize.folder_for(fam)}/{fname}" if fam and kind != "vae" else fname
    try:
        dest, shared = paths.dest_path(folder, rel)
    except ValueError as ex:
        item.update(status="unavailable", note=str(ex))
        return item
    if os.path.exists(dest):
        item.update(status="present", local=rel, matched_by="already downloaded", comfy_name=rel.replace("/", os.sep))
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


def _entry(ref: dict, extra: dict | None = None) -> dict:
    """Shared-format model reference -> planner entry."""
    e = {"name": ref.get("display_name") or ref.get("name"), "file_name": recipe_parse._stem(ref.get("file")) if ref.get("file") else None,
         "hash": ref.get("hash"), "id": ref.get("civitai_version_id"), "modelId": ref.get("civitai_model_id"),
         "version": ref.get("version"), "downloadable": ref.get("downloadable")}
    if ref.get("file") and paths.is_model_value(ref["file"]):
        e["file_name"] = os.path.basename(str(ref["file"]).replace("\\", "/"))
    e.update(extra or {})
    return e


async def plan_recipe(recipe: dict) -> dict:
    inv = await asyncio.to_thread(paths.Inventory)
    jobs = []
    if recipe.get("model") and (recipe["model"].get("file") or recipe["model"].get("hash")
                                or recipe["model"].get("civitai_version_id") or recipe["model"].get("name")):
        jobs.append(_plan_one(_entry(recipe["model"], {"baseModel": recipe.get("base_model")}), "checkpoint", inv))
    for l in recipe.get("loras") or []:
        jobs.append(_plan_one(_entry(l, {"weight": l.get("weight"), "clip_weight": l.get("clip_weight")}), "lora", inv))
    if recipe.get("vae") and (recipe["vae"].get("file") or recipe["vae"].get("hash")):
        jobs.append(_plan_one(_entry(recipe["vae"]), "vae", inv))
    return {"items": list(await asyncio.gather(*jobs))}


async def plan(loras: list[dict], checkpoint: dict | None) -> dict:
    """Legacy entry point: LoRA Manager analysis shapes."""
    inv = await asyncio.to_thread(paths.Inventory)
    jobs = [_plan_one(e, "lora", inv) for e in loras if isinstance(e, dict)]
    if isinstance(checkpoint, dict) and (checkpoint.get("name") or checkpoint.get("hash")
                                         or checkpoint.get("id") or checkpoint.get("file_name")):
        jobs.insert(0, _plan_one(checkpoint, "checkpoint", inv))
    return {"items": list(await asyncio.gather(*jobs))}


# ---------------------------------------------------------------- analyze (image / link)
_CIVITAI_HOSTS = ("civitai.com", "civitai.green", "civitai.red")


def _civitai_api_base(host: str) -> str:
    # The configured base (tests point it elsewhere) unless the link names another Civitai host
    if host in _CIVITAI_HOSTS and host != urlparse(net.CIVITAI_BASE).hostname and urlparse(net.CIVITAI_BASE).hostname in _CIVITAI_HOSTS:
        return f"https://{host}"
    return net.CIVITAI_BASE


async def _civitai_images(base: str, query: str) -> list[dict]:
    items = []
    for extra in ("", "&nsfw=X"):  # higher content levels only come back when asked for
        d = await net.get_json(f"{base}/api/v1/images?{query}&withMeta=true{extra}")
        items = (d or {}).get("items") or []
        if items:
            break
    return items


async def _fetch_image(url: str) -> bytes | None:
    try:
        async with net.session().get(url) as r:
            if r.status != 200 or not r.headers.get("Content-Type", "").startswith("image"):
                return None
            data = await r.content.read(MAX_IMAGE + 1)
            return data if len(data) <= MAX_IMAGE else None
    except Exception:
        return None


async def analyze_image(data: bytes, filename: str | None = None) -> dict:
    rec = await asyncio.to_thread(recipe_parse.from_image, data, filename)
    thumb = await asyncio.to_thread(recipe_store.make_thumbnail, data)
    return {"recipe": rec, "thumb": recipe_store.thumb_data_url(thumb), **(await plan_recipe(rec))}


def _public_https(u) -> bool:
    """Only fetch public https URLs (the server fetches them, so no LAN/loopback)."""
    import ipaddress
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host or host == "localhost" or host.endswith((".local", ".localhost", ".internal")):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)
    except ValueError:
        return True  # a hostname


async def analyze_url(url: str) -> dict:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if not _public_https(u):
        raise recipe_parse.NoMetadata("Paste a public https:// link (an image, or a CivitAI image/post page).")
    if host in _CIVITAI_HOSTS:
        base = _civitai_api_base(host)
        m = re.match(r"^/images/(\d+)", u.path)
        if m:
            items = await _civitai_images(base, f"imageId={m.group(1)}")
            if not items:
                raise recipe_parse.NoMetadata("CivitAI has no public image with that id (or it needs your API key).")
            item = items[0]
            rec = recipe_parse.from_civitai_item(item, f"https://{host}/images/{item.get('id')}")
            if not any((rec.get("model"), rec.get("loras"), rec["prompt"]["positive"])):
                raise recipe_parse.NoMetadata("CivitAI has no generation data for this image.")
            img = await _fetch_image(re.sub(r"/(original=true|width=\d+)/", "/width=512/", item.get("url") or "")) if item.get("url") else None
            thumb = await asyncio.to_thread(recipe_store.make_thumbnail, img) if img else None
            return {"recipe": rec, "thumb": recipe_store.thumb_data_url(thumb), **(await plan_recipe(rec))}
        m = re.match(r"^/posts/(\d+)", u.path)
        if m:
            items = await _civitai_images(base, f"postId={m.group(1)}&limit=50")
            if not items:
                raise recipe_parse.NoMetadata("CivitAI has no public images in that post.")
            return {"choices": [{"url": f"https://{host}/images/{i['id']}", "thumb": re.sub(r"/(original=true|width=\d+)/", "/width=256/", i.get("url") or ""),
                                 "has_meta": bool(i.get("meta"))} for i in items if i.get("id")]}
        raise recipe_parse.NoMetadata("Paste a CivitAI image (/images/…) or post (/posts/…) link.")
    data = await _fetch_image(url)
    if not data:
        raise recipe_parse.NoMetadata("That link isn't an image file. Paste a direct image link or a CivitAI image/post link.")
    return await analyze_image(data, os.path.basename(u.path) or None)

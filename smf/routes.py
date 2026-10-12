"""HTTP API (mounted on ComfyUI's PromptServer under /sm-fetcher and /api/sm-fetcher)."""
from __future__ import annotations

import asyncio
import functools
import logging
import mimetypes
import os
import re
import time

from aiohttp import web

from . import (bridge, busy, config, downloader, hashing, infer, library, organize, paths, recipes, registry, smmeta, sources,
               swaps, tiering, usage, workflows)

P = "/sm-fetcher"


def _err(msg: str, status: int = 400):
    return web.json_response({"error": msg}, status=status)


def _busy_ok(fn):
    """Another library operation is running -> 409 with a message the UI shows."""
    @functools.wraps(fn)
    async def wrapper(request):
        try:
            return await fn(request)
        except busy.Busy as ex:
            return _err(str(ex), 409)
    return wrapper


async def _body(request) -> dict:
    try:
        return await request.json()
    except Exception:
        return {}


def _node_installed(name: str) -> bool:
    try:
        import nodes
        return name in nodes.NODE_CLASS_MAPPINGS
    except Exception:
        return False


def _local_by_sha(folder: str | None, inv: paths.Inventory) -> dict:
    """sha256 -> ComfyUI name, for files of this folder type that are already hashed
    (names come from ComfyUI's own list, so repointed widgets validate)."""
    out = {}
    if not folder:
        return out
    for f in inv._folders_for(folder):
        for n in inv.lists[f]:
            fp = inv.full_path(f, n)
            sha = hashing.cached(fp) if fp else None
            if sha:
                out.setdefault(sha.lower(), n)
    return out



def _lm_group(name: str, inv: paths.Inventory) -> dict:
    """Scan result for a LoRA Manager reference (a LoRA name without extension)."""
    raw = paths.strip_lm_ext(name.replace("\\", "/"))
    name = paths.strip_lm_ext(paths.norm_rel(name))
    g = {"value": name, "folder": "loras", "how": "lora-manager", "lm": True, "refs": [], "node_types": [],
         "embedded": None, "size": None, "dest": None, "shared": None, "too_big": False, "hint": None,
         "found_as": None, "found_folder": None,
         "search_name": name.rsplit("/", 1)[-1] + ".safetensors"}
    if raw.startswith("/") or re.match(r"^[a-zA-Z]:", raw):
        # LoRA Manager accepts raw absolute paths that exist on disk
        if any(os.path.isfile(raw + e) for e in ("",) + paths.LM_EXTS):
            g["status"] = "present"
            return g
        name = name.rsplit("/", 1)[-1]
    state, ffolder, fname = inv.find_lm(name)
    g.update(status=state, found_as=fname, found_folder=ffolder)
    if state == "present":
        fp = inv.full_path(ffolder, fname)
        if fp and os.path.exists(fp):
            g["size"] = os.path.getsize(fp)
        return g
    try:
        g["dest"], g["shared"] = paths.dest_path("loras", name + ".safetensors")
    except ValueError as ex:
        g["status"], g["error"] = "invalid", str(ex)
    return g


def register(routes: web.RouteTableDef) -> None:
    # every data module is imported above, so all their mergers are registered
    try:
        merged = config.migrate_to_shared()
        if merged:
            logging.info("[Model Librarian] merged %s into shared data folder %s", ", ".join(merged),
                         config.data_dir())
    except Exception:
        logging.exception("[Model Librarian] couldn't merge local data into the shared folder")
    try:
        tiering.install()  # archive folders visible to ComfyUI + usage tracking hook
    except Exception:
        logging.exception("[Model Librarian] storage tiers unavailable")

    @routes.get(P + "/status")
    async def status(request):
        info = paths.sm_info()
        dests = {}
        for f in ("checkpoints", "loras", "diffusion_models", "text_encoders", "vae", "controlnet",
                  "upscale_models", "embeddings", "clip_vision"):
            d, shared = paths.dest_dir(f)
            dests[f] = {"path": d, "shared": shared}
        return web.json_response({
            "config": config.public(), "sm": {"mode": info["mode"], "models_root": info["models_root"]},
            "destinations": dests, "gguf_installed": _node_installed("UnetLoaderGGUF"),
            "lm_installed": _node_installed("Lora Loader (LoraManager)"),
            "families": organize.basemodel.FAMILIES, "sections": library.SECTIONS, "sep": os.sep,
        })

    @routes.post(P + "/config")
    async def set_config(request):
        try:
            cfg = config.save(await _body(request))
        except ValueError as ex:
            return _err(str(ex))
        tiering.register_folders()
        return web.json_response({"config": config.public(cfg)})

    # ------------------------------------------------------------- scan
    @routes.post(P + "/scan")
    async def scan(request):
        body = await _body(request)
        inv = await asyncio.to_thread(paths.Inventory)
        budget = swaps.budget_bytes()
        groups: dict[tuple, dict] = {}
        for ref in body.get("refs", []):
            val = ref.get("value")
            if ref.get("lm"):
                if not isinstance(val, str) or not val.strip():
                    continue
                key = (paths.strip_lm_ext(paths.norm_rel(val)).lower(), "loras", "lm")
                g = groups.get(key)
                if g is None:
                    g = groups[key] = _lm_group(val, inv)
                g["refs"].append(ref.get("key"))
                if ref.get("node_type") not in g["node_types"]:
                    g["node_types"].append(ref.get("node_type"))
                continue
            if not paths.is_model_value(val):
                continue
            emb = ref.get("embedded") or None
            folder, how = infer.infer_folder(ref.get("node_type", ""), ref.get("widget", ""),
                                             (emb or {}).get("directory"), inv)
            key = (paths.norm_rel(val).lower(), folder)
            g = groups.get(key)
            if g is None:
                state, ffolder, fname, hint = inv.find(val, folder)
                if state == "missing" and "%" in val:
                    # URL-encoded names from browser downloads ("My%20Lora.safetensors")
                    from urllib.parse import unquote
                    s2, f2, n2, _ = inv.find(unquote(val), folder)
                    if s2 != "missing":
                        state, ffolder, fname = "elsewhere", f2, n2
                g = {"value": val, "folder": folder, "how": how, "status": state,
                     "found_as": fname, "found_folder": ffolder, "refs": [], "node_types": [],
                     "embedded": emb, "size": None, "dest": None, "shared": None, "too_big": False,
                     "hint": hint}
                if state != "missing":
                    fp = inv.full_path(ffolder, fname)
                    if fp and os.path.exists(fp):
                        g["size"] = os.path.getsize(fp)
                try:
                    paths.safe_rel_path(val)
                except ValueError as ex:
                    g["status"], g["error"] = "invalid", str(ex)
                if folder and g["status"] != "invalid":
                    try:
                        d, shared = paths.dest_path(folder, val)
                        g["dest"], g["shared"] = d, shared
                    except ValueError as ex:
                        g["status"], g["error"] = "invalid", str(ex)
                groups[key] = g
            g["refs"].append(ref.get("key"))
            if ref.get("node_type") not in g["node_types"]:
                g["node_types"].append(ref.get("node_type"))
            if emb and not g["embedded"]:
                g["embedded"] = emb
        items = list(groups.values())
        for g in items:
            g["big_kind"] = swaps.too_big(g.get("found_as") or g["value"], g["size"], g["node_types"], budget)
            g["too_big"] = bool(g["big_kind"])
        order = {"missing": 0, "invalid": 1, "elsewhere": 2, "present": 3}
        items.sort(key=lambda g: (order.get(g["status"], 9), g["value"].lower()))
        return web.json_response({"items": items, "budget": budget,
                                  "sm_mode": paths.sm_info()["mode"]})

    @routes.post(P + "/resolve")
    async def resolve(request):
        b = await _body(request)
        if not b.get("value"):
            return _err("value required")
        cands = await sources.resolve(b["value"], b.get("folder"), b.get("embedded"))
        # Flag candidates you already have (same file name or same SHA256), so the UI
        # offers "Use local file" instead of downloading a second copy.
        inv = await asyncio.to_thread(paths.Inventory)
        by_sha = await asyncio.to_thread(_local_by_sha, b.get("folder"), inv)
        for c in cands:
            hit = None
            if c.get("sha256"):
                hit = by_sha.get(c["sha256"].lower())
            if not hit and c.get("filename"):
                st, _f, name, _h = inv.find(c["filename"], b.get("folder"))
                if st in ("present", "elsewhere"):
                    hit = name
            c["local"] = hit
        return web.json_response({"candidates": cands})

    # ------------------------------------------------------------- storage tiers
    @routes.get(P + "/tiering/plan")
    async def tier_plan(request):
        return web.json_response(await asyncio.to_thread(tiering.plan))

    @routes.post(P + "/tiering/archive")
    @_busy_ok
    async def tier_archive(request):
        b = await _body(request)
        return web.json_response(await tiering.start_job("archive", [i for i in b.get("ids", []) if isinstance(i, str)]))

    @routes.post(P + "/tiering/restore")
    @_busy_ok
    async def tier_restore(request):
        b = await _body(request)
        return web.json_response(await tiering.start_job("restore", [i for i in b.get("ids", []) if isinstance(i, str)]))

    @routes.get(P + "/tiering/job")
    async def tier_job(request):
        return web.json_response(tiering.job_status())

    @routes.get(P + "/tiering/events")
    async def tier_events(request):
        try:
            since = float(request.query.get("since", "0"))
        except ValueError:
            since = 0
        return web.json_response({"events": tiering.events(since), "now": time.time()})

    @routes.get(P + "/tiering/lm-paths")
    async def tier_lm_paths(request):
        return web.json_response({"extra_folder_paths": tiering.lm_extra_paths()})

    @routes.post(P + "/resolve-url")
    async def resolve_url(request):
        b = await _body(request)
        url = str(b.get("url") or "").strip()
        if not url.startswith("https://"):
            return _err("Paste an https:// link")
        try:
            return web.json_response({"candidate": await sources.from_url(url)})
        except ValueError as ex:
            return _err(str(ex))

    @routes.post(P + "/workflows/sources")
    async def wf_sources(request):
        """Known download sources for models the open workflow uses (to embed in it)."""
        b = await _body(request)
        inv = await asyncio.to_thread(paths.Inventory)

        def lookup():
            out = []
            for it in b.get("items", [])[:500]:
                val, folder = it.get("value"), paths.canonical(it.get("folder"))
                if not isinstance(val, str) or not folder:
                    continue
                state, ffolder, fname, _ = inv.find(val, folder)
                sha = None
                if state != "missing":
                    fp = inv.full_path(ffolder, fname)
                    sha = hashing.cached(fp) if fp else None
                e = registry.lookup(val) or (registry.lookup_hash(sha) if sha else None)
                if not e or not str(e.get("url", "")).startswith("https://"):
                    out.append({"value": val, "url": None})
                    continue
                if sha and e.get("sha256") and e["sha256"].lower() != sha.lower():
                    out.append({"value": val, "url": None, "note": "registry entry is for a different file"})
                    continue
                out.append({"value": val, "url": e["url"], "directory": folder,
                            "hash": (sha or e.get("sha256") or "").lower() or None})
            return out
        return web.json_response({"sources": await asyncio.to_thread(lookup)})

    @routes.post(P + "/workflows/scan")
    async def wf_scan(request):
        b = await _body(request)
        paths.invalidate()
        return web.json_response(await asyncio.to_thread(workflows.scan, bool(b.get("apply"))))

    @routes.post(P + "/bridge/plan")
    async def bridge_plan(request):
        b = await _body(request)
        secs = [s for s in b.get("sections", []) if s in library.SECTIONS] or ["loras"]
        return web.json_response(await asyncio.to_thread(bridge.plan, secs))

    @routes.post(P + "/bridge/apply")
    @_busy_ok
    async def bridge_apply(request):
        b = await _body(request)
        return web.json_response(await asyncio.to_thread(bridge.apply, [i for i in b.get("ids", []) if isinstance(i, str)]))

    @routes.post(P + "/recipe/plan")
    async def recipe_plan(request):
        b = await _body(request)
        loras = b.get("loras") if isinstance(b.get("loras"), list) else []
        return web.json_response(await recipes.plan(loras, b.get("checkpoint")))

    # ------------------------------------------------------------- downloads
    @routes.post(P + "/download")
    async def download(request):
        b = await _body(request)
        try:
            job = downloader.start(url=b["url"], folder=b["folder"], rel=b["rel"], sha256=b.get("sha256"),
                                   size=b.get("size"), source=b.get("source", "manual"),
                                   page_url=b.get("page_url"), title=b.get("title"), meta=b.get("meta"),
                                   auto_place=bool(b.get("auto_place")))
        except (KeyError, ValueError) as ex:
            return _err(str(ex))
        return web.json_response({"job": {k: v for k, v in job.items() if k != "meta"}})

    @routes.get(P + "/jobs")
    async def jobs(request):
        return web.json_response({"jobs": [{k: v for k, v in j.items() if k != "meta"}
                                           for j in downloader.jobs()]})

    @routes.post(P + "/jobs/{jid}/cancel")
    async def cancel(request):
        return web.json_response({"ok": downloader.cancel(request.match_info["jid"])})

    @routes.post(P + "/jobs/{jid}/retry")
    async def retry(request):
        try:
            job = downloader.retry(request.match_info["jid"])
        except ValueError as ex:
            return _err(str(ex))
        return web.json_response({"job": {k: v for k, v in job.items() if k != "meta"}})

    @routes.get(P + "/partials")
    async def partials(request):
        return web.json_response({"partials": await asyncio.to_thread(downloader.partials)})

    @routes.post(P + "/partials/delete")
    async def partials_delete(request):
        b = await _body(request)
        return web.json_response(await asyncio.to_thread(downloader.delete_partials, b.get("paths", [])))

    @routes.post(P + "/jobs/clear")
    async def clear(request):
        downloader.clear_finished()
        return web.json_response({"ok": True})

    @routes.post(P + "/vram")
    async def vram(request):
        b = await _body(request)
        return web.json_response(await swaps.suggest(b.get("value", ""), b.get("size"), b.get("node_type"),
                                                     b.get("node_types")))

    # ------------------------------------------------------------- registry
    @routes.get(P + "/registry")
    async def reg_list(request):
        return web.json_response({"entries": registry.all_entries()})

    @routes.post(P + "/registry")
    async def reg_add(request):
        b = await _body(request)
        if not b.get("filename") or not str(b.get("url", "")).startswith("https://"):
            return _err("filename and an https:// url are required")
        e = registry.remember(b["filename"], b["url"], source="manual", folder=paths.canonical(b.get("folder")),
                              sha256=b.get("sha256"), page_url=b.get("page_url"), title=b.get("title"))
        return web.json_response({"entry": e})

    @routes.delete(P + "/registry/{name}")
    async def reg_del(request):
        return web.json_response({"ok": registry.forget(request.match_info["name"])})

    # ------------------------------------------------------------- library
    @routes.get(P + "/library")
    async def lib(request):
        section = request.query.get("section", "loras")
        if section not in library.SECTIONS:
            return _err("unknown section")
        entries = await asyncio.to_thread(library.build, section)
        return web.json_response({
            "section": section, "roots": [os.path.basename(r.rstrip("/\\")) for r in library.roots(section)],
            "entries": [library.public(e) for e in entries],
            "blur_nsfw": config.load().get("blur_nsfw", True),
        })

    @routes.get(P + "/library/usage")
    async def lib_usage(request):
        section = request.query.get("section", "loras")
        if section not in library.SECTIONS:
            return _err("unknown section")
        return web.json_response(await asyncio.to_thread(usage.unused, section))

    @routes.get(P + "/preview/{fid}")
    async def preview(request):
        e = library.get(request.match_info["fid"])
        if not e or not e.get("preview") or not os.path.isfile(e["preview"]):
            return web.Response(status=404)
        ctype = mimetypes.guess_type(e["preview"])[0] or "application/octet-stream"
        return web.FileResponse(e["preview"], headers={"Content-Type": ctype,
                                                       "Cache-Control": "max-age=3600"})

    @routes.post(P + "/identify")
    @_busy_ok
    async def identify(request):
        b = await _body(request)
        secs = [s for s in b.get("sections", []) if s in library.SECTIONS] or ["loras"]
        ids = [i for i in b.get("ids", []) if isinstance(i, str)] or None
        return web.json_response(await library.identify(secs, bool(b.get("force")), ids))

    @routes.get(P + "/identify")
    async def identify_status(request):
        return web.json_response(library.job_status())

    @routes.post(P + "/identify/cancel")
    async def identify_cancel(request):
        library.cancel_identify()
        return web.json_response({"ok": True})

    # ------------------------------------------------------------- organize
    @routes.post(P + "/organize/plan")
    async def org_plan(request):
        b = await _body(request)
        secs = [s for s in b.get("sections", []) if s in library.SECTIONS] or ["loras"]
        mode = "full" if b.get("mode") == "full" else "loose"
        return web.json_response(await asyncio.to_thread(organize.plan, secs, mode))

    @routes.post(P + "/organize/apply")
    @_busy_ok
    async def org_apply(request):
        b = await _body(request)
        return web.json_response(await asyncio.to_thread(organize.apply, b.get("items", [])))

    @routes.get(P + "/organize/history")
    async def org_hist(request):
        return web.json_response({"runs": organize.history()})

    @routes.post(P + "/organize/undo")
    @_busy_ok
    async def org_undo(request):
        b = await _body(request)
        return web.json_response(await asyncio.to_thread(organize.undo, b.get("run_id")))

    @routes.post(P + "/duplicates/scan")
    @_busy_ok
    async def dup_scan(request):
        b = await _body(request)
        secs = [s for s in b.get("sections", []) if s in library.SECTIONS] or list(library.SECTIONS)
        return web.json_response(await organize.find_duplicates(secs))

    @routes.get(P + "/duplicates")
    async def dup_status(request):
        return web.json_response(organize.dup_status())

    @routes.post(P + "/duplicates/hardlink")
    @_busy_ok
    async def dup_link(request):
        b = await _body(request)
        return web.json_response(await asyncio.to_thread(organize.hardlink, b.get("ids", [])))

    @routes.post(P + "/duplicates/quarantine")
    @_busy_ok
    async def dup_q(request):
        b = await _body(request)
        return web.json_response(await asyncio.to_thread(organize.quarantine, b.get("ids", [])))

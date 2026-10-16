"""The Library: models, previews, metadata lookups, your notes, HuggingFace details, update alerts, CivArchive."""
from __future__ import annotations

import asyncio
import mimetypes
import os
import re

from aiohttp import web

from .. import civarchive, config, hfmeta, library, notes, paths, sources, thumbs, tiering, updates, usage
from .common import P, _err, _busy_ok, _body


def register(routes: web.RouteTableDef) -> None:
    @routes.get(P + "/library")
    async def lib(request):
        section = request.query.get("section", "loras")
        if section not in library.SECTIONS:
            return _err("unknown section")
        entries = await asyncio.to_thread(library.build, section)
        await asyncio.to_thread(updates.annotate, entries)
        await asyncio.to_thread(hfmeta.annotate, entries)
        await asyncio.to_thread(notes.annotate, entries)
        await asyncio.to_thread(tiering.annotate_usage, entries)
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
        path = e["preview"]
        w = request.query.get("w", "")
        if w.isdigit():  # cards ask for a small thumbnail instead of the full-size image
            path = await asyncio.to_thread(thumbs.thumb_for, path, int(w))
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        return web.FileResponse(path, headers={"Content-Type": ctype,
                                               "Cache-Control": "max-age=86400" if w else "max-age=3600"})

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

    @routes.post(P + "/library/notes")
    async def library_notes(request):
        """Your rating, note and tags for a model: {id, rating?, note?, tags?}."""
        b = await _body(request)
        e = library.get(str(b.get("id") or ""))
        if not e:
            return _err("model not found (refresh the Library)", 404)
        try:
            n = await asyncio.to_thread(notes.save, e["section"], e["name"], {k: b[k] for k in ("rating", "note", "tags") if k in b})
        except ValueError as ex:
            return _err(str(ex))
        return web.json_response({"notes": n})

    @routes.post(P + "/civarchive/lookup")
    async def civarchive_lookup(request):
        """What CivArchive knows about a file: copies (live or not) and the CivitAI details it kept."""
        b = await _body(request)
        sha = str(b.get("sha256") or "").lower()
        if not re.fullmatch(r"[a-f0-9]{64}", sha):
            return _err("sha256 required")
        try:
            rec = await civarchive.by_hash(sha, force=bool(b.get("force")))
        except Exception as ex:
            return _err(f"CivArchive lookup failed: {ex}", 502)
        return web.json_response({"record": rec, "page_url": civarchive.page_url(sha)})

    @routes.post(P + "/hf/details")
    async def hf_details(request):
        """HuggingFace repo details (license, tags, model card excerpt), refreshed on request."""
        b = await _body(request)
        repo = str(b.get("repo") or "")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            return _err("repo must look like owner/name")
        try:
            d = await hfmeta.fetch(repo, force=bool(b.get("force")))
        except Exception as ex:
            return _err(f"HuggingFace lookup failed: {ex}", 502)
        return web.json_response({"repo": repo, "details": d})

    @routes.get(P + "/updates")
    async def updates_status(request):
        return web.json_response(updates.job_status())

    @routes.post(P + "/updates/check")
    async def updates_check(request):
        b = await _body(request)
        secs = [s for s in b.get("sections", []) if s in library.SECTIONS] or None
        return web.json_response(await updates.check(bool(b.get("force")), secs))

    @routes.post(P + "/updates/cancel")
    async def updates_cancel(request):
        updates.cancel()
        return web.json_response({"ok": True})

    @routes.post(P + "/updates/dismiss")
    async def updates_dismiss(request):
        b = await _body(request)
        try:
            await asyncio.to_thread(updates.dismiss, int(b["model_id"]), int(b["version_id"]))
        except (KeyError, TypeError, ValueError):
            return _err("model_id and version_id required")
        return web.json_response({"ok": True})

    @routes.post(P + "/updates/compare")
    async def updates_compare(request):
        """The version you have next to the newer one: changelog, sizes, trigger words, sample images."""
        b = await _body(request)
        try:
            mid, have, newer = int(b["model_id"]), int(b.get("have") or 0), int(b["newer"])
        except (KeyError, TypeError, ValueError):
            return _err("model_id and newer required")
        try:
            return web.json_response(await updates.compare(mid, have, newer))
        except LookupError as ex:
            return _err(str(ex), 404)
        except Exception as ex:
            return _err(f"CivitAI lookup failed: {ex}", 502)

    @routes.post(P + "/updates/candidate")
    async def updates_candidate(request):
        """The newer version's file, saved next to the old one (which is kept)."""
        b = await _body(request)
        e = library.get(str(b.get("id") or ""))
        if not e:
            return _err("model not found (refresh the Library)", 404)
        try:
            cand = await sources.civitai_by_version(int(b["version_id"]))
        except (KeyError, TypeError, ValueError):
            return _err("version_id required")
        except Exception as ex:
            return _err(f"CivitAI lookup failed: {ex}", 502)
        if not cand:
            return _err("CivitAI doesn't have that version any more", 404)
        sub = os.path.dirname(e["rel"].replace("\\", "/"))
        name = cand.get("filename") or os.path.basename(e["rel"])

        def free(n):
            try:
                return not os.path.exists(paths.dest_path(e["section"], f"{sub}/{n}" if sub else n)[0])
            except ValueError:
                return False
        if not free(name):  # the new version reuses the old file name: keep both
            stem, ext = os.path.splitext(name)
            tag = re.sub(r"[^A-Za-z0-9._-]+", "_", str(b.get("version_name") or b["version_id"])).strip("_") or str(b["version_id"])
            name = f"{stem}_{tag}{ext}"
        rel = f"{sub}/{name}" if sub else name
        dest, shared = paths.dest_path(e["section"], rel)
        return web.json_response({"candidate": cand, "folder": e["section"], "rel": rel, "dest": dest, "shared": shared})

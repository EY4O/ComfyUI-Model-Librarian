"""For the Model Librarian Chrome extension: hello, lookup, download, jobs, and the characters it files from boorus."""
from __future__ import annotations

import asyncio

from aiohttp import web

from .. import characters, ext
from .common import P, _err, _body


def register(routes: web.RouteTableDef) -> None:
    @routes.get(P + "/ext/hello")
    async def ext_hello(request):
        return web.json_response(await asyncio.to_thread(ext.hello))

    @routes.post(P + "/ext/lookup")
    async def ext_lookup(request):
        """Which CivitAI versions (and SHA256s) are already in the library."""
        b = await _body(request)
        return web.json_response(await asyncio.to_thread(ext.lookup, b.get("version_ids") or [], b.get("hashes") or [], b.get("model_ids") or []))

    @routes.post(P + "/ext/download")
    async def ext_download(request):
        """A CivitAI version's file (the primary one unless file_id says) into the right folder."""
        b = await _body(request)
        try:
            return web.json_response(await ext.download(b.get("version_id"), b.get("file_id"), dry_run=bool(b.get("dry_run"))))
        except ValueError as ex:
            return _err(str(ex))
        except LookupError as ex:
            return _err(str(ex), 404)
        except Exception as ex:
            return _err(f"CivitAI lookup failed: {ex}", 502)

    @routes.post(P + "/ext/companions")
    async def ext_companions(request):
        """What a diffusion model also needs (text encoders, VAE), from ComfyUI's workflow templates."""
        b = await _body(request)
        return web.json_response(await asyncio.to_thread(ext.companions, b.get("base_model"), b.get("file_name")))

    @routes.post(P + "/ext/companion-download")
    async def ext_companion_download(request):
        b = await _body(request)
        try:
            return web.json_response(await ext.companion_download(b.get("base_model"), b.get("file_name"), b.get("name")))
        except ValueError as ex:
            return _err(str(ex))
        except LookupError as ex:
            return _err(str(ex), 404)
        except Exception as ex:
            return _err(f"Couldn't start that download: {ex}", 502)

    @routes.get(P + "/ext/model")
    async def ext_model(request):
        """A CivitAI model's versions and files (the Library's "find a better fit"); raw=1: CivitAI's whole
        answer, for the extension when the public API won't show the model."""
        try:
            if request.query.get("raw"):
                return web.json_response(await ext.civitai_model_raw(request.query.get("id")))
            return web.json_response(await ext.civitai_model(request.query.get("id")))
        except ValueError as ex:
            return _err(str(ex))
        except LookupError as ex:
            return _err(str(ex), 404)
        except Exception as ex:
            return _err(f"CivitAI lookup failed: {ex}", 502)

    @routes.post(P + "/ext/civarchive")
    async def ext_civarchive(request):
        """A file CivArchive lists (by SHA256): yours already, or its live copies, planned into the right folder."""
        b = await _body(request)
        try:
            return web.json_response(await ext.civarchive_copies(b.get("sha256")))
        except ValueError as ex:
            return _err(str(ex))
        except Exception as ex:
            return _err(f"CivArchive lookup failed: {ex}", 502)

    @routes.post(P + "/ext/download-url")
    async def ext_download_url(request):
        """A HuggingFace file page (or download link) into the folder picked in the extension."""
        b = await _body(request)
        try:
            return web.json_response(await ext.download_url(b.get("url"), b.get("folder"), dry_run=bool(b.get("dry_run"))))
        except ValueError as ex:
            return _err(str(ex))
        except Exception as ex:
            return _err(f"Couldn't read that link: {ex}", 502)

    @routes.get(P + "/ext/jobs")
    async def ext_jobs(request):
        ids = [x for x in request.query.get("ids", "").split(",") if x]
        return web.json_response({"jobs": ext.jobs(ids)})

    @routes.get(P + "/ext/characters")
    async def ext_characters(request):
        """Your characters (tag, name, outfits): the extension's sheet says which ones you have already."""
        return web.json_response({"characters": await asyncio.to_thread(characters.listing)})

    @routes.post(P + "/ext/characters")
    async def ext_characters_add(request):
        """{character, picture?} -> {character, created}: one character from a booru post, filed into characters.json."""
        if not (request.content_type or "").startswith("application/json"):  # a web page can't send this without asking first
            return _err("JSON only", 415)
        b = await _body(request)
        try:
            return web.json_response(await asyncio.to_thread(characters.save_import, b.get("character"), b.get("picture")))
        except ValueError as ex:
            return _err(str(ex))

    @routes.get(P + "/characters/{cid}/picture")
    async def character_picture(request):
        p = await asyncio.to_thread(characters.picture_file, request.match_info["cid"])
        if not p:
            return _err("No picture", 404)
        return web.FileResponse(p, headers={"Cache-Control": "no-cache"})

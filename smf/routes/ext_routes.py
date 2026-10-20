"""For the Model Librarian Chrome extension: hello, lookup, download, jobs."""
from __future__ import annotations

import asyncio

from aiohttp import web

from .. import ext
from .common import P, _err, _body


def register(routes: web.RouteTableDef) -> None:
    @routes.get(P + "/ext/hello")
    async def ext_hello(request):
        return web.json_response(await asyncio.to_thread(ext.hello))

    @routes.post(P + "/ext/lookup")
    async def ext_lookup(request):
        """Which CivitAI versions (and SHA256s) are already in the library."""
        b = await _body(request)
        return web.json_response(await asyncio.to_thread(ext.lookup, b.get("version_ids") or [], b.get("hashes") or []))

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

    @routes.get(P + "/ext/jobs")
    async def ext_jobs(request):
        ids = [x for x in request.query.get("ids", "").split(",") if x]
        return web.json_response({"jobs": ext.jobs(ids)})

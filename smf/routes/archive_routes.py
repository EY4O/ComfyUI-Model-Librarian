"""Archive: consolidate what made every image in a folder (report, CSV, recipes, workflows, thumbnails)."""
from __future__ import annotations

import asyncio

from aiohttp import web

from .. import archive
from .common import P, _err, _body


def register(routes: web.RouteTableDef) -> None:
    @routes.post(P + "/archive/start")
    async def archive_start(request):
        b = await _body(request)
        mode = b.get("grouping") if b.get("grouping") in archive.SIMILARITY else "similar"
        try:
            st = await asyncio.to_thread(archive.start, b.get("folder"), recursive=bool(b.get("recursive", True)),
                                         thumbs=bool(b.get("thumbs", True)), embed=bool(b.get("embed", True)), mode=mode)
        except ValueError as ex:
            return _err(str(ex))
        return web.json_response(st)

    @routes.get(P + "/archive/status")
    async def archive_status(request):
        return web.json_response(archive.job_status())

    @routes.post(P + "/archive/cancel")
    async def archive_cancel(request):
        archive.cancel()
        return web.json_response({"ok": True})

    @routes.get(P + "/archive/summary")
    async def archive_summary(request):
        """The last archive written for a folder (or null)."""
        return web.json_response({"summary": await asyncio.to_thread(archive.summary, request.query.get("folder", ""))})

    @routes.get(P + "/archive/thumb")
    async def archive_thumb(request):
        p = archive.thumb_path(request.query.get("folder", ""), request.query.get("name", ""))
        if not p:
            return web.Response(status=404)
        return web.FileResponse(p, headers={"Content-Type": "image/webp", "Cache-Control": "max-age=3600"})

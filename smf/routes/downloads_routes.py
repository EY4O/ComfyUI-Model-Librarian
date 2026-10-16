"""Downloads and leftover partial files."""
from __future__ import annotations

import asyncio

from aiohttp import web

from .. import downloader
from .common import P, _err, _body


def register(routes: web.RouteTableDef) -> None:
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

    @routes.get(P + "/partials/summary")
    async def partials_summary(request):
        return web.json_response(await asyncio.to_thread(downloader.partials_summary))

    @routes.post(P + "/partials/delete")
    async def partials_delete(request):
        b = await _body(request)
        return web.json_response(await asyncio.to_thread(downloader.delete_partials, b.get("paths", [])))

    @routes.post(P + "/jobs/clear")
    async def clear(request):
        downloader.clear_finished()
        return web.json_response({"ok": True})

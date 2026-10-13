"""Organize (base-model folders), duplicates and the LoRA Manager metadata bridge."""
from __future__ import annotations

import asyncio

from aiohttp import web

from .. import bridge, library, organize
from .common import P, _busy_ok, _body


def register(routes: web.RouteTableDef) -> None:
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

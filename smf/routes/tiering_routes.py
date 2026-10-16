"""SSD/HDD storage tiers."""
from __future__ import annotations

import asyncio
import time

from aiohttp import web

from .. import storehist, tiering
from .common import P, _busy_ok, _body


def register(routes: web.RouteTableDef) -> None:
    @routes.get(P + "/storage/history")
    async def storage_history(request):
        """Free space per drive over time, and what the storage tiers moved each day."""
        try:
            days = max(7, min(365, int(request.query.get("days", 90))))
        except ValueError:
            days = 90
        await asyncio.to_thread(storehist.sample)
        return web.json_response(await asyncio.to_thread(storehist.history, days))

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

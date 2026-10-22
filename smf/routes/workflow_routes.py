"""The open workflow (scan, sources) and saved workflows (health, repair, embedded sources)."""
from __future__ import annotations

import asyncio

from aiohttp import web

from .. import paths, share, sources, scanrefs, swaps, workflows
from .common import P, _err, _body, _local_by_sha


def register(routes: web.RouteTableDef) -> None:
    @routes.post(P + "/scan")
    async def scan(request):
        body = await _body(request)
        inv = await asyncio.to_thread(paths.Inventory)
        budget = swaps.budget_bytes()
        items = scanrefs.group(body.get("refs", []), inv, budget)
        await asyncio.to_thread(scanrefs.add_trigger_words, items, inv)
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
        """Download links, pages and SHA256s for the models the open workflow uses (to share it)."""
        b = await _body(request)
        rows = await share.sources_for(b.get("items") or [])
        return web.json_response({"sources": rows, "markdown": share.markdown(rows, b.get("title"))})

    @routes.get(P + "/workflows/health")
    async def wf_health(request):
        """Missing / moved models across every saved workflow."""
        paths.invalidate()
        return web.json_response(await asyncio.to_thread(workflows.health))

    @routes.post(P + "/workflows/scan")
    async def wf_scan(request):
        b = await _body(request)
        paths.invalidate()
        return web.json_response(await asyncio.to_thread(workflows.scan, bool(b.get("apply"))))

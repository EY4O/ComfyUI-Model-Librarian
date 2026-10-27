"""Your characters (characters.json, shared with the Chrome extension and the Gallery): the Character Select node's picker."""
from __future__ import annotations

import asyncio

from aiohttp import web

from .. import characters
from .common import P, _err


def register(routes: web.RouteTableDef) -> None:
    @routes.get(P + "/characters")
    async def characters_list(request):
        """Every character, whole (tags, outfits, LoRA), for the node's picker."""
        return web.json_response({"characters": await asyncio.to_thread(characters.for_picker)})

    @routes.get(P + "/characters/{cid}/picture")
    async def character_picture(request):
        p = await asyncio.to_thread(characters.picture_file, request.match_info["cid"])
        if not p:
            return _err("No picture", 404)
        return web.FileResponse(p, headers={"Cache-Control": "no-cache"})

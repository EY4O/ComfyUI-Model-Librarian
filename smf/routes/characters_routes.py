"""Your characters (characters.json, shared with the Chrome extension and the Gallery): the Character Select node's picker."""
from __future__ import annotations

import asyncio
import os

from aiohttp import web

from .. import characters
from .common import P, _err, _body


def register(routes: web.RouteTableDef) -> None:
    @routes.get(P + "/characters")
    async def characters_list(request):
        """Every character, whole (tags, outfits, LoRA), for the node's picker."""
        return web.json_response({"characters": await asyncio.to_thread(characters.for_picker)})

    @routes.post(P + "/characters/{cid}/lora")
    async def character_lora(request):
        """{name (a LoRA as ComfyUI names it; empty: none), trigger?} -> {character}: the LoRA Character Select loads for it."""
        if not (request.content_type or "").startswith("application/json"):  # a web page can't send this without asking first
            return _err("JSON only", 415)
        b = await _body(request)
        try:
            c = await asyncio.to_thread(characters.set_lora, request.match_info["cid"], b.get("name"), b.get("trigger"))
        except LookupError:
            return _err("No such character", 404)
        except ValueError as ex:
            return _err(str(ex))
        except OSError as ex:
            return _err(f"Couldn't save it: {ex}", 500)
        return web.json_response({"character": c})

    @routes.get(P + "/characters/loras")
    async def character_loras(request):
        """The LoRAs you have (the names ComfyUI's loaders take), for linking one to a character."""
        return web.json_response({"loras": await asyncio.to_thread(characters.loras)})

    @routes.get(P + "/characters/{cid}/picture")
    async def character_picture(request):
        p = await asyncio.to_thread(characters.picture_file, request.match_info["cid"])
        if not p:
            return _err("No picture", 404)
        kind = {".webp": "image/webp", ".jpg": "image/jpeg", ".png": "image/png"}[os.path.splitext(p)[1].lower()]
        return web.FileResponse(p, headers={"Cache-Control": "no-cache", "Content-Type": kind})

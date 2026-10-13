"""Status, settings, VRAM advice and the download registry."""
from __future__ import annotations

import os

from aiohttp import web

from .. import config, library, organize, paths, registry, swaps, tiering
from .common import P, _err, _body, _node_installed


def register(routes: web.RouteTableDef) -> None:
    @routes.get(P + "/status")
    async def status(request):
        info = paths.sm_info()
        dests = {}
        for f in ("checkpoints", "loras", "diffusion_models", "text_encoders", "vae", "controlnet",
                  "upscale_models", "embeddings", "clip_vision"):
            d, shared = paths.dest_dir(f)
            dests[f] = {"path": d, "shared": shared}
        return web.json_response({
            "config": config.public(), "sm": {"mode": info["mode"], "models_root": info["models_root"]},
            "destinations": dests, "gguf_installed": _node_installed("UnetLoaderGGUF"),
            "lm_installed": _node_installed("Lora Loader (LoraManager)"),
            "families": organize.basemodel.FAMILIES, "sections": library.SECTIONS, "sep": os.sep,
        })

    @routes.post(P + "/config")
    async def set_config(request):
        try:
            cfg = config.save(await _body(request))
        except ValueError as ex:
            return _err(str(ex))
        tiering.register_folders()
        return web.json_response({"config": config.public(cfg)})

    @routes.post(P + "/vram")
    async def vram(request):
        b = await _body(request)
        return web.json_response(await swaps.suggest(b.get("value", ""), b.get("size"), b.get("node_type"),
                                                     b.get("node_types")))

    @routes.get(P + "/registry")
    async def reg_list(request):
        return web.json_response({"entries": registry.all_entries()})

    @routes.post(P + "/registry")
    async def reg_add(request):
        b = await _body(request)
        if not b.get("filename") or not str(b.get("url", "")).startswith("https://"):
            return _err("filename and an https:// url are required")
        e = registry.remember(b["filename"], b["url"], source="manual", folder=paths.canonical(b.get("folder")),
                              sha256=b.get("sha256"), page_url=b.get("page_url"), title=b.get("title"))
        return web.json_response({"entry": e})

    @routes.delete(P + "/registry/{name}")
    async def reg_del(request):
        return web.json_response({"ok": registry.forget(request.match_info["name"])})

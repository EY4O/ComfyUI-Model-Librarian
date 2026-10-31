"""For Model Librarian Gallery: open a file's workflow, or a recipe, in ComfyUI.

The Gallery sends the workflow (or a recipe: its id in the shared recipes folder, and the recipe itself) here; it waits under a one-time token while every open ComfyUI page is told
about it, and the first page to claim it opens it in a new tab (a page you're looking at claims first). So
one tab opens, wherever ComfyUI is open, and nothing is queued. A recipe opens in the Recipes tab, ready to
download what's missing and fill the workflow.
"""
from __future__ import annotations

import re
import secrets
import time

from aiohttp import web

from .common import P, _err, _body

_PENDING: dict[str, dict] = {}
_KEEP = 60          # seconds a workflow waits to be claimed
_MAX = 32 * 1024 * 1024


def _tidy() -> None:
    now = time.time()
    for k in [k for k, v in _PENDING.items() if now - v["at"] > _KEEP]:
        _PENDING.pop(k, None)


def register(routes: web.RouteTableDef) -> None:
    @routes.post(P + "/gallery/open")
    async def gallery_open(request):
        """{workflow (the UI graph) or prompt (the API graph), or recipe (recipe/1) with its recipe_id and thumb, name}
        -> {clients}: how many ComfyUI pages were told."""
        if (request.content_length or 0) > _MAX:
            return _err("That workflow is too big.", 413)
        if not (request.content_type or "").startswith("application/json"):  # a web page can't send this without asking first
            return _err("JSON only", 415)
        b = await _body(request)
        wf, prompt, recipe = b.get("workflow"), b.get("prompt"), b.get("recipe")
        if not isinstance(wf, dict) and not isinstance(prompt, dict) and not isinstance(recipe, dict):
            return _err("Send a workflow, a prompt or a recipe.")
        if isinstance(wf, dict) and not isinstance(wf.get("nodes"), list):
            return _err("That isn't a ComfyUI workflow.")
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(b.get("name") or "From the Gallery"))[:120].strip() or "From the Gallery"
        _tidy()
        token = secrets.token_urlsafe(16)
        rid = str(b.get("recipe_id") or "")
        thumb = b.get("thumb")
        _PENDING[token] = {"at": time.time(), "workflow": wf if isinstance(wf, dict) else None,
                           "prompt": prompt if isinstance(prompt, dict) else None, "name": name,
                           "recipe": recipe if isinstance(recipe, dict) and not isinstance(wf, dict) and not isinstance(prompt, dict) else None,
                           "recipe_id": rid if re.fullmatch(r"[a-f0-9]{12}", rid) else None,  # (saved in the shared recipes folder)
                           "thumb": thumb if isinstance(thumb, str) and thumb.startswith("data:image/") else None}
        from server import PromptServer
        ps = PromptServer.instance
        clients = len(getattr(ps, "sockets", {}) or {})
        ps.send_sync("ml-gallery-open", {"token": token, "name": name})
        return web.json_response({"clients": clients, "token": token})

    @routes.post(P + "/gallery/claim")
    async def gallery_claim(request):
        """The page that gets here first opens it; the others are told it's taken."""
        b = await _body(request)
        _tidy()
        item = _PENDING.pop(str(b.get("token") or ""), None)
        if not item:
            return _err("taken", 410)
        return web.json_response({k: item[k] for k in ("workflow", "prompt", "name", "recipe", "recipe_id", "thumb")})

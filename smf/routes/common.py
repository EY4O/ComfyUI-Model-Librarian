"""Helpers shared by the route modules."""
from __future__ import annotations

import functools

from aiohttp import web

from .. import busy, hashing, paths

P = "/sm-fetcher"


def _err(msg: str, status: int = 400):
    return web.json_response({"error": msg}, status=status)


def _busy_ok(fn):
    """Another library operation is running -> 409 with a message the UI shows."""
    @functools.wraps(fn)
    async def wrapper(request):
        try:
            return await fn(request)
        except busy.Busy as ex:
            return _err(str(ex), 409)
    return wrapper


async def _body(request) -> dict:
    try:
        return await request.json()
    except Exception:
        return {}


def _node_installed(name: str) -> bool:
    try:
        import nodes
        return name in nodes.NODE_CLASS_MAPPINGS
    except Exception:
        return False


def _local_by_sha(folder: str | None, inv: paths.Inventory) -> dict:
    """sha256 -> ComfyUI name, for files of this folder type that are already hashed
    (names come from ComfyUI's own list, so repointed widgets validate)."""
    out = {}
    if not folder:
        return out
    for f in inv._folders_for(folder):
        for n in inv.lists[f]:
            fp = inv.full_path(f, n)
            sha = hashing.cached(fp) if fp else None
            if sha:
                out.setdefault(sha.lower(), n)
    return out

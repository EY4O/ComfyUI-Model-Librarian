"""HTTP API (mounted on ComfyUI's PromptServer under /sm-fetcher and /api/sm-fetcher).

One module per area (*_routes.py); register() wires them all up. Importing every data module
here registers their shared-data mergers before the migration below runs.
"""
from __future__ import annotations

import logging

from aiohttp import web

from .. import (bridge, busy, civarchive, config, downloader, hashing, hfmeta, library, notes, organize, paths, recipes, registry, smmeta, sources, recipe_parse, recipe_store, scanrefs, swaps, tiering, updates, usage, videometa, workflows)  # noqa: F401  (mergers)
from . import (core_routes, downloads_routes, library_routes, organize_routes, recipes_routes, tiering_routes,
               workflow_routes)
from .common import P, _local_by_sha  # noqa: F401  (used by tests and the bridge)


def register(routes: web.RouteTableDef) -> None:
    # every data module is imported above, so all their mergers are registered
    try:
        merged = config.migrate_to_shared()
        if merged:
            logging.info("[Model Librarian] merged %s into shared data folder %s", ", ".join(merged),
                         config.data_dir())
    except Exception:
        logging.exception("[Model Librarian] couldn't merge local data into the shared folder")
    try:
        tiering.install()  # archive folders visible to ComfyUI + usage tracking hook
    except Exception:
        logging.exception("[Model Librarian] storage tiers unavailable")
    for area in (core_routes, workflow_routes, tiering_routes, recipes_routes, downloads_routes, library_routes, organize_routes):
        area.register(routes)

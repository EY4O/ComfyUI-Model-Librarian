"""Model Librarian — ComfyUI extension.

Finds and downloads missing models into Stability Matrix's shared model
folders, identifies/organizes your library and suggests GGUF swaps that fit
your GPU. Everything lives in the Models panel (toolbar button / Extensions
menu), plus one workflow node: Gallery Info, which tags what a workflow makes
for Model Librarian Gallery.
"""
import logging

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
WEB_DIRECTORY = "./js"

try:
    from .smf import gallery_node as _gallery

    NODE_CLASS_MAPPINGS.update(_gallery.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_gallery.NODE_DISPLAY_NAME_MAPPINGS)
except Exception as e:  # never break ComfyUI startup
    logging.exception("[Model Librarian] the Gallery Info node failed to load: %s", e)

try:
    from server import PromptServer
    from .smf import routes as _routes

    _routes.register(PromptServer.instance.routes)
    logging.info("[Model Librarian] loaded")
except Exception as e:  # never break ComfyUI startup
    logging.exception("[Model Librarian] failed to load: %s", e)

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]

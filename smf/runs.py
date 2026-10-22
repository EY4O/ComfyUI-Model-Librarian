"""The images ComfyUI's recent runs made (from its run history), and a recipe from one of them.

ComfyUI's history keeps, for each run, the API prompt and the workflow it ran (with the workflow's id) and
the images each output node made. A recipe is read from the image itself first (what ComfyUI embedded when
it saved it); an image saved without that data falls back to the run's own prompt and workflow.
"""
from __future__ import annotations

import asyncio
import os

from . import recipe_parse, recipe_store

MAX_RUNS = 64


def _queue():
    try:
        import server
        return server.PromptServer.instance.prompt_queue
    except Exception:
        return None


def _history(prompt_id: str | None = None, max_items: int | None = MAX_RUNS) -> dict:
    q = _queue()
    if q is None:
        return {}
    try:
        return q.get_history(prompt_id=prompt_id, max_items=None if prompt_id else max_items) or {}
    except Exception:
        return {}


def _run_parts(entry: dict) -> tuple[dict | None, dict]:
    """-> (API prompt, workflow) of a history entry."""
    p = entry.get("prompt") or ()
    prompt = p[2] if len(p) > 2 and isinstance(p[2], dict) else None
    extra = p[3] if len(p) > 3 and isinstance(p[3], dict) else {}
    wf = (extra.get("extra_pnginfo") or {}).get("workflow")
    return prompt, wf if isinstance(wf, dict) else {}


def _when(entry: dict) -> float:
    for m in (entry.get("status") or {}).get("messages") or []:
        if isinstance(m, (list, tuple)) and len(m) > 1 and isinstance(m[1], dict) and m[1].get("timestamp"):
            return m[1]["timestamp"] / 1000
    return 0.0


def recent_images(workflow_id: str | None = None, node: str | None = None, limit: int = 12) -> list[dict]:
    """Images from recent runs, newest first: of one workflow (by its id) and/or one output node."""
    out = []
    for pid, entry in reversed(list(_history().items())):
        _prompt, wf = _run_parts(entry)
        if workflow_id and wf.get("id") != workflow_id:
            continue
        meta = entry.get("meta") or {}
        for nid, o in (entry.get("outputs") or {}).items():
            shown = str((meta.get(nid) or {}).get("display_node") or nid)
            if node is not None and str(node) not in (str(nid), shown):
                continue
            for im in (o or {}).get("images") or []:
                if isinstance(im, dict) and im.get("filename"):
                    out.append({"filename": im["filename"], "subfolder": im.get("subfolder") or "", "type": im.get("type") or "output",
                                "prompt_id": pid, "node": shown, "time": _when(entry)})
                    if len(out) >= limit:
                        return out
    return out


def image_path(item: dict) -> str:
    """Full path of an image in ComfyUI's output, temp or input folder (never outside them)."""
    import folder_paths
    base = {"output": folder_paths.get_output_directory, "temp": folder_paths.get_temp_directory,
            "input": folder_paths.get_input_directory}.get(item.get("type") or "output")
    if base is None:
        raise ValueError("unknown image type")
    base = os.path.abspath(base())
    name = str(item.get("filename") or "")
    if not name or os.path.basename(name) != name:
        raise ValueError("bad file name")
    full = os.path.abspath(os.path.join(base, str(item.get("subfolder") or ""), name))
    if os.path.commonpath([full, base]) != base:
        raise ValueError("outside ComfyUI's folders")
    return full


def _run_for(item: dict, prompt_id: str | None) -> dict | None:
    """The history entry of the run that made this image (by id, or by finding the image in recent runs)."""
    if prompt_id:
        entry = _history(prompt_id).get(prompt_id)
        if entry:
            return entry
    for pid, entry in reversed(list(_history().items())):
        for o in (entry.get("outputs") or {}).values():
            for im in (o or {}).get("images") or []:
                if isinstance(im, dict) and im.get("filename") == item.get("filename") and (im.get("subfolder") or "") == (item.get("subfolder") or ""):
                    return entry
    return None


async def recipe_for(item: dict, prompt_id: str | None = None) -> dict:
    """-> {recipe, thumb, items}: a recipe from an image a run made, ready to save."""
    from .recipes import plan_recipe
    full = image_path(item)
    if not os.path.isfile(full):
        raise recipe_parse.NoMetadata("That image isn't in ComfyUI's folder any more.")
    data = await asyncio.to_thread(lambda: open(full, "rb").read())
    try:
        rec = await asyncio.to_thread(recipe_parse.from_image, data, item["filename"])
    except recipe_parse.NoMetadata:
        rec = None
    if rec is None:  # saved without generation data: the run's own prompt and workflow
        entry = _run_for(item, prompt_id)
        prompt, wf = _run_parts(entry) if entry else (None, {})
        if not prompt:
            raise recipe_parse.NoMetadata("No generation data in this image, and its run isn't in ComfyUI's history any more.")
        rec = recipe_parse.parse_comfy_prompt(prompt)
        rec["comfy"] = {**(rec.get("comfy") or {}), "prompt": prompt, **({"workflow": wf} if wf.get("nodes") else {})}
        rec["source"]["filename"] = item["filename"]
    rec["source"]["output"] = {"filename": item["filename"], "subfolder": item.get("subfolder") or "", "type": item.get("type") or "output"}
    thumb = await asyncio.to_thread(recipe_store.make_thumbnail, data)
    return {"recipe": rec, "thumb": recipe_store.thumb_data_url(thumb), **(await plan_recipe(rec))}

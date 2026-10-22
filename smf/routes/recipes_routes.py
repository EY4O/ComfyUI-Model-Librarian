"""Recipes: analyze images, videos and links; the recipe store."""
from __future__ import annotations

import asyncio
import os

from aiohttp import web

from .. import recipes, recipe_parse, recipe_store, runs, videometa
from .common import P, _err, _body


def register(routes: web.RouteTableDef) -> None:
    @routes.post(P + "/recipe/link")
    async def recipe_link(request):
        """Use a file you have for a recipe item (remembered), or {file: null} to forget the link."""
        b = await _body(request)
        if not isinstance(b.get("item"), dict):
            return _err("item required")
        try:
            return web.json_response({"item": await asyncio.to_thread(recipes.link_item, b["item"], b.get("file") or None)})
        except ValueError as ex:
            return _err(str(ex))

    @routes.post(P + "/recipe/link-url")
    async def recipe_link_url(request):
        """A pasted page or download link for a recipe item -> its planned download."""
        b = await _body(request)
        url = str(b.get("url") or "").strip()
        if not isinstance(b.get("item"), dict) or not url.startswith("https://"):
            return _err("Paste an https:// link")
        try:
            return web.json_response({"item": await recipes.item_from_url(b["item"], url)})
        except ValueError as ex:
            return _err(str(ex))
        except Exception as ex:
            return _err(f"Couldn't read that link: {ex}", 502)

    @routes.post(P + "/recipe/plan")
    async def recipe_plan(request):
        b = await _body(request)
        if isinstance(b.get("recipe"), dict):
            rec = recipe_parse.normalize(b["recipe"])  # recipes from elsewhere (e.g. Prompto) may be partial
            return web.json_response({**(await recipes.plan_recipe(rec)), "recipe": rec})
        loras = b.get("loras") if isinstance(b.get("loras"), list) else []
        return web.json_response(await recipes.plan(loras, b.get("checkpoint")))

    @routes.post(P + "/recipe/from-lm")
    async def recipe_from_lm(request):
        """A LoRA Manager recipe (as /api/lm/recipes lists it) -> recipe/1."""
        b = await _body(request)
        if not isinstance(b.get("item"), dict):
            return _err("item required")
        return web.json_response({"recipe": recipe_parse.from_lm_recipe(b["item"])})

    async def _analyze_video_upload(field) -> web.Response:
        """Stream an uploaded video to a temporary file (videos are big) and read it."""
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(field.filename or "")[1] or ".mp4")
        total = 0
        try:
            with os.fdopen(fd, "wb") as out:
                while True:
                    chunk = await field.read_chunk(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > recipes.MAX_VIDEO:
                        return _err(f"video too large (max {recipes.MAX_VIDEO // (1024 ** 3)} GB)", 413)
                    out.write(chunk)
            return web.json_response(await recipes.analyze_video(tmp, field.filename))
        except recipe_parse.NoMetadata as ex:
            return _err(str(ex), 422)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    @routes.post(P + "/recipe/analyze")
    async def recipe_analyze(request):
        """An uploaded image (multipart field 'image') or JSON {url} -> draft recipe + plan."""
        try:
            if request.content_type.startswith("multipart/"):
                reader = await request.multipart()
                field = await reader.next()
                while field is not None and field.name != "image":
                    field = await reader.next()
                if field is None:
                    return _err("no image uploaded")
                if videometa.is_video(field.filename, field.headers.get("Content-Type")):
                    return await _analyze_video_upload(field)
                data = bytearray()
                while chunk := await field.read_chunk(1 << 20):
                    data += chunk
                    if len(data) > recipes.MAX_IMAGE:
                        return _err("image too large")
                return web.json_response(await recipes.analyze_image(bytes(data), field.filename))
            b = await _body(request)
            if not b.get("url"):
                return _err("send an image or a url")
            return web.json_response(await recipes.analyze_url(str(b["url"]).strip()))
        except recipe_parse.NoMetadata as ex:
            return _err(str(ex), 422)
        except Exception as ex:  # the site didn't answer, or answered with an error
            return _err(f"Couldn't read that link: {ex}", 502)

    @routes.get(P + "/recipes")
    async def recipes_list(request):
        return web.json_response({"recipes": await asyncio.to_thread(recipe_store.list_recipes)})

    @routes.post(P + "/recipes")
    async def recipes_save(request):
        b = await _body(request)
        if not isinstance(b.get("recipe"), dict):
            return _err("recipe required")
        r = await asyncio.to_thread(recipe_store.save, b["recipe"], b.get("thumb"))
        out = (r.get("source") or {}).get("output")
        warning = None
        if b.get("keep_image") and isinstance(out, dict):  # a full-size copy of the run's image, kept with the recipe
            try:
                if await asyncio.to_thread(recipe_store.keep_image, r["id"], runs.image_path(out)):
                    r = await asyncio.to_thread(recipe_store.get, r["id"])
                else:
                    warning = "Saved, but the full-size image couldn't be kept (it isn't there any more)."
            except Exception as ex:  # the recipe is saved either way: say so, don't fail it
                warning = f"Saved, but the full-size image couldn't be kept ({ex})."
        return web.json_response({"recipe": r, **({"warning": warning} if warning else {})})

    @routes.get(P + "/runs/images")
    async def runs_images(request):
        """Images ComfyUI's recent runs made, newest first (of one workflow, by its id; or one output node)."""
        q = request.query
        try:
            limit = max(1, min(48, int(q.get("limit", "12"))))
        except ValueError:
            limit = 12
        imgs = await asyncio.to_thread(runs.recent_images, q.get("workflow_id") or None, q.get("node") or None, limit)
        return web.json_response({"images": imgs})

    @routes.post(P + "/recipe/from-output")
    async def recipe_from_output(request):
        """A recipe from an image a run made (in ComfyUI's output or temp folder), ready to save."""
        b = await _body(request)
        item = {k: b.get(k) for k in ("filename", "subfolder", "type")}
        try:
            return web.json_response(await runs.recipe_for(item, b.get("prompt_id")))
        except ValueError as ex:
            return _err(str(ex), 422)

    @routes.get(P + "/recipes/{rid}")
    async def recipes_get(request):
        try:
            r = recipe_store.get(request.match_info["rid"])
        except ValueError:
            r = None
        return web.json_response({"recipe": r}) if r else _err("not found", 404)

    @routes.patch(P + "/recipes/{rid}")
    async def recipes_update(request):
        try:
            r = await asyncio.to_thread(recipe_store.update, request.match_info["rid"], await _body(request))
        except ValueError:
            r = None
        return web.json_response({"recipe": r}) if r else _err("not found", 404)

    @routes.delete(P + "/recipes/{rid}")
    async def recipes_delete(request):
        try:
            ok = await asyncio.to_thread(recipe_store.delete, request.match_info["rid"])
        except ValueError:
            ok = False
        return web.json_response({"ok": ok}) if ok else _err("not found", 404)

    @routes.post(P + "/recipes/{rid}/picture")
    async def recipes_picture(request):
        """Fetch a saved recipe's picture again from the link it came from."""
        try:
            r = recipe_store.get(request.match_info["rid"])
        except ValueError:
            r = None
        if not r:
            return _err("not found", 404)
        url = (r.get("source") or {}).get("url")
        if not url:
            return _err("This recipe wasn't saved from a link, so there's nowhere to fetch its picture from.", 422)
        try:
            thumb = await recipes.picture_from(url)
        except Exception:
            thumb = None
        if not thumb:
            return _err("Couldn't get the picture from its link: it may have been removed, or the site didn't answer.", 422)
        await asyncio.to_thread(recipe_store.set_thumb, r["id"], thumb)
        return web.json_response({"recipe": recipe_store.summary(r)})

    @routes.get(P + "/recipes/{rid}/image")
    async def recipes_image(request):
        try:
            p = await asyncio.to_thread(recipe_store.image_path, request.match_info["rid"])
        except ValueError:
            p = None
        if not p:
            return _err("The full image isn't kept with this recipe, and the original has moved or been deleted.", 404)
        return web.FileResponse(p, headers={"Cache-Control": "max-age=3600"})

    @routes.get(P + "/recipes/{rid}/thumb")
    async def recipes_thumb(request):
        try:
            p = recipe_store.thumb_path(request.match_info["rid"])
        except ValueError:
            p = None
        if not p:
            return web.Response(status=404)
        return web.FileResponse(p, headers={"Content-Type": "image/webp", "Cache-Control": "max-age=3600"})

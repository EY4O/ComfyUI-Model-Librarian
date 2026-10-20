"""Recipe parsing without LoRA Manager: image metadata formats -> shared recipe format,
plus planning, the recipe store, link analysis and the HTTP routes."""
import asyncio
import json
import os
import shutil
import struct
import sys
import zlib

import test_shared as T

check = T.check


# ---------------------------------------------------------------- image builders
def png(chunks):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    for kind, k, v in chunks:
        if kind == "tEXt":
            out += chunk(b"tEXt", k.encode("latin-1") + b"\0" + v.encode("latin-1"))
        elif kind == "zTXt":
            out += chunk(b"zTXt", k.encode("latin-1") + b"\0\0" + zlib.compress(v.encode("latin-1")))
        elif kind == "iTXtz":
            out += chunk(b"iTXt", k.encode() + b"\0\x01\0\0\0" + zlib.compress(v.encode("utf-8")))
        elif kind == "iTXt":
            out += chunk(b"iTXt", k.encode() + b"\0\0\0\0\0" + v.encode("utf-8"))
    return out + chunk(b"IDAT", zlib.compress(b"\0\0\0\0\0")) + chunk(b"IEND", b"")


def tiff_user_comment(text, encoding="unicode"):
    data = b"UNICODE\0" + text.encode("utf-16-be") if encoding == "unicode" else b"ASCII\0\0\0" + text.encode()
    t = b"MM\x00\x2a" + struct.pack(">I", 8)
    t += struct.pack(">H", 1) + struct.pack(">HHII", 0x8769, 4, 1, 26) + struct.pack(">I", 0)
    t += struct.pack(">H", 1) + struct.pack(">HHII", 0x9286, 7, len(data), 44) + struct.pack(">I", 0)
    return t + data


def jpeg(text):
    seg = b"Exif\0\0" + tiff_user_comment(text)
    return b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(seg) + 2) + seg + b"\xff\xda\x00\x02" + b"\xff\xd9"


def webp(text):
    t = tiff_user_comment(text, "ascii")
    body = b"WEBP" + b"EXIF" + struct.pack("<I", len(t)) + t + (b"\0" if len(t) & 1 else b"")
    return b"RIFF" + struct.pack("<I", len(body)) + body


A1111 = ("masterpiece, 1girl, lighthouse <lora:watercolor_v3:0.7:0.5> <lora:detail_slider:-1.5>\n"
         "Negative prompt: blurry, lowres\n"
         'Steps: 28, Sampler: DPM++ 2M Karras, CFG scale: 5.5, Seed: 81723, Size: 832x1216, Model hash: 1a2b3c4d5e, '
         'Model: illustriousXL_v20, Clip skip: 2, Lora hashes: "watercolor_v3: aaaa1111bbbb, detail_slider: cccc2222dddd", '
         'Hashes: {"model": "1a2b3c4d5e", "lora:watercolor_v3": "aaaa1111bb"}, '
         'Civitai resources: [{"type":"checkpoint","modelVersionId":999,"modelName":"Illustrious XL"},'
         '{"type":"lora","weight":0.7,"modelVersionId":111,"modelName":"Watercolor Wash","modelVersionName":"v3"}], Version: f2.0')

COMFY = {
    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "Illustrious\\illustriousXL_v20.safetensors"}},
    "2": {"class_type": "LoraLoader", "inputs": {"model": ["1", 0], "clip": ["1", 1], "lora_name": "Illustrious\\watercolor_v3.safetensors", "strength_model": 0.7, "strength_clip": 0.5}},
    "3": {"class_type": "Power Lora Loader (rgthree)", "inputs": {"model": ["2", 0], "clip": ["2", 1],
          "lora_1": {"on": True, "lora": "soft_pastel.safetensors", "strength": 0.55, "strengthTwo": 0.4},
          "lora_2": {"on": False, "lora": "off_one.safetensors", "strength": 1}}},
    "4": {"class_type": "CLIPSetLastLayer", "inputs": {"clip": ["3", 1], "stop_at_clip_layer": -2}},
    "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": "a lighthouse at dusk, watercolor"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": "blurry"}},
    "7": {"class_type": "EmptyLatentImage", "inputs": {"width": 832, "height": 1216, "batch_size": 1}},
    "8": {"class_type": "Seed (rgthree)", "inputs": {"seed": 123456}},
    "9": {"class_type": "KSampler", "inputs": {"model": ["3", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0],
          "seed": ["8", 0], "steps": 28, "cfg": 5.5, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0}},
    "10": {"class_type": "VAELoader", "inputs": {"vae_name": "sdxl_vae.safetensors"}},
    "11": {"class_type": "KSampler", "inputs": {"model": ["3", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["9", 0],
           "seed": 5, "steps": 12, "cfg": 4, "sampler_name": "euler", "scheduler": "normal", "denoise": 0.4}},
}

FLUX = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-dev.safetensors", "weight_dtype": "default"}},
    "2": {"class_type": "Lora Loader (LoraManager)", "inputs": {"model": ["1", 0], "text": "<lora:flux_detail:0.9>",
          "loras": {"__value__": [{"name": "flux_detail", "strength": 0.9, "clipStrength": 0.8, "active": True},
                                  {"name": "flux_off", "strength": 1, "active": False}]}}},
    "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "a red fox in snow"}},
    "4": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["3", 0], "guidance": 3.5}},
    "5": {"class_type": "BasicGuider", "inputs": {"model": ["2", 0], "conditioning": ["4", 0]}},
    "6": {"class_type": "RandomNoise", "inputs": {"noise_seed": 42}},
    "7": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
    "8": {"class_type": "BasicScheduler", "inputs": {"model": ["2", 0], "scheduler": "simple", "steps": 20, "denoise": 1.0}},
    "9": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
    "10": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["6", 0], "guider": ["5", 0], "sampler": ["7", 0], "sigmas": ["8", 0], "latent_image": ["9", 0]}},
}

WORKFLOW = {"nodes": [
    {"id": 1, "type": "CheckpointLoaderSimple", "widgets_values": ["ponyDiffusionV6XL.safetensors"], "inputs": []},
    {"id": 2, "type": "CLIPTextEncode", "widgets_values": ["score_9, a cat"], "inputs": []},
    {"id": 3, "type": "CLIPTextEncode", "widgets_values": ["score_1"], "inputs": []},
    {"id": 4, "type": "KSampler", "widgets_values": [77, "fixed", 25, 7, "euler_ancestral", "normal", 1],
     "inputs": [{"name": "positive", "type": "CONDITIONING", "link": 10}, {"name": "negative", "type": "CONDITIONING", "link": 11}]},
    {"id": 5, "type": "LoraLoader", "widgets_values": ["cute_style.safetensors", 0.6, 0.6], "inputs": []},
    {"id": 6, "type": "LoraLoader", "mode": 4, "widgets_values": ["bypassed.safetensors", 1, 1], "inputs": []},
], "links": [[10, 2, 0, 4, 1, "CONDITIONING"], [11, 3, 0, 4, 2, "CONDITIONING"]]}


def main():
    base, user = T.fake_install("Recipes")
    for d in ("Illustrious", ""):
        os.makedirs(os.path.join(T.LORA, d), exist_ok=True)
    smf = T.load_smf(base, user)
    rp = smf.recipe_parse
    lora = lambda r, stem: next((l for l in r["loras"] if (l.get("file") or "").lower().endswith(stem.lower()) or l.get("name") == stem), None)  # noqa

    # ---- shared recipe/1 fixtures (the same file is tested by Prompto's JS parser)
    def partial(actual, expected, path=""):
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                return f"{path}: expected an object, got {actual!r}"
            for k, v in expected.items():
                err = partial(actual.get(k), v, f"{path}.{k}" if path else k)
                if err:
                    return err
        elif isinstance(expected, list):
            if not isinstance(actual, list) or len(actual) != len(expected):
                return f"{path}: expected {len(expected)} items, got {actual!r}"
            for i, (a, e) in enumerate(zip(actual, expected)):
                err = partial(a, e, f"{path}[{i}]")
                if err:
                    return err
        elif actual != expected:
            return f"{path}: expected {expected!r}, got {actual!r}"
        return None
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "recipe1.json"), encoding="utf-8") as f:
        fixtures = json.load(f)
    for case in fixtures["cases"]:
        got = rp.from_civitai_item(case["civitai"], case.get("page")) if "civitai" in case else rp.from_text(case["text"])
        err = partial(got, case["expect"])
        try:
            json.dumps(got, allow_nan=False)
        except ValueError:
            err = err or "not strict JSON"
        check(err is None, f"fixture: {case['name']}" + (f" -- {err}" if err else ""))

    # ---- low-level readers
    meta = smf.imagemeta.read(png([("tEXt", "a", "plain"), ("zTXt", "b", "zipped"), ("iTXtz", "c", "üñí zipped"), ("iTXt", "d", "ütf")]))
    check(meta["format"] == "png" and meta["text"] == {"a": "plain", "b": "zipped", "c": "üñí zipped", "d": "ütf"}, "PNG tEXt / zTXt / iTXt (compressed + plain)")
    check(smf.imagemeta.read(jpeg("hello ✓"))["text"].get("UserComment") == "hello ✓", "JPEG EXIF UserComment (UTF-16)")
    check(smf.imagemeta.read(webp("ascii text"))["text"].get("UserComment") == "ascii text", "WebP EXIF UserComment (ASCII)")

    # ---- A1111 (JPEG) with hashes + Civitai resources
    r = rp.from_image(jpeg(A1111), "dusk.jpg")
    check(r["format"] == "a1111" and r["prompt"]["positive"] == "masterpiece, 1girl, lighthouse", "A1111: prompt without <lora> tags")
    check(r["prompt"]["negative"] == "blurry, lowres", "A1111: negative prompt")
    s = r["settings"]
    check((s["sampler"], s["scheduler"], s["steps"], s["cfg"], s["seed"], s["width"], s["height"], s["clip_skip"]) ==
          ("dpmpp_2m", "karras", 28, 5.5, 81723, 832, 1216, 2), f"A1111: settings incl. sampler mapping ({s})")
    m = r["model"]
    check(m["file"] == "illustriousXL_v20" and m["hash"] == "1a2b3c4d5e" and m["civitai_version_id"] == 999, f"A1111: model name + hash + Civitai version ({m})")
    w = lora(r, "watercolor_v3")
    check(w and w["weight"] == 0.7 and w["clip_weight"] == 0.5 and w["hash"] == "aaaa1111bbbb" and w["civitai_version_id"] == 111,
          f"A1111: LoRA tag + Lora hashes + Civitai resource merged into one ({w})")
    check(lora(r, "detail_slider")["weight"] == -1.5 and len(r["loras"]) == 2, "A1111: negative LoRA weight kept, no duplicates")
    check(r["title"] == "dusk" and r["source"]["filename"] == "dusk.jpg", "title from file name")

    # ---- ComfyUI PNG (prompt graph + A1111 text with resources)
    r = rp.from_image(png([("tEXt", "prompt", json.dumps(COMFY)), ("tEXt", "workflow", json.dumps(WORKFLOW)), ("tEXt", "parameters", A1111)]))
    s = r["settings"]
    check(r["format"] == "comfyui" and r["prompt"] == {"positive": "a lighthouse at dusk, watercolor", "negative": "blurry"}, "ComfyUI: prompts traced from the sampler")
    check((s["seed"], s["steps"], s["cfg"], s["sampler"], s["scheduler"], s["denoise"]) == (123456, 28, 5.5, "dpmpp_2m", "karras", 1.0),
          f"ComfyUI: first-pass sampler settings, seed via linked node ({s})")
    check((s["width"], s["height"], s["clip_skip"]) == (832, 1216, 2), "ComfyUI: size + clip skip")
    check(r["model"]["file"] == "Illustrious\\illustriousXL_v20.safetensors" and r["model"]["type"] == "checkpoint", "ComfyUI: checkpoint traced through LoRA loaders")
    check(r["model"]["civitai_version_id"] == 999 and r["vae"]["file"] == "sdxl_vae.safetensors", "ComfyUI: Civitai version from the A1111 text; VAE")
    w, sp = lora(r, "watercolor_v3.safetensors"), lora(r, "soft_pastel.safetensors")
    check(w["weight"] == 0.7 and w["clip_weight"] == 0.5 and w["civitai_version_id"] == 111, "ComfyUI: LoraLoader strengths + enriched version id")
    check(sp and sp["weight"] == 0.55 and sp["clip_weight"] == 0.4 and not lora(r, "off_one.safetensors"), "ComfyUI: rgthree rows (off rows skipped)")
    check(isinstance(r["comfy"].get("prompt"), dict) and isinstance(r["comfy"].get("workflow"), dict), "ComfyUI: graphs kept for 'open as workflow'")

    # ---- ComfyUI writes NaN into PNG graphs (e.g. "is_changed": NaN); browsers can't parse it
    nan_graph = json.dumps(COMFY)[:-1] + ', "30": {"class_type": "Widget To String", "inputs": {}, "is_changed": NaN}}'
    r = rp.from_image(png([("tEXt", "prompt", nan_graph)]))
    try:
        json.dumps(r, allow_nan=False)
        check(r["settings"]["steps"] == 28, "NaN in a ComfyUI graph -> null (strict JSON)")
    except ValueError:
        check(False, "NaN in a ComfyUI graph -> null (strict JSON)")

    # ---- settings routed through a parameter node with several outputs (Image Saver style)
    g = json.loads(json.dumps(COMFY))
    g["20"] = {"class_type": "Input Parameters (Image Saver)", "inputs": {"seed": ["8", 0], "steps": 30, "cfg": 6.0, "sampler": "euler_ancestral", "scheduler": "normal", "denoise": 0.9}}
    g["21"] = {"class_type": "easy showAnything", "inputs": {"text": "euler_ancestral", "anything": ["20", 3]}}
    g["9"]["inputs"].update(steps=["20", 1], cfg=["20", 2], sampler_name=["21", 0], scheduler=["20", 4], denoise=["20", 5])
    s = rp.parse_comfy_prompt(g)["settings"]
    check((s["seed"], s["steps"], s["cfg"], s["sampler"], s["scheduler"], s["denoise"]) == (123456, 30, 6.0, "euler_ancestral", "normal", 0.9),
          f"ComfyUI: settings from a multi-output parameter node, by name and slot ({s})")

    # ---- Flux / SamplerCustomAdvanced + LoRA Manager loader
    r = rp.parse_comfy_prompt(FLUX)
    s = r["settings"]
    check(r["prompt"]["positive"] == "a red fox in snow" and r["model"]["type"] == "unet", "Flux: prompt through FluxGuidance/BasicGuider; UNet model")
    check((s["seed"], s["steps"], s["sampler"], s["scheduler"], s["width"]) == (42, 20, "euler", "simple", 1024), f"Flux: noise/sampler/scheduler nodes ({s})")
    fd = lora(r, "flux_detail")
    check(fd and fd["weight"] == 0.9 and fd["clip_weight"] == 0.8 and not lora(r, "flux_off") and len(r["loras"]) == 1,
          "LoRA Manager loader list: active entries, list and text not double-counted")

    # ---- workflow-only PNG (compressed iTXt)
    r = rp.from_image(png([("iTXtz", "workflow", json.dumps(WORKFLOW))]))
    check(r["format"] == "comfyui-workflow" and r["prompt"] == {"positive": "score_9, a cat", "negative": "score_1"}, "workflow-only: prompts via links")
    check(r["model"]["file"] == "ponyDiffusionV6XL.safetensors" and r["settings"]["seed"] == 77 and r["settings"]["steps"] == 25, "workflow-only: model + KSampler widgets")
    check([l["file"] for l in r["loras"]] == ["cute_style.safetensors"], "workflow-only: bypassed loaders skipped")

    # ---- other generators
    r = rp.from_image(png([("tEXt", "Software", "NovelAI"), ("tEXt", "Source", "NovelAI Diffusion V4"),
                           ("tEXt", "Comment", json.dumps({"prompt": "1girl", "uc": "bad", "steps": 28, "scale": 5, "seed": 9, "width": 832, "height": 1216, "sampler": "k_euler"}))]))
    check(r["format"] == "novelai" and r["prompt"]["positive"] == "1girl" and r["model"]["downloadable"] is False, "NovelAI: prompt; model marked not downloadable")
    r = rp.from_image(png([("tEXt", "invokeai_metadata", json.dumps({"positive_prompt": "castle", "negative_prompt": "ugly", "seed": 3, "steps": 30, "cfg_scale": 7,
                           "width": 1024, "height": 768, "scheduler": "dpmpp_2m", "model": {"name": "juggernautXL", "hash": "blake3:abcd"}, "loras": [{"model": {"name": "add_detail"}, "weight": 0.5}]}))]))
    check(r["format"] == "invokeai" and r["model"]["name"] == "juggernautXL" and lora(r, "add_detail")["weight"] == 0.5, "InvokeAI metadata")
    r = rp.from_image(png([("tEXt", "parameters", json.dumps({"sui_image_params": {"prompt": "forest", "negativeprompt": "", "model": "OfficialStableDiffusion/sd_xl_base_1.0",
                           "seed": 1, "steps": 20, "cfgscale": 6, "width": 1024, "height": 1024, "loras": ["moody_forest"], "loraweights": [0.8]}}))]))
    check(r["format"] == "swarmui" and lora(r, "moody_forest")["weight"] == 0.8 and r["model"]["file"].endswith("sd_xl_base_1.0"), "SwarmUI sui_image_params")
    r = rp.from_image(png([("tEXt", "parameters", json.dumps({"Prompt": "sunset", "Negative Prompt": "", "Base Model": "juggernautXL_v8.safetensors",
                           "Steps": 30, "Guidance Scale": 4, "Seed": 5, "Resolution": "(1152, 896)", "LoRA 1": "sdxl_offset:0.1"}))]))
    check(r["format"] == "fooocus" and r["settings"]["width"] == 1152 and lora(r, "sdxl_offset")["weight"] == 0.1, "Fooocus parameters")
    try:
        rp.from_image(png([("tEXt", "Title", "nothing here")]))
        check(False, "no metadata -> NoMetadata")
    except rp.NoMetadata:
        check(True, "no metadata -> NoMetadata")

    # ---- Civitai API item: LoRA listed as tag + resource + civitaiResource -> one entry
    item = {"id": 555, "url": "https://image.civitai.com/x/original=true/555.jpeg", "width": 832, "height": 1216, "baseModel": "Illustrious",
            "meta": {"prompt": "a lighthouse, <lora:watercolor_v3:0.8>", "negativePrompt": "blurry", "steps": 28, "sampler": "Euler a", "cfgScale": 5, "seed": 7,
                     "Size": "832x1216", "Model": "illustriousXL_v20", "Model hash": "1a2b3c4d5e",
                     "resources": [{"name": "Watercolor Wash", "type": "lora", "weight": 0.8, "hash": "aaaa1111bb"}, {"name": "illustriousXL_v20", "type": "model", "hash": "1a2b3c4d5e"}],
                     "civitaiResources": [{"type": "checkpoint", "modelVersionId": 999}, {"type": "lora", "weight": 0.8, "modelVersionId": 111, "modelVersionName": "v3"}]}}
    r = rp.from_civitai_item(item)
    check(r["format"] == "civitai" and r["base_model"] == "Illustrious" and r["source"]["url"] == "https://civitai.com/images/555", "Civitai: format, base model, source")
    check(len(r["loras"]) == 1, f"Civitai: one LoRA, not three ({[l.get('name') or l.get('file') for l in r['loras']]})")
    w = r["loras"][0]
    check(w["file"] == "watercolor_v3" and w["civitai_version_id"] == 111 and w["hash"] == "aaaa1111bb" and w["weight"] == 0.8, f"Civitai: file + version id + hash ({w})")
    check(r["model"]["civitai_version_id"] == 999 and r["model"]["hash"] == "1a2b3c4d5e" and r["settings"]["sampler"] == "euler_ancestral", "Civitai: model version + hash; sampler mapped")

    # ---- planning (no LoRA Manager): local by file name -> ComfyUI name; missing -> exact CivitAI file
    open(os.path.join(T.LORA, "Illustrious", "watercolor_v3.safetensors"), "wb").write(b"w")

    async def fake_get_json(url, params=None, timeout=30):
        if "/model-versions/999" in url:
            return {"id": 999, "modelId": 9, "name": "v2.0", "baseModel": "Illustrious", "model": {"name": "Illustrious XL", "type": "Checkpoint"},
                    "files": [{"name": "illustriousXL_v20.safetensors", "primary": True, "sizeKB": 6, "hashes": {"SHA256": "AB" * 32, "AutoV2": "1A2B3C4D5E"},
                               "downloadUrl": "https://civitai.com/api/download/models/999"}]}
        if "/images?imageId=555" in url:
            return {"items": [item]}
        if "/images?postId=77" in url:
            return {"items": [{"id": 1, "url": "https://image.civitai.com/x/width=1024/1.jpeg", "meta": {"prompt": "a"}}, {"id": 2, "url": "u", "meta": None}]}
        return None
    smf.net.get_json = fake_get_json

    async def no_resolve(*a, **k):
        return []
    smf.sources.resolve = no_resolve
    plan = asyncio.run(smf.recipes.plan_recipe(r))
    items = {i["kind"]: i for i in plan["items"]}
    lr = items["lora"]
    check(lr["status"] == "present" and lr["comfy_name"] == os.path.join("Illustrious", "watercolor_v3.safetensors") and lr["weight"] == 0.8,
          f"plan: installed LoRA found, with its ComfyUI name ({lr['comfy_name']})")
    ck = items["checkpoint"]
    check(ck["status"] == "missing" and ck["download"]["rel"] == "Illustrious/illustriousXL_v20.safetensors" and ck["download"]["sha256"] == "ab" * 32,
          "plan: missing checkpoint -> exact CivitAI file, filed under Illustrious/")

    # ---- an image that arrives in pieces is read whole (a cut-off one made grey thumbnails)
    from aiohttp import web

    async def slow_image():
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.effect_noise((600, 800), 80).convert("RGB").save(buf, "JPEG", quality=95)
        body = buf.getvalue()

        async def handler(request):
            res = web.StreamResponse(headers={"Content-Type": "image/jpeg", "Content-Length": str(len(body))})
            await res.prepare(request)
            for i in range(0, len(body), 8192):
                await res.write(body[i:i + 8192])
                await asyncio.sleep(0.01)
            return res

        async def short(request):  # says more than it sends
            res = web.StreamResponse(headers={"Content-Type": "image/jpeg", "Content-Length": str(len(body))})
            await res.prepare(request)
            await res.write(body[:5000])
            request.transport.close()
            return res
        app = web.Application()
        app.router.add_get("/img.jpg", handler)
        app.router.add_get("/short.jpg", short)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        smf.net._session = None
        try:
            whole = await smf.recipes._fetch_image(f"http://127.0.0.1:{port}/img.jpg")
            cut = await smf.recipes._fetch_image(f"http://127.0.0.1:{port}/short.jpg")
        finally:
            await smf.net.session().close()
            smf.net._session = None
            await runner.cleanup()
        return body, whole, cut
    body, whole, cut = asyncio.run(slow_image())
    check(whole == body, f"fetch: an image sent in pieces is read whole ({len(whole or b'')} of {len(body)} bytes)")
    check(cut is None, "fetch: an image cut off before its stated length is refused")

    # ---- link analysis
    async def fake_fetch(url):
        return png([("tEXt", "parameters", A1111)]) if "direct" in url else None
    smf.recipes._fetch_image = fake_fetch
    a = asyncio.run(smf.recipes.analyze_url("https://civitai.red/images/555"))
    check(a["recipe"]["format"] == "civitai" and a["recipe"]["source"]["url"] == "https://civitai.red/images/555" and a["items"], "link: CivitAI image page (.red kept)")
    a = asyncio.run(smf.recipes.analyze_url("https://civitai.com/posts/77"))
    check([c["url"] for c in a["choices"]] == ["https://civitai.com/images/1", "https://civitai.com/images/2"], "link: CivitAI post -> choose an image")
    a = asyncio.run(smf.recipes.analyze_url("https://example.org/direct.png"))
    check(a["recipe"]["format"] == "a1111", "link: direct image file is read")
    for bad in ("http://example.org/a.png", "https://127.0.0.1/a.png", "https://192.168.1.5/x.png", "https://localhost/x.png"):
        try:
            asyncio.run(smf.recipes.analyze_url(bad))
            check(False, f"refused {bad}")
        except rp.NoMetadata:
            check(True, f"refused non-public link {bad}")

    # ---- store
    st = smf.recipe_store
    thumb = st.thumb_data_url(st.make_thumbnail(png([("tEXt", "x", "y")])) or b"RIFFxxxxWEBP")
    saved = st.save(r, thumb)
    check(len(saved["id"]) == 12 and os.path.isfile(st.thumb_path(saved["id"])), "store: saved with id + thumbnail")
    check([x["id"] for x in st.list_recipes()] == [saved["id"]] and st.list_recipes()[0]["lora_count"] == 1, "store: listed with summary")
    legacy = dict(r, id=None, notes=float("nan"))  # a file written before cleaning, or a NaN from elsewhere
    nid = st.save(legacy)["id"]
    try:
        json.dumps(st.get(nid), allow_nan=False)
        check(True, "store: non-finite numbers never saved or returned")
    except ValueError:
        check(False, "store: non-finite numbers never saved or returned")
    st.delete(nid)
    st.update(saved["id"], {"title": "Lighthouse", "tags": ["watercolor", " ", "dusk"], "fav": 1, "prompt": "ignored"})
    g = st.get(saved["id"])
    check(g["title"] == "Lighthouse" and g["tags"] == ["watercolor", "dusk"] and g["fav"] is True and g["prompt"]["positive"] == r["prompt"]["positive"],
          "store: only title/tags/notes/fav editable")
    check(st.delete(saved["id"]) and st.get(saved["id"]) is None and os.path.isfile(os.path.join(st.folder(), "_deleted", saved["id"] + ".json")),
          "store: delete moves to _deleted")
    check(st.get("../../etc") is None, "store: path-like id reads nothing")
    try:
        st.delete("../../etc")
        check(False, "store: path-like ids refused")
    except ValueError:
        check(True, "store: path-like ids refused")

    # ---- thumbnails of any type are stored as WebP; LoRA Manager link kept
    import base64
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (900, 600), (200, 80, 80)).save(buf, "PNG")
    png_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    lmrec = st.save(dict(r, id=None, lm_id="lm-123"), png_url)
    tb = open(st.thumb_path(lmrec["id"]), "rb").read()
    check(tb[:4] == b"RIFF" and tb[8:12] == b"WEBP" and max(Image.open(io.BytesIO(tb)).size) == st.THUMB_PX, "store: a PNG thumbnail is re-encoded as a 512px WebP")
    check(next(x for x in st.list_recipes() if x["id"] == lmrec["id"])["lm_id"] == "lm-123", "store: summary carries the LoRA Manager id")
    st.update(lmrec["id"], {"lm_id": ""})
    check(st.get(lmrec["id"]).get("lm_id") is None, "store: lm_id can be cleared")
    st.delete(lmrec["id"])

    # ---- LoRA Manager's stored recipes -> recipe/1
    lm_item = {"id": "f00d", "title": "Lighthouse (LM)", "base_model": "Illustrious", "tags": ["dusk"], "created_date": 1791800000.0,
               "source_path": "https://civitai.com/images/555", "file_url": "/api/lm/recipes/f00d/image",
               "gen_params": {"prompt": "a lighthouse", "negative_prompt": "blurry", "steps": 28, "sampler": "DPM++ 2M Karras",
                              "cfg_scale": 5.5, "seed": 7, "size": "832x1216", "clip_skip": 2},
               "checkpoint": {"name": "Illustrious XL", "file_name": "illustriousXL_v20", "hash": "1A2B", "modelVersionId": 999},
               "loras": [{"file_name": "watercolor_v3", "hash": "AAAA", "strength": 0.8, "modelVersionId": 111, "modelName": "Watercolor Wash",
                          "modelVersionName": "v3", "isDeleted": False, "exclude": False},
                         {"file_name": "skipped", "strength": 1, "exclude": True}]}
    lr = rp.from_lm_recipe(lm_item)
    check(lr["format"] == "lora-manager" and lr["lm_id"] == "f00d" and lr["title"] == "Lighthouse (LM)" and lr["tags"] == ["dusk"],
          "LM recipe: title, tags, id")
    check(lr["prompt"] == {"positive": "a lighthouse", "negative": "blurry"} and lr["settings"]["sampler"] == "dpmpp_2m"
          and lr["settings"]["scheduler"] == "karras" and (lr["settings"]["width"], lr["settings"]["height"]) == (832, 1216), "LM recipe: prompts and settings")
    check(lr["model"]["file"] == "illustriousXL_v20" and lr["model"]["hash"] == "1a2b" and lr["model"]["civitai_version_id"] == 999,
          "LM recipe: checkpoint reference")
    check(len(lr["loras"]) == 1 and lr["loras"][0]["civitai_version_id"] == 111 and lr["loras"][0]["weight"] == 0.8
          and lr["loras"][0]["display_name"] == "Watercolor Wash" and lr["source"]["url"] == "https://civitai.com/images/555",
          "LM recipe: LoRAs with hash and version id (excluded ones left out), source link")
    check("lm_id" in rp.normalize(lr), "normalize keeps the LoRA Manager id")

    # ---- HTTP: multipart analyze
    from aiohttp import web, FormData, ClientSession

    async def http():
        routes = web.RouteTableDef()
        smf.routes.register(routes)
        app = web.Application()
        app.add_routes(routes)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            async with ClientSession() as s:
                fd = FormData()
                fd.add_field("image", jpeg(A1111), filename="up.jpg", content_type="image/jpeg")
                async with s.post(f"http://127.0.0.1:{port}/sm-fetcher/recipe/analyze", data=fd) as resp:
                    ok = (resp.status, await resp.json())
                fd = FormData()
                fd.add_field("image", b"not an image", filename="x.bin")
                async with s.post(f"http://127.0.0.1:{port}/sm-fetcher/recipe/analyze", data=fd) as resp:
                    bad = (resp.status, await resp.json())
                partial_recipe = {"schema": "recipe/1", "prompt": {"positive": "x"}, "settings": {"steps": 20},
                                  "loras": [{"file": "watercolor_v3", "weight": 0.5}, "junk"]}
                async with s.post(f"http://127.0.0.1:{port}/sm-fetcher/recipe/plan", json={"recipe": partial_recipe}) as resp:
                    planned = (resp.status, await resp.json())
                async with s.post(f"http://127.0.0.1:{port}/sm-fetcher/recipe/from-lm", json={"item": lm_item}) as resp:
                    from_lm = (resp.status, await resp.json())
                check(from_lm[0] == 200 and from_lm[1]["recipe"]["lm_id"] == "f00d", "HTTP: LoRA Manager recipe converted")
                return ok, bad, planned
        finally:
            await runner.cleanup()
    (st_ok, body), (st_bad, err), (st_plan, planned) = asyncio.run(http())
    pr = planned.get("recipe") or {}
    check(st_plan == 200 and pr.get("settings", {}).get("steps") == 20 and "sampler" in pr.get("settings", {}) and pr["prompt"]["negative"] == ""
          and len(pr["loras"]) == 1 and len(planned["items"]) == 1 and planned["items"][0]["status"] == "present",
          f"HTTP: plan normalizes a partial recipe from another extension ({st_plan}, {planned.get('items')})")
    check(st_ok == 200 and body["recipe"]["format"] == "a1111" and body["recipe"]["title"] == "up" and "items" in body, "HTTP: multipart upload analyzed")
    check(st_bad == 422 and "error" in err, "HTTP: non-image -> 422 with a message")

    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    shutil.rmtree(T.ROOT, ignore_errors=True)
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()

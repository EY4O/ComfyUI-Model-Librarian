"""Recipes from videos: files written the way ComfyUI's Save Video, Video Helper
Suite, Save WEBM and Save Animated WEBP write them (PyAV / Pillow), then read back."""
import asyncio
import io
import json
import os
import shutil
import sys
import tempfile

import test_shared as T

check = T.check

GRAPH = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "Wan\\wan2.2_i2v_high_fp8.safetensors", "weight_dtype": "default"}},
    "2": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": "Wan\\motion_sway_HIGH.safetensors", "strength_model": 0.9}},
    "3": {"class_type": "DF_DynamicPrompts_Text_Box", "inputs": {"Text": "a fox running through snow"}},
    "4": {"class_type": "StringConcatenate", "inputs": {"string_a": ["3", 0], "string_b": "cinematic", "delimiter": ", "}},
    "5": {"class_type": "CLIPTextEncode", "inputs": {"text": ["4", 0]}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "static, blurry"}},
    "7": {"class_type": "WanImageToVideo", "inputs": {"positive": ["5", 0], "negative": ["6", 0], "width": 480, "height": 832, "length": 81}},
    "8": {"class_type": "KSamplerAdvanced", "inputs": {"model": ["2", 0], "positive": ["7", 0], "negative": ["7", 1], "latent_image": ["7", 2],
                                                     "noise_seed": 42, "steps": 6, "cfg": 1, "sampler_name": "euler", "scheduler": "simple"}},
}
WORKFLOW = {"nodes": [{"id": 8, "type": "KSamplerAdvanced"}], "links": []}


def write_video(path, fmt, codec, metadata, options=None):
    import av
    import numpy as np
    c = av.open(path, "w", format=fmt, options=options or {})
    for k, v in metadata.items():
        c.metadata[k] = v
    s = c.add_stream(codec, rate=8)
    s.width, s.height, s.pix_fmt = 64, 64, "yuv420p"
    for i in range(4):
        frame = av.VideoFrame.from_ndarray(np.full((64, 64, 3), i * 40, dtype=np.uint8), format="rgb24")
        for p in s.encode(frame):
            c.mux(p)
    for p in s.encode():
        c.mux(p)
    c.close()


def main():
    base, user = T.fake_install("Video")
    smf = T.load_smf(base, user)
    rp, vm = smf.recipe_parse, smf.videometa
    tmp = tempfile.mkdtemp(prefix="smf_video_")
    try:
        import av  # noqa: F401
        have_av = True
    except ImportError:
        have_av = False
        print("SKIP video files: PyAV isn't installed (ComfyUI ships it)")

    def check_recipe(r, label):
        check(r["format"] == "comfyui" and r["prompt"]["positive"] == "a fox running through snow, cinematic" and r["prompt"]["negative"] == "static, blurry",
              f"{label}: prompts traced through WanImageToVideo and StringConcatenate ({r['prompt']})")
        check(r["model"]["file"] == "Wan\\wan2.2_i2v_high_fp8.safetensors" and r["loras"][0]["weight"] == 0.9 and r["settings"]["steps"] == 6,
              f"{label}: model, LoRA and settings")

    if have_av:
        # ComfyUI Save Video: QuickTime metadata keys, through PyAV with use_metadata_tags
        core = os.path.join(tmp, "core.mp4")
        write_video(core, "mp4", "mpeg4", {"prompt": json.dumps(GRAPH), "workflow": json.dumps(WORKFLOW)}, {"movflags": "use_metadata_tags"})
        meta = vm.read(core)
        check(meta["format"] == "mp4" and json.loads(meta["text"]["prompt"]) == GRAPH and "workflow" in meta["text"], "Save Video MP4: prompt and workflow keys")
        r = rp.from_video(core, "core.mp4")
        check_recipe(r, "Save Video MP4")
        check(r.get("media") == "video" and r["comfy"]["workflow"] == WORKFLOW and r["title"] == "core", "Save Video MP4: workflow kept, marked as video")

        # Video Helper Suite: one comment holding both, written by ffmpeg (iTunes ©cmt)
        vhs = os.path.join(tmp, "vhs.mp4")
        write_video(vhs, "mp4", "mpeg4", {"comment": json.dumps({"prompt": json.dumps(GRAPH), "workflow": json.dumps(WORKFLOW)})})
        check_recipe(rp.from_video(vhs, "vhs.mp4"), "Video Helper Suite MP4 comment")

        # Save WEBM / VHS webm: Matroska tags
        webm = os.path.join(tmp, "clip.webm")
        try:
            write_video(webm, "webm", "libvpx-vp9", {"prompt": json.dumps(GRAPH), "workflow": json.dumps(WORKFLOW)})
            check(vm.read(webm)["format"] == "webm", "WebM recognised")
            check_recipe(rp.from_video(webm, "clip.webm"), "WebM tags")
        except Exception as ex:  # no VP9 encoder in this PyAV build
            print(f"SKIP webm: {ex}")

        # a video without metadata
        bare = os.path.join(tmp, "bare.mp4")
        write_video(bare, "mp4", "mpeg4", {})
        try:
            rp.from_video(bare, "bare.mp4")
            check(False, "video without metadata -> NoMetadata")
        except rp.NoMetadata as ex:
            check("No generation data" in str(ex), "video without metadata -> NoMetadata with a clear message")

        # HTTP: a video upload is streamed to disk and read
        from aiohttp import web, FormData, ClientSession

        async def http():
            routes = web.RouteTableDef()
            smf.routes.register(routes)
            app = web.Application(client_max_size=1024 ** 3)
            app.add_routes(routes)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            try:
                async with ClientSession() as s:
                    fd = FormData()
                    fd.add_field("image", open(core, "rb").read(), filename="upload.mp4", content_type="video/mp4")
                    async with s.post(f"http://127.0.0.1:{port}/sm-fetcher/recipe/analyze", data=fd) as resp:
                        return resp.status, await resp.json()
            finally:
                await runner.cleanup()
        st, body = asyncio.run(http())
        check(st == 200 and body["recipe"]["media"] == "video" and body["recipe"]["title"] == "upload" and body["thumb"] is None and body["items"],
              f"HTTP: video upload analyzed (thumbnail left to the browser) ({st})")

    # Save Animated WEBP: EXIF Model = "prompt:{...}", Make = "workflow:{...}"
    from PIL import Image
    ex = Image.Exif()
    ex[0x0110] = "prompt:" + json.dumps(GRAPH)
    ex[0x010F] = "workflow:" + json.dumps(WORKFLOW)
    buf = io.BytesIO()
    frames = [Image.new("RGB", (32, 32), (i * 60, 0, 0)) for i in range(3)]
    frames[0].save(buf, "WEBP", save_all=True, append_images=frames[1:], exif=ex.tobytes(), duration=100)
    text = smf.imagemeta.read(buf.getvalue())["text"]
    check(json.loads(text.get("prompt", "null")) == GRAPH and json.loads(text.get("workflow", "null")) == WORKFLOW, "animated WebP: prompt:/workflow: EXIF fields")
    check_recipe(rp.from_image(buf.getvalue(), "anim.webp"), "animated WebP")

    # CivitAI video links -> a still frame from the CDN
    still = smf.recipes.civitai_still("https://image.civitai.com/abc/uuid/original=true/123.mp4")
    check(still == "https://image.civitai.com/abc/uuid/anim=false,width=512/123.mp4", f"CivitAI video -> still frame URL ({still})")
    check(smf.videometa.is_video("clip.WEBM") and smf.videometa.is_video(None, "video/mp4") and not smf.videometa.is_video("a.png", "image/png"), "video detection")

    shutil.rmtree(tmp, ignore_errors=True)
    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    shutil.rmtree(T.ROOT, ignore_errors=True)
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()

"""Downloads (UNet relocation, persistence + retry, leftover partials), pasted links, VRAM advice."""
import asyncio
import json
import os
import shutil
import struct
import sys

import test_shared as T

check = T.check
GB = 1024 ** 3


def safetensors(keys):
    header = {k: {"dtype": "F16", "shape": [1], "data_offsets": [i * 2, i * 2 + 2]} for i, k in enumerate(keys)}
    raw = json.dumps(header).encode()
    return struct.pack("<Q", len(raw)) + raw + b"\0" * (2 * len(keys))


def main():
    base, user = T.fake_install("DL")
    dm = os.path.join(T.MODELS, "DiffusionModels")
    for d in (dm, T.LORA, os.path.join(T.MODELS, "StableDiffusion"), os.path.join(T.MODELS, "TextEncoders")):
        os.makedirs(d, exist_ok=True)
    with open(os.path.join(base, "extra_model_paths.yaml"), "w") as f:
        f.write(f"stability_matrix:\n  base_path: {T.MODELS}\n  loras: Lora\n  checkpoints: StableDiffusion\n"
                f"  diffusion_models: DiffusionModels\n  text_encoders: TextEncoders\n")
    smf = T.load_smf(base, user)
    smf.downloader.TEST_ALLOW_HTTP = True  # the test server is plain http on 127.0.0.1
    unet = safetensors(["model.diffusion_model.double_blocks.0.img_attn.qkv.weight", "model.diffusion_model.final_layer.linear.weight"])
    full = safetensors(["model.diffusion_model.input_blocks.0.0.weight", "first_stage_model.decoder.conv_in.weight",
                        "cond_stage_model.transformer.text_model.embeddings.position_ids"])
    files = {"/unet.safetensors": unet, "/full.safetensors": full, "/lora.safetensors": b"L" * 5000}

    from aiohttp import web

    async def serve(request):
        data = files.get(request.path)
        if data is None:
            return web.Response(status=404)
        rng = request.headers.get("Range")
        if rng:
            start = int(rng.split("=")[1].split("-")[0])
            return web.Response(status=206, body=data[start:], headers={"Content-Type": "application/octet-stream"})
        return web.Response(body=data, headers={"Content-Type": "application/octet-stream"})

    async def wait(job_id):
        for _ in range(200):
            j = smf.downloader.get(job_id)
            if j["status"] not in ("queued", "downloading", "verifying"):
                return j
            await asyncio.sleep(0.05)
        return smf.downloader.get(job_id)

    async def run():
        app = web.Application()
        app.router.add_get("/{name}", serve)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        url = lambda n: f"http://127.0.0.1:{port}/{n}"  # noqa: E731
        try:
            j = await wait(smf.downloader.start(url=url("unet.safetensors"), folder="checkpoints", rel="Flux/unet.safetensors",
                                                auto_place=True)["id"])
            check(j["status"] == "done" and j["folder"] == "diffusion_models"
                  and os.path.isfile(os.path.join(dm, "Flux", "unet.safetensors")), "UNet-only 'checkpoint' moved to diffusion_models")
            j = await wait(smf.downloader.start(url=url("full.safetensors"), folder="checkpoints", rel="full.safetensors",
                                                auto_place=True)["id"])
            check(j["folder"] == "checkpoints" and os.path.isfile(os.path.join(T.MODELS, "StableDiffusion", "full.safetensors")),
                  "all-in-one checkpoint stays in checkpoints")
            j = await wait(smf.downloader.start(url=url("unet.safetensors"), folder="checkpoints", rel="kept.safetensors")["id"])
            check(j["folder"] == "checkpoints", "without auto_place (workflow downloads) nothing is moved")

            # persistence: an unfinished job survives a restart as 'interrupted', and retry resumes
            part = os.path.join(T.LORA, "lora.safetensors.smf-part")
            open(part, "wb").write(files["/lora.safetensors"][:2000])
            json.dump({"url": url("lora.safetensors")}, open(part + ".src", "w"))
            saved = [{"id": "old1", "url": url("lora.safetensors"), "folder": "loras", "rel": "lora.safetensors",
                      "dest": os.path.join(T.LORA, "lora.safetensors"), "shared": True, "sha256": None, "size": 5000,
                      "source": "manual", "page_url": None, "title": None, "meta": None, "status": "downloading",
                      "done": 2000, "total": 5000, "error": None, "created": 1, "finished": None, "auto_place": False}]
            json.dump(saved, open(os.path.join(smf.config.local_dir(), "downloads.json"), "w"))
            smf.downloader._restored = False
            smf.downloader._jobs.pop("old1", None)
            old = next(j for j in smf.downloader.jobs() if j["id"] == "old1")
            check(old["status"] == "interrupted" and "restarted" in old["error"], "restart: unfinished download listed as interrupted")
            plist = smf.downloader.partials()
            check(any(p["path"] == part and p["retryable"] for p in plist), "its partial file is flagged as resumable")
            nj = await wait(smf.downloader.retry("old1")["id"])
            data = open(os.path.join(T.LORA, "lora.safetensors"), "rb").read()
            check(nj["status"] == "done" and data == files["/lora.safetensors"], "retry resumed and completed the file")
            check(not any(j["id"] == "old1" for j in smf.downloader.jobs()), "old entry replaced by the retry")
        finally:
            await smf.net.close()
            await runner.cleanup()
    asyncio.run(run())

    # leftover partials
    orphan = os.path.join(T.LORA, "orphan.safetensors.smf-part")
    open(orphan, "wb").write(b"x" * 300)
    found = {p["path"]: p for p in smf.downloader.partials()}
    check(orphan in found and not found[orphan]["retryable"], "orphan partial found")
    keep_file = os.path.join(T.LORA, "precious.safetensors")
    open(keep_file, "wb").write(b"!")
    r = smf.downloader.delete_partials([orphan, keep_file])
    check(r["deleted"] == 1 and not os.path.exists(orphan), "orphan partial deleted")
    check(os.path.exists(keep_file) and r["errors"], "anything that isn't a leftover partial is refused")

    # pasted links
    async def fake_get_json(u, params=None, timeout=30):
        if u.endswith("/api/v1/models/77"):
            return {"modelVersions": [{"id": 701}]}
        if "/model-versions/701" in u:
            return {"id": 701, "modelId": 77, "name": "v1", "baseModel": "Pony", "model": {"name": "M", "type": "LORA"},
                    "files": [{"name": "m.safetensors", "primary": True, "sizeKB": 1, "hashes": {"SHA256": "AB" * 32},
                               "downloadUrl": "https://civitai.com/api/download/models/701"}]}
        return None
    smf.net.get_json = fake_get_json

    async def fake_tree(repo):
        return [{"type": "file", "path": "sub/x.safetensors", "size": 10, "lfs": {"oid": "cd" * 32, "size": 10}}]
    smf.sources.hf_tree = fake_tree
    c = asyncio.run(smf.sources.from_url("https://civitai.red/models/77/some-name"))
    check(c["sha256"] == "ab" * 32 and c["filename"] == "m.safetensors" and c["meta"]["baseModel"] == "Pony",
          "CivitAI model page (no version) -> latest version's file + hash + metadata")
    c = asyncio.run(smf.sources.from_url("https://civitai.com/api/download/models/701?type=Model&format=SafeTensor&size=pruned"))
    check(c["url"].endswith("size=pruned") and c["sha256"] is None, "download link picking a variant: kept, hash not assumed")
    c = asyncio.run(smf.sources.from_url("https://huggingface.co/org/repo/blob/main/sub/x.safetensors"))
    check(c["url"] == "https://huggingface.co/org/repo/resolve/main/sub/x.safetensors" and c["sha256"] == "cd" * 32,
          "HuggingFace /blob/ page -> /resolve/ link with SHA256")

    # VRAM advice
    budget = smf.swaps.budget_bytes({"vram_gb": 12, "headroom_gb": 1.5})
    tb = smf.swaps.too_big
    check(tb("flux1-dev.safetensors", 23 * GB, ["UNETLoader"], budget) == "model", "big UNet flagged")
    check(tb("t5xxl_fp16.safetensors", 9 * GB, ["DualCLIPLoader"], budget) == "text_encoder", "big text encoder flagged")
    check(tb("t5xxl_fp8_e4m3fn.safetensors", 9 * GB, ["DualCLIPLoader"], budget) is None, "fp8 file not flagged again")
    check(tb("clip_l.safetensors", 0.2 * GB, ["DualCLIPLoader"], budget) is None, "small text encoder fine")

    async def fake_search(q, limit=8):
        return [{"id": "someone/t5-gguf"}] if "gguf" in q else [{"id": "comfyanonymous/flux_text_encoders"}]

    async def fake_tree2(repo):
        if repo == "comfyanonymous/flux_text_encoders":
            return [{"type": "file", "path": "t5xxl_fp8_e4m3fn.safetensors", "size": 5 * GB},
                    {"type": "file", "path": "clip_l.safetensors", "size": GB // 4},
                    {"type": "file", "path": "t5xxl_fp16.safetensors", "size": 9 * GB}]
        if repo == "city96/t5-v1_1-xxl-encoder-gguf":
            return [{"type": "file", "path": "t5-v1_1-xxl-encoder-Q8_0.gguf", "size": 5 * GB},
                    {"type": "file", "path": "t5-v1_1-xxl-encoder-Q4_K_M.gguf", "size": 3 * GB}]
        return []
    smf.sources.hf_search, smf.sources.hf_tree = fake_search, fake_tree2
    smf.config.save({"vram_gb": 12, "headroom_gb": 1.5})
    res = asyncio.run(smf.swaps.suggest("t5xxl_fp16.safetensors", 9 * GB, None, ["DualCLIPLoader"]))
    kinds = {(o["filename"], o["kind"], o["action"]) for o in res["options"]}
    check(("t5xxl_fp8_e4m3fn.safetensors", "fp8", "repoint") in kinds, "fp8 text encoder offered, repointed in the same node")
    check(("t5-v1_1-xxl-encoder-Q4_K_M.gguf", "gguf", "download") in kinds, "GGUF text encoder offered as download-only")
    check(not any(o["filename"] == "clip_l.safetensors" for o in res["options"]), "unrelated files in the repo ignored")
    check(sum(o["recommended"] for o in res["options"]) == 1 and res["kind"] == "text_encoder", "one recommendation")

    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    shutil.rmtree(T.ROOT, ignore_errors=True)
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()

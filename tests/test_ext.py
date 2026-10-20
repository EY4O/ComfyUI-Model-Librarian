"""The Chrome extension's routes: hello, a CivitAI version's file planned into the right folder and
downloaded (SHA256-verified), nothing downloaded twice, and library lookups. CivitAI is faked."""
import asyncio
import hashlib
import os

os.environ["SMF_TEST_ALLOW_HTTP"] = "1"
import test_shared as T  # noqa: E402

check = T.check


def main():
    base, user = T.fake_install("EXT")
    for d in ("StableDiffusion", "Lora", "Embeddings", "DiffusionModels"):
        os.makedirs(os.path.join(T.MODELS, d), exist_ok=True)
    with open(os.path.join(base, "extra_model_paths.yaml"), "w") as f:
        f.write(f"stability_matrix:\n  base_path: {T.MODELS}\n  loras: Lora\n  checkpoints: StableDiffusion\n"
                f"  embeddings: Embeddings\n  diffusion_models: DiffusionModels\n")
    smf = T.load_smf(base, user)
    ext = smf.ext
    lora_bytes, pruned_bytes, emb_bytes = b"L" * 6000, b"P" * 3000, b"E" * 700
    sha = lambda b: hashlib.sha256(b).hexdigest().upper()  # noqa: E731

    from aiohttp import web
    files = {"/lora": lora_bytes, "/pruned": pruned_bytes, "/emb": emb_bytes}

    async def serve(request):
        data = files.get(request.path)
        return web.Response(body=data, headers={"Content-Type": "application/octet-stream"}) if data else web.Response(status=404)

    async def run():
        app = web.Application()
        app.router.add_get("/{name}", serve)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        u = lambda n: f"http://127.0.0.1:{port}/{n}"  # noqa: E731

        def fl(fid, name, data, url, primary=True, fmt="SafeTensor"):
            return {"id": fid, "name": name, "primary": primary, "sizeKB": len(data) / 1024, "downloadUrl": url,
                    "hashes": {"SHA256": sha(data)}, "metadata": {"format": fmt}}
        versions = {
            "11": {"id": 11, "modelId": 1, "name": "v1", "baseModel": "Illustrious", "images": [],
                   "model": {"name": "Paper Cut", "type": "LORA"}, "files": [fl(101, "paper_cut.safetensors", lora_bytes, u("lora"))]},
            "21": {"id": 21, "modelId": 2, "name": "v4", "baseModel": "SDXL 1.0", "images": [],
                   "model": {"name": "Aurora", "type": "Checkpoint"},
                   "files": [fl(201, "aurora_full.safetensors", b"F" * 9000, u("full")), fl(202, "aurora_pruned.safetensors", pruned_bytes, u("pruned"), primary=False),
                             {**fl(203, "aurora_vae.safetensors", b"V", u("vae"), primary=False), "type": "VAE"},
                             {**fl(204, "dataset.zip", b"D", u("zip"), primary=False), "type": "Training Data"}]},
            "31": {"id": 31, "modelId": 3, "name": "v1", "baseModel": "SD 1.5", "images": [],
                   "model": {"name": "Neg", "type": "TextualInversion"}, "files": [fl(301, "easyneg.safetensors", emb_bytes, u("emb"))]},
            "41": {"id": 41, "modelId": 4, "name": "v1", "baseModel": "Flux.1 D", "images": [],
                   "model": {"name": "Flux Q8", "type": "Checkpoint"}, "files": [fl(401, "flux_q8.gguf", b"G" * 10, u("gguf"), fmt="GGUF")]},
            "61": {"id": 61, "modelId": 6, "name": "v4.0 INT4", "baseModel": "Krea 2 Turbo", "images": [],
                   "model": {"name": "Muse", "type": "Checkpoint"},
                   "files": [{**fl(601, "muse_v40INT4.safetensors", b"I", u("i4")), "type": "Diffusion Model"},
                             {**fl(602, "muse_txt.safetensors", b"T", u("te"), primary=False), "type": "Text Encoder"}]},
            "51": {"id": 51, "modelId": 5, "name": "v1", "baseModel": "Other", "images": [],
                   "model": {"name": "Comfy flow", "type": "Workflows"}, "files": [fl(501, "flow.zip", b"Z", u("zip"))]},
        }

        async def fake_get_json(url, params=None, timeout=30):
            vid = url.rstrip("/").split("/")[-1]
            return versions.get(vid)
        smf.net.get_json = fake_get_json

        async def wait(jid):
            for _ in range(200):
                j = smf.downloader.get(jid)
                if j["status"] not in ext.ACTIVE:
                    return j
                await asyncio.sleep(0.05)
            return smf.downloader.get(jid)

        try:
            h = ext.hello()
            check(h["app"] == "model-librarian" and h["version"] == ext.plugin_version() != "?" and h["civitai_key"] is False,
                  f"hello: who's there, its version, no key set ({h['version']})")

            fam = smf.organize.folder_for(smf.basemodel.from_text("Illustrious"))
            p = await ext.download(11, dry_run=True)
            check(p["status"] == "planned" and p["folder"] == "loras" and p["rel"] == f"{fam}/paper_cut.safetensors"
                  and p["dest"] == os.path.join(T.LORA, fam, "paper_cut.safetensors"), f"a LoRA is planned into its base-model folder ({p['rel']})")
            p = await ext.download(31, dry_run=True)
            check(p["folder"] == "embeddings" and p["rel"] == "easyneg.safetensors", "embeddings aren't sorted into subfolders")
            p = await ext.download(41, dry_run=True)
            check(p["folder"] == "diffusion_models", "a GGUF 'checkpoint' goes to diffusion_models")
            p = await ext.download(21, 202, dry_run=True)
            check(p["file"] == "aurora_pruned.safetensors" and p["folder"] == "checkpoints", "file_id picks the pruned file, not the primary")
            p = await ext.download(61, dry_run=True)
            check(p["folder"] == "diffusion_models", f"a 'Diffusion Model' file on a Checkpoint page goes to diffusion_models ({p['folder']}/{p['rel']})")
            p = await ext.download(61, 602, dry_run=True)
            check(p["folder"] == "text_encoders" and p["rel"] == "muse_txt.safetensors", "a bundled text encoder goes to text_encoders, unsorted")
            sysinfo = h["system"]
            check(set(sysinfo) >= {"gpu", "vram_total", "budget", "fast", "formats", "loaders"} and sysinfo["budget"] == int((12.0 - 1.5) * 1024 ** 3),
                  f"hello describes the system (no GPU here: budget from Settings) ({sysinfo['budget']})")
            p = await ext.download(21, 203, dry_run=True)
            check(p["folder"] == "vae" and p["rel"] == "aurora_vae.safetensors", "a checkpoint's bundled VAE file goes to vae")
            for bad, label in (((51,), "a workflow isn't a model"), (("abc",), "a non-number version"), ((21, 204), "training data")):
                try:
                    await ext.download(*bad, dry_run=True)
                    check(False, label + " is refused")
                except ValueError:
                    check(True, label + " is refused")
            try:
                await ext.download(999, dry_run=True)
                check(False, "an unknown version -> LookupError (404)")
            except LookupError:
                check(True, "an unknown version -> LookupError (404)")

            check(ext.lookup([11, "31", "x"])["versions"] == {"11": {"status": "missing"}, "31": {"status": "missing"}}, "lookup before downloading: missing (junk ids dropped)")
            r = await ext.download(11)
            check(r["status"] == "started" and r["job"]["id"], "download started")
            again = await ext.download(11)
            check(again["status"] in ("downloading", "have"), f"clicking again doesn't start a second download ({again['status']})")
            j = await wait(r["job"]["id"])
            dest = os.path.join(T.LORA, fam, "paper_cut.safetensors")
            check(j["status"] == "done" and open(dest, "rb").read() == lora_bytes, f"downloaded and verified ({j['status']} {j.get('error')})")
            lk = ext.lookup([11])["versions"]["11"]
            check(lk["status"] == "have", f"lookup after: have ({lk})")
            check((await ext.download(11))["status"] == "have", "a file that's there isn't downloaded again")
            check(any(x["id"] == r["job"]["id"] and x["status"] == "done" for x in ext.jobs([r["job"]["id"]])) and "meta" not in ext.jobs([])[0],
                  "jobs by id, without the metadata blob")

            # already in the library under another name: found by SHA256
            other = os.path.join(T.MODELS, "Embeddings", "renamed_neg.safetensors")
            open(other, "wb").write(emb_bytes)
            smf.hashing.store(other, sha(emb_bytes).lower())
            ext._owned["at"] = 0
            r = await ext.download(31)
            check(r["status"] == "have" and r["rel"] == "renamed_neg.safetensors", f"a file you have under another name isn't downloaded ({r.get('rel')})")
            check(ext.lookup([], [sha(emb_bytes)])["hashes"][sha(emb_bytes).lower()]["status"] == "have", "lookup by SHA256")
        finally:
            await smf.net.close()
            await runner.cleanup()

    asyncio.run(run())
    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    return 1 if check.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

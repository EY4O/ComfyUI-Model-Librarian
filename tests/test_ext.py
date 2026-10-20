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
            "1": {"id": 1, "description": "<p>A <b>paper cut</b> LoRA.</p>"},  # /api/v1/models/1: the model page's description
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
            cmi = smf.smmeta.read_cm_info(dest) or {}
            check(cmi.get("ModelDescription") == "<p>A <b>paper cut</b> LoRA.</p>", f"the model's CivitAI description is saved next to the download ({cmi.get('ModelDescription')!r})")
            lk = ext.lookup([11])["versions"]["11"]
            check(lk["status"] == "have", f"lookup after: have ({lk})")
            check((await ext.download(11))["status"] == "have", "a file that's there isn't downloaded again")
            ext._owned["at"] = 0
            lm = ext.lookup([], [], [1, 999])["models"]
            check(lm["1"]["status"] == "have" and lm["1"]["files"] == 1 and lm["999"]["status"] == "missing", f"lookup by model id, for listing badges ({lm})")
            smf.config.write_json(smf.updates.CACHE, {"models": {"1": {"name": "Paper Cut", "versions": [
                {"id": 12, "name": "v2", "base_model": "Illustrious"}, {"id": 11, "name": "v1", "base_model": "Illustrious"}]}}})
            lm = ext.lookup([], [], [1])["models"]["1"]
            check(lm["status"] == "update" and lm["update"] == {"version_id": 12, "name": "v2"}, f"a newer version shows as an update ({lm})")

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

            # ---- what a diffusion model needs besides itself, from ComfyUI's workflow templates
            import json as _json
            import sys as _sys
            import tempfile as _tf
            pkg_root = _tf.mkdtemp(prefix="smf_tpl_")
            tdir = os.path.join(pkg_root, "comfyui_workflow_templates_json", "templates")
            os.makedirs(tdir)
            open(os.path.join(pkg_root, "comfyui_workflow_templates_json", "__init__.py"), "w").close()
            HF = "https://huggingface.co/Comfy-Org"

            def tpl(name, models, sub=False):
                nodes = [{"type": "X", "properties": {"models": [{"name": n, "directory": d, "url": f"{HF}/{d}/{n}"}]}} for d, n in models]
                body = {"nodes": [], "definitions": {"subgraphs": [{"nodes": nodes}]}} if sub else {"nodes": nodes}
                _json.dump(body, open(os.path.join(tdir, name + ".json"), "w"))
            tpl("image_krea2_turbo_t2i", [("diffusion_models", "krea2_turbo_fp8_scaled.safetensors"), ("text_encoders", "qwen3vl_4b_fp8_scaled.safetensors"),
                                          ("vae", "qwen_image_vae.safetensors"), ("loras", "krea2_darkbrush.safetensors")], sub=True)
            tpl("image_krea2_turbo_t2i_int8", [("diffusion_models", "krea2_turbo_int8_convrot.safetensors"), ("text_encoders", "qwen3vl_4b_fp8_scaled.safetensors"),
                                               ("vae", "qwen_image_vae.safetensors")])
            tpl("flux_dev_full_text_to_image", [("diffusion_models", "flux1-dev.safetensors"), ("text_encoders", "clip_l.safetensors"),
                                                ("text_encoders", "t5xxl_fp16.safetensors"), ("vae", "ae.safetensors")])
            tpl("audio_ace_step1_5_xl_sft", [("diffusion_models", "acestep_v1.5_xl_sft.safetensors"), ("vae", "ace_1.5_vae.safetensors")])
            tpl("api_krea2_t2i", [("diffusion_models", "krea2_api.safetensors"), ("text_encoders", "nope.safetensors")])
            _sys.path.insert(0, pkg_root)
            import importlib as _il
            _il.invalidate_caches()
            from smf import companions as comp
            check(sorted(t["template"] for t in comp.index()) == ["flux_dev_full_text_to_image", "image_krea2_turbo_t2i", "image_krea2_turbo_t2i_int8"],
                  "templates indexed (subgraphs read; api_ and audio templates and LoRAs left out)")

            class Inv:
                base = {"text_encoders": {"qwen3vl_4b_fp8_scaled.safetensors": "qwen3vl_4b_fp8_scaled.safetensors",
                                          "t5xxl_fp8_e4m3fn_scaled.safetensors": "t5xxl_fp8_e4m3fn_scaled.safetensors"},
                        "vae": {"qwen_image_vae.safetensors": "Qwen\qwen_image_vae.safetensors"}}
            r = comp.for_model("Krea 2 Turbo", "museByStableYogi_v40INT4Extended.safetensors", Inv())
            by = {c["name"]: c for c in r["companions"]}
            check(r["family"] == "Krea 2" and set(by) == {"qwen3vl_4b_fp8_scaled.safetensors", "qwen_image_vae.safetensors"},
                  f"Krea 2 needs its Qwen3-VL text encoder and the Qwen image VAE ({r['source']}: {sorted(by)})")
            check(all("size" in c for c in r["companions"]), "each companion says its size (from disk when installed; None here, no ComfyUI)")
            check(by["qwen_image_vae.safetensors"]["have"] == "Qwen\qwen_image_vae.safetensors" and by["qwen3vl_4b_fp8_scaled.safetensors"]["have"],
                  "found in your library, in a subfolder too")
            check(comp.for_model("Krea 2", "krea2_turbo_int8_whatever.safetensors", Inv())["source"] == "image_krea2_turbo_t2i_int8",
                  "the template whose model file is most like this one")
            r = comp.for_model("Flux.1 D", "myFluxMerge_fp8.safetensors", Inv())
            fb = {c["name"]: c for c in r["companions"]}
            check(fb["t5xxl_fp16.safetensors"]["have"] is None and fb["t5xxl_fp16.safetensors"]["alt"] == "t5xxl_fp8_e4m3fn_scaled.safetensors"
                  and fb["clip_l.safetensors"]["have"] is None and fb["clip_l.safetensors"]["alt"] is None,
                  "another precision of the same encoder counts as an alternative; a missing one is missing")
            check(comp.for_model("SDXL 1.0", "x.safetensors", Inv())["companions"] == [], "SDXL: nothing suggested (an audio template whose name has 'xl' in it doesn't count)")

            # companion download: only listed files; HuggingFace's SHA256 is checked
            vae_bytes = b"VAE!" * 100
            files["/vae"] = vae_bytes

            async def fake_from_url(url):
                return {"url": u("vae"), "sha256": sha(vae_bytes).lower(), "size": len(vae_bytes), "source": "huggingface", "page_url": url}
            smf.sources.from_url = fake_from_url
            os.makedirs(os.path.join(T.MODELS, "VAE"), exist_ok=True)
            try:
                await ext.companion_download("Flux.1 D", "myFlux.safetensors", "evil.safetensors")
                check(False, "a file the model doesn't need is refused")
            except LookupError:
                check(True, "a file the model doesn't need is refused")
            r = await smf.sources.from_templates("Qwen\QWEN_IMAGE_VAE.safetensors")
            check(len(r) == 1 and r[0]["source"] == "template" and r[0]["confidence"] == "high" and r[0]["folder"] == "vae"
                  and "image_krea2_turbo_t2i" in r[0]["title"] and r[0]["sha256"], f"the missing-model finder knows the templates' official links ({r[:1]})")
            lr = await smf.sources.from_templates("krea2_darkbrush.safetensors")
            check(lr and lr[0]["folder"] == "loras", "LoRAs and diffusion models from the templates too")
            check(await smf.sources.from_templates("nothing_like_it.safetensors") == [], "unknown files: nothing")
            r = await ext.companion_download("Flux.1 D", "myFlux.safetensors", "ae.safetensors")
            j = await wait(r["job"]["id"])
            check(r["status"] == "started" and j["status"] == "done" and j["folder"] == "vae" and open(j["dest"], "rb").read() == vae_bytes,
                  f"a missing VAE downloads into vae, verified ({j['status']} {j.get('error')})")

            # ---- CivArchive: a file by SHA256 -> yours, or its live copies planned into the right folder
            gone_sha = "ab" * 32
            async def fake_by_hash(sha, force=False):
                if sha != gone_sha:
                    return None
                return {"sha256": gone_sha, "filename": "gone_style.safetensors", "size": 1234, "page_url": "https://civarchive.com/sha256/" + gone_sha,
                        "deleted_on_civitai": True, "meta": {"modelName": "Gone Style", "versionName": "v2", "type": "LORA", "baseModel": "Illustrious"},
                        "files": [{"live": True, "paid": False, "url": "https://huggingface.co/x/y/resolve/main/gone_style.safetensors", "host": "huggingface.co",
                                   "filename": "gone_style.safetensors", "gated": False},
                                  {"live": True, "paid": False, "url": "https://example-host.com/gone", "host": "example-host.com", "filename": "gone_style.safetensors", "gated": False},
                                  {"live": False, "paid": False, "url": "https://civitai.com/api/download/models/5", "host": "civitai.com", "filename": "gone_style.safetensors", "gated": False}]}
            smf.civarchive.by_hash = fake_by_hash
            cr = await ext.civarchive_copies(gone_sha)
            d0 = (cr.get("downloads") or [{}])[0]
            check(cr["status"] == "copies" and cr["removed"] and len(cr["downloads"]) == 1 and d0["folder"] == "loras"
                  and d0["rel"] == f"{fam}/gone_style.safetensors" and d0["sha256"] == gone_sha and cr["links"] == [{"url": "https://example-host.com/gone", "via": "example-host.com"}],
                  f"a removed model's live copy is planned into loras/{fam}/; other hosts are links ({cr.get('downloads')}, {cr.get('links')})")
            check((await ext.civarchive_copies("cd" * 32))["status"] == "unknown", "CivArchive doesn't know it: unknown")
            check((await ext.civarchive_copies(sha(emb_bytes).lower()))["status"] == "have", "a file you have: have")
            try:
                await ext.civarchive_copies("nope")
                check(False, "a bad hash is refused")
            except ValueError:
                check(True, "a bad hash is refused")

            # ---- a HuggingFace file page into the folder you pick
            te_bytes = b"TE" * 300
            files["/te"] = te_bytes
            async def fake_from_url2(url):
                return {"url": u("te"), "filename": "umt5_xxl_fp8.safetensors", "sha256": sha(te_bytes).lower(), "size": len(te_bytes), "source": "huggingface",
                        "page_url": "https://huggingface.co/Comfy-Org/wan", "title": "Comfy-Org/wan/umt5_xxl_fp8.safetensors"}
            smf.sources.from_url = fake_from_url2
            os.makedirs(os.path.join(T.MODELS, "TextEncoders"), exist_ok=True)
            for bad_folder in ("", "../etc", "workflows"):
                try:
                    await ext.download_url("https://huggingface.co/a/b/blob/main/x.safetensors", bad_folder)
                    check(False, f"folder {bad_folder!r} refused")
                except ValueError:
                    pass
            pl = await ext.download_url("https://huggingface.co/Comfy-Org/wan/blob/main/umt5_xxl_fp8.safetensors", "text_encoders", dry_run=True)
            check(pl["status"] == "planned" and pl["rel"] == "umt5_xxl_fp8.safetensors" and pl["sha256"], f"planned with HF's SHA256 ({pl['status']})")
            st = await ext.download_url("https://huggingface.co/Comfy-Org/wan/blob/main/umt5_xxl_fp8.safetensors", "text_encoders")
            j = await wait(st["job"]["id"])
            check(j["status"] == "done" and j["folder"] == "text_encoders" and open(j["dest"], "rb").read() == te_bytes, f"downloaded into text_encoders, verified ({j['status']})")
            check((await ext.download_url("https://huggingface.co/Comfy-Org/wan/blob/main/umt5_xxl_fp8.safetensors", "text_encoders"))["status"] == "have", "and not twice")
            async def fake_from_url3(url):
                return {"url": u("te"), "filename": "qwen_image_vae.safetensors", "sha256": None, "size": 10, "source": "huggingface"}
            smf.sources.from_url = fake_from_url3
            real_inv = smf.paths.Inventory

            class InvWithVae:
                base = {"vae": {"qwen_image_vae.safetensors": "Qwen\qwen_image_vae.safetensors"}}
            smf.paths.Inventory = InvWithVae
            try:
                hv = await ext.download_url("https://huggingface.co/Comfy-Org/Krea-2/blob/main/vae/qwen_image_vae.safetensors", "vae", dry_run=True)
            finally:
                smf.paths.Inventory = real_inv
            check(hv["status"] == "have" and hv["rel"] == "Qwen/qwen_image_vae.safetensors", f"the same file name in a subfolder counts as yours, even unhashed ({hv['status']} {hv.get('rel')})")
        finally:
            await smf.net.close()
            await runner.cleanup()

    asyncio.run(run())
    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    return 1 if check.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

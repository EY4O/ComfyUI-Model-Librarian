"""Saved-workflow repair after moves, and embedding model sources (through the HTTP route)."""
import asyncio
import json
import os
import shutil
import sys

import test_shared as T

check = T.check
S = os.sep


def main():
    for d in ("Pony", "A", "B"):
        os.makedirs(os.path.join(T.LORA, d), exist_ok=True)
    for rel in ("Pony/moved.safetensors", "A/dup.safetensors", "B/dup.safetensors", "kept.safetensors"):
        open(os.path.join(T.LORA, *rel.split("/")), "wb").write(rel.encode())
    base, user = T.fake_install("WF")
    smf = T.load_smf(base, user)
    wdir = os.path.join(user, "default", "workflows", "sub")
    os.makedirs(wdir, exist_ok=True)
    moved_new = f"Pony{S}moved.safetensors"
    wf = {
        "nodes": [
            {"id": 1, "type": "LoraLoader", "widgets_values": ["moved.safetensors", 1, 1]},
            {"id": 2, "type": "LoraLoader", "widgets_values": [moved_new, 1, 1]},
            {"id": 3, "type": "LoraLoader", "widgets_values": ["nothere.safetensors", 1, 1]},
            {"id": 4, "type": "LoraLoader", "widgets_values": ["dup.safetensors", 1, 1]},
            {"id": 5, "type": "Power Lora Loader (rgthree)",
             "widgets_values": [{}, {"on": True, "lora": "Old/moved.safetensors", "strength": 1}, "a prompt"]},
            {"id": 6, "type": "LoraLoader", "widgets_values": ["kept.safetensors", 1, 1],
             "properties": {"models": [{"name": "moved.safetensors", "url": "https://x"}]}},
        ],
        "definitions": {"subgraphs": [{"nodes": [{"id": 9, "widgets_values": ["moved.safetensors"]}]}]},
        "models": [{"name": "moved.safetensors", "directory": "loras"}],
    }
    p = os.path.join(wdir, "test.json")
    json.dump(wf, open(p, "w"))  # single-line, like ComfyUI saves
    json.dump({"nodes": [{"id": 1, "widgets_values": ["kept.safetensors"]}]}, open(os.path.join(wdir, "fine.json"), "w"))

    r = smf.workflows.scan(apply=False)
    w = {x["file"]: x for x in r["workflows"]}
    item = w.get("default/workflows/sub/test.json")
    check(item is not None and "default/workflows/sub/fine.json" not in w, "only workflows with problems are listed")
    fixes = {f["old"]: f["new"] for f in item["fixes"]}
    check(fixes.get("moved.safetensors") == moved_new and fixes.get("Old/moved.safetensors") == moved_new,
          "moved model repointed (plain + nested rgthree value)")
    check(item["missing"] == ["nothere.safetensors"], "not-installed model reported as missing")
    check(item["ambiguous"] == ["dup.safetensors"], "name matching two files is ambiguous, not guessed")
    check(json.load(open(p)) == wf, "check-only run changes nothing")

    r = smf.workflows.scan(apply=True)
    out = json.load(open(p))
    vals = [n["widgets_values"] for n in out["nodes"]]
    check(vals[0][0] == moved_new and vals[4][1]["lora"] == moved_new, "widget values rewritten")
    check(vals[3][0] == "dup.safetensors" and vals[2][0] == "nothere.safetensors", "ambiguous/missing left alone")
    check(out["definitions"]["subgraphs"][0]["nodes"][0]["widgets_values"][0] == moved_new, "subgraph definitions fixed")
    check(out["models"][0]["name"] == moved_new and out["nodes"][5]["properties"]["models"][0]["name"] == moved_new,
          "embedded model names fixed")
    check(out["nodes"][4]["widgets_values"][2] == "a prompt", "non-model strings untouched")
    check("\n" not in open(p).read().strip(), "single-line formatting kept")
    bak = os.path.join(r["backup_dir"], "default", "workflows", "sub", "test.json")
    check(os.path.isfile(bak) and json.load(open(bak)) == wf, "original backed up")
    check(smf.workflows.scan(apply=False)["fixable_files"] == 0, "second run: nothing left to fix")

    # ---- embed sources, through the real HTTP route
    from aiohttp import web
    kept = os.path.join(T.LORA, "kept.safetensors")
    smf.hashing.store(kept, "aa" * 32)
    smf.registry.remember("kept.safetensors", "https://civitai.com/api/download/models/1", source="civitai", sha256="aa" * 32)
    smf.registry.remember("Pony/moved.safetensors", "https://civitai.com/api/download/models/2", source="civitai", sha256="ff" * 32)
    smf.hashing.store(os.path.join(T.LORA, "Pony", "moved.safetensors"), "bb" * 32)

    async def nowhere(*a, **k):
        return None
    smf.sources.civitai_by_hash = nowhere  # files without a recorded source: CivitAI, then CivArchive (offline here)
    smf.civarchive._page = nowhere

    async def go():
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
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.post(f"http://127.0.0.1:{port}/sm-fetcher/workflows/sources", json={"items": [
                        {"value": "kept.safetensors", "folder": "loras"},
                        {"value": moved_new, "folder": "loras"},
                        {"value": "nothere.safetensors", "folder": "loras"}]}) as r:
                    return await r.json()
        finally:
            await runner.cleanup()
    res = {x["value"]: x for x in asyncio.run(go())["sources"]}
    k = res["kept.safetensors"]
    check(k["url"].endswith("/models/1") and k["sha256"] == "aa" * 32 and k["folder"] == "loras", "source found with hash + folder")
    check(res[moved_new]["url"] is None and res[moved_new].get("note") == "no known source", "registry entry for a different file isn't used")
    check(res["nothere.safetensors"]["url"] is None and res["nothere.safetensors"]["note"] == "not installed", "model not installed: no source")

    # ---- health: every saved workflow checked for missing models
    import types

    class KSampler:
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"model": ("MODEL",), "seed": ("INT", {"default": 0}), "steps": ("INT",),
                                 "sampler_name": (["euler", "dpmpp_2m"],), "positive": ("CONDITIONING",)}}

    class DualLoader:  # two model lists: the position decides which one a value is
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"clip_name1": (["a.safetensors"],), "clip_name2": ("COMBO", {"options": ["b.safetensors"]}),
                                 "type": (["flux", "sd3"],)}, "optional": {"device": (["default", "cpu"],)}}

    class Dynamic:  # widgets added at run time: fall back to its one model list
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"strength": ("FLOAT",), "lora": ([],)}, "optional": {"hidden": ("STRING", {"forceInput": True})}}

    class RIFE:  # lists the models it downloads itself on first use
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"ckpt_name": (["rife47.pth", "rife49.pth"],), "multiplier": ("INT",)}}

    sys.modules["nodes"] = types.SimpleNamespace(NODE_CLASS_MAPPINGS={"KSampler": KSampler, "DualCLIPLoader": DualLoader, "MyLoader": Dynamic, "RIFE VFI": RIFE})
    inf = smf.infer
    inf.clear_cache()
    check(inf.widget_names("KSampler") == ["seed", "control_after_generate", "steps", "sampler_name"], "widget order (seed has a control value)")
    check(inf.widget_at("DualCLIPLoader", 1) == "clip_name2" and inf.widget_at("DualCLIPLoader", 0) == "clip_name1", "widget from its position")
    check(inf.widget_at("MyLoader", 5) == "lora" and inf.widget_at("Unknown", 0) == "", "fallback: the node's only model list; unknown nodes → ''")
    check("hidden" not in inf.widget_names("MyLoader"), "forceInput inputs aren't widgets")

    hd = os.path.join(user, "default", "workflows", "health")
    os.makedirs(hd, exist_ok=True)
    json.dump({"nodes": [
        {"id": 1, "type": "CheckpointLoaderSimple", "widgets_values": ["gone_ckpt.safetensors"]},
        {"id": 2, "type": "LoraLoader", "widgets_values": ["kept.safetensors", 1, 1]},
        {"id": 3, "type": "Lora Loader (LoraManager)", "widgets_values": ["<lora:x:1>", [{"name": "lm_missing", "strength": 1, "active": True},
                                                                                        {"name": "lm_off", "active": False}]]},
        {"id": 4, "type": "Note", "widgets_values": ["download note_model.safetensors"]},
        {"id": 5, "type": "LoraLoader", "widgets_values": ["nothere.safetensors", 1, 1],
         "properties": {"models": [{"name": "nothere.safetensors", "url": "https://huggingface.co/x/nothere.safetensors", "directory": "loras"}]}},
    ], "definitions": {"subgraphs": [{"id": "sg1", "nodes": [{"id": 7, "type": "UNETLoader", "widgets_values": ["sub_unet.safetensors", "default"]}]}]}},
        open(os.path.join(hd, "a.json"), "w"))
    json.dump({"nodes": [{"id": 1, "type": "Text (LoraManager)", "widgets_values": ["a cat <lora:lm_missing:0.6>"]},
                         {"id": 3, "type": "RIFE VFI", "widgets_values": ["rife49.pth", 2]},
                         {"id": 2, "type": "Lora Randomizer (LoraManager)", "widgets_values": [[{"name": "random_pick", "active": True}]]}]},
              open(os.path.join(hd, "b.json"), "w"))
    open(os.path.join(hd, "broken.json"), "w").write("{not json")
    smf.paths.invalidate()
    h = smf.workflows.health()
    items = {(i["value"], i["folder"]): i for i in h["items"]}
    wfs = {w["file"]: w for w in h["workflows"]}
    a = wfs["default/workflows/health/a.json"]
    check(items[("gone_ckpt.safetensors", "checkpoints")]["status"] == "missing", "missing checkpoint, folder from the node type")
    check(items[("sub_unet.safetensors", "diffusion_models")]["workflows"] == ["default/workflows/health/a.json"], "subgraph models count, with their workflow")
    lm = items[("lm_missing", "loras")]
    check(lm["lm"] and lm["status"] == "missing" and lm["workflows"] == ["default/workflows/health/a.json", "default/workflows/health/b.json"],
          "LoRA Manager names from the list and from <lora:> text, shared across workflows")
    check(not any(v == "lm_off" or v == "random_pick" or "note_model" in v for v, _ in items), "inactive LoRAs, randomizers and notes skipped")
    check(items[("nothere.safetensors", "loras")]["embedded"]["url"].startswith("https://huggingface.co/"), "embedded source kept for downloads")
    check(items[("kept.safetensors", "loras")]["status"] == "present", "installed model is fine")
    check(a["missing"] == 4 and a["path"] == "workflows/health/a.json" and a["user"] == "default", f"per-workflow counts and userdata path ({a})")
    check(wfs["default/workflows/health/broken.json"].get("error"), "unreadable workflow reported, not fatal")
    check(h["workflows"][0]["file"] == "default/workflows/health/a.json", "worst workflow first")
    rife = next(i for i in h["items"] if i["value"] == "rife49.pth")
    check(rife["status"] == "present" and rife["how"] == "node-provided", "a model the node offers itself isn't missing")
    del sys.modules["nodes"]

    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    shutil.rmtree(T.ROOT, ignore_errors=True)
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()

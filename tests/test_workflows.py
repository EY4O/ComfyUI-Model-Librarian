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
    check(k["url"].endswith("/models/1") and k["hash"] == "aa" * 32 and k["directory"] == "loras", "source found with hash + directory")
    check(res[moved_new]["url"] is None and "different file" in res[moved_new].get("note", ""), "registry entry for a different file isn't embedded")
    check(res["nothere.safetensors"]["url"] is None, "unknown model: no source")

    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    shutil.rmtree(T.ROOT, ignore_errors=True)
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()

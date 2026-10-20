"""Recipe planner tests with CivitAI mocked (reuses the fake-install helpers)."""
import asyncio
import os
import shutil
import sys

import test_shared as T

check = T.check


def main():
    os.makedirs(os.path.join(T.LORA, "Illustrious"), exist_ok=True)
    os.makedirs(os.path.join(T.MODELS, "StableDiffusion", "Pony"), exist_ok=True)
    have = os.path.join(T.LORA, "Illustrious", "hashed.safetensors")
    open(have, "wb").write(b"\1" * 2048)
    already = os.path.join(T.MODELS, "StableDiffusion", "Pony", "ponyAlready.safetensors")
    open(already, "wb").write(b"\2" * 10)
    open(os.path.join(T.LORA, "byname.safetensors"), "wb").write(b"\3" * 10)
    base, user = T.fake_install("ComfyR")
    smf = T.load_smf(base, user)
    smf.hashing.store(have, "11" * 32)

    versions = {
        101: {"id": 101, "modelId": 1, "name": "v2", "baseModel": "Illustrious", "model": {"name": "Style", "type": "LORA"},
              "files": [{"name": "wrong.safetensors", "primary": True, "sizeKB": 1, "hashes": {"SHA256": "AA" * 32, "AutoV2": "AAAAAAAAAA"},
                         "downloadUrl": "https://civitai.red/api/download/models/101?type=a"},
                        {"name": "right.safetensors", "sizeKB": 2, "hashes": {"SHA256": "BB" * 32, "AutoV2": "BBBBBBBBBB"},
                         "downloadUrl": "https://civitai.com/api/download/models/101?type=b"}]},
    }
    by_hash = {
        "cccccccccc": {"id": 202, "modelId": 2, "name": "v1", "baseModel": "Pony", "model": {"name": "PonyCk", "type": "Checkpoint"},
                       "files": [{"name": "ponyCk.safetensors", "primary": True, "sizeKB": 5, "hashes": {"SHA256": "CC" * 32, "AutoV2": "CCCCCCCCCC"},
                                  "downloadUrl": "https://civitai.com/api/download/models/202"}]},
        "dddddddddd": {"id": 303, "modelId": 3, "name": "v1", "baseModel": "Pony", "model": {"name": "Already", "type": "Checkpoint"},
                       "files": [{"name": "ponyAlready.safetensors", "primary": True, "hashes": {"AutoV2": "DDDDDDDDDD"},
                                  "downloadUrl": "https://civitai.com/api/download/models/303"}]},
    }
    calls = []

    async def fake_get_json(url, params=None, timeout=30):
        calls.append(url)
        if "/model-versions/by-hash/" in url:
            return by_hash.get(url.rsplit("/", 1)[-1].lower())
        if "/model-versions/" in url:
            return versions.get(int(url.rsplit("/", 1)[-1]))
        return None
    smf.net.get_json = fake_get_json

    async def no_resolve(*a, **k):
        return []
    smf.sources.resolve = no_resolve

    loras = [
        {"name": "LM has it", "existsLocally": True, "localPath": "X:/Lora/lm.safetensors", "weight": 0.7},
        {"name": "In hash cache", "hash": "11" * 32, "weight": 1},
        {"name": "Style", "id": 101, "hash": "bbbbbbbbbb", "weight": 0.85, "file_name": "right"},
        {"name": "By name", "file_name": "byname", "weight": 0.5},
        {"name": "Gone", "isDeleted": True, "hash": "eeeeeeeeee", "file_name": "gone"},
    ]
    checkpoint = {"name": "PonyCk", "hash": "cccccccccc"}
    res = asyncio.run(smf.recipes.plan(loras, checkpoint))
    items = {i["name"]: i for i in res["items"]}

    check(res["items"][0]["kind"] == "checkpoint", "checkpoint listed first")
    check(items["LM has it"]["status"] == "present" and items["LM has it"]["matched_by"] == "LoRA Manager", "present via LoRA Manager flag")
    check(items["In hash cache"]["status"] == "present" and items["In hash cache"]["matched_by"] == "hash", "present via our hash cache")
    check(items["By name"]["status"] == "present" and items["By name"]["matched_by"] == "file name", "present via file name")
    s = items["Style"]
    d = s["download"] or {}
    check(s["status"] == "missing" and d.get("rel") == "Illustrious/right.safetensors", "LoRA by version id: short hash picks the right file, filed in Illustrious/")
    check(d.get("sha256") == "bb" * 32 and d.get("folder") == "loras", "download verified against that file's SHA256")
    check(s["weight"] == 0.85, "strength kept")
    check((d.get("meta") or {}).get("baseModel") == "Illustrious", "CivitAI metadata passed on for .cm-info.json")
    ck = items["PonyCk"]["download"] or {}
    check(ck.get("folder") == "checkpoints" and ck.get("rel") == "Pony/ponyCk.safetensors", "checkpoint by short hash -> checkpoints/Pony/")
    check(items["Gone"]["status"] == "unavailable" and "Removed" in (items["Gone"]["note"] or ""), "deleted LoRA -> unavailable with reason")
    check(not any("by-hash/" in c and "11" * 32 in c for c in calls), "no CivitAI call for models already installed")

    res2 = asyncio.run(smf.recipes.plan([], {"name": "Already", "hash": "dddddddddd"}))
    it = res2["items"][0]
    check(it["status"] == "present" and it["matched_by"] == "already downloaded", "existing destination file -> present, no overwrite")

    c = asyncio.run(smf.sources.civitai_by_hash("eeeeeeeeee"))
    check(c is None, "by-hash 404 -> None")
    by_hash["ffffffffff"] = dict(by_hash["cccccccccc"])
    c = asyncio.run(smf.sources.civitai_by_hash("ffffffffff"))
    check(c["sha256"] is None and c["meta"]["hashes"] == {}, "short hash that matches no file: no wrong hashes recorded")

    u = smf.net.canonical_download_url("https://civitai.red/api/download/models/101?type=a")
    check(u == "https://civitai.com/api/download/models/101?type=a", "civitai.red download -> civitai.com")
    check(smf.net.canonical_download_url("https://civitai.red/images/5") == "https://civitai.red/images/5", "non-download links untouched")

    # CivitAI image data often names a resource only by its version id: the item takes the model's name
    blank = {"kind": "lora", "name": "?", "file": None, "version": "", "weight": 0.8, "base_model": "", "hash": None, "status": "missing",
             "local": None, "comfy_name": None, "matched_by": None, "download": None, "note": None, "page_url": None}
    cand = {"url": "https://civitai.com/api/download/models/55", "filename": "sinozick_v1.safetensors", "folder": "loras", "source": "civitai",
            "meta": {"modelName": "Sinozick Style", "versionName": "v1.0", "baseModel": "Pony"}}
    it = smf.recipes._with_download(dict(blank), cand, "lora")
    check(it["name"] == "Sinozick Style" and it["version"] == "v1.0", f"a resource known only by version id gets its model's name ({it['name']}, {it['version']})")

    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    shutil.rmtree(T.ROOT, ignore_errors=True)
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()

"""Hard-link dedupe and the unused-models report."""
import asyncio
import json
import os
import shutil
import sys
import time

import test_shared as T

check = T.check


def put(rel, data):
    p = os.path.join(T.LORA, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(data)
    return p


def main():
    base, user = T.fake_install("Dedupe")
    blob = os.urandom(2 * 1024 * 1024)
    keep = put("Illustrious/style.safetensors", blob)
    dup = put("copies/style_copy.safetensors", blob)
    dup2 = put("copies/style_copy2.safetensors", blob)
    smf = T.load_smf(base, user)

    async def scan():
        await smf.organize.find_duplicates(["loras"])
        while smf.organize.dup_status()["status"] == "running":
            await asyncio.sleep(0.05)
        return smf.organize.dup_status()
    st = asyncio.run(scan())
    g = st["groups"][0]
    check(len(st["groups"]) == 1 and len(g["duplicates"]) == 2, "duplicates found")
    keep_path = smf.library.get(g["keep"]["id"])["path"]
    ids = [d["id"] for d in g["duplicates"]]

    # a duplicate that changed after the scan must not be linked
    changed = smf.library.get(ids[1])["path"]
    time.sleep(0.05)
    with open(changed, "r+b") as f:
        f.write(b"X")
    r = smf.organize.hardlink(ids)
    res = {x["id"]: x for x in r["results"]}
    check(res[ids[1]]["ok"] is False and "changed" in res[ids[1]]["error"], "file changed since the scan: not linked")
    linked = smf.library.get(ids[0])["path"]
    a, b = os.stat(keep_path), os.stat(linked)
    check(res[ids[0]]["ok"] and a.st_ino == b.st_ino and a.st_ino != 0, "duplicate is now a hard link to the kept file")
    check(open(linked, "rb").read() == blob and r["freed"] == len(blob), "contents intact, space freed reported")
    check(not os.path.exists(linked + ".smf-link"), "no temp link left behind")
    st2 = asyncio.run(scan())
    check(all(smf.library.get(d["id"])["path"] != linked for gg in st2["groups"] for d in gg["duplicates"]),
          "linked copy no longer reported as a duplicate")

    # ---- unused models
    for name in ("used_by_name", "lm_entry", "in_text", "in_recipe", "never_used"):
        put(f"u/{name}.safetensors", name.encode() * 10)
    smf = T.load_smf(base, user)
    rec = os.path.join(T.LORA, "u", "in_recipe.safetensors")
    smf.hashing.store(rec, "9" * 64)
    wdir = os.path.join(user, "default", "workflows")
    os.makedirs(wdir, exist_ok=True)
    json.dump({"nodes": [
        {"type": "LoraLoader", "widgets_values": ["u\\used_by_name.safetensors", 1, 1]},
        {"type": "Lora Loader (LoraManager)", "widgets_values": ["", [{"name": "lm_entry", "strength": 1, "active": True}]]},
        {"type": "Text (LoraManager)", "widgets_values": ["a cat <lora:in_text:0.6>"]},
    ]}, open(os.path.join(wdir, "w.json"), "w"))
    os.makedirs(os.path.join(T.LORA, "recipes"), exist_ok=True)
    json.dump({"loras": [{"file_name": "renamed_in_recipe", "hash": "9" * 64}], "checkpoint": "ck.safetensors"},
              open(os.path.join(T.LORA, "recipes", "r.recipe.json"), "w"))
    u = smf.usage.unused("loras")
    names = {smf.library.get(i)["name"] for i in u["unused_ids"]}
    check("never_used.safetensors" in names, "unreferenced model reported unused")
    for n in ("used_by_name", "lm_entry", "in_text", "in_recipe"):
        check(f"{n}.safetensors" not in names, f"used: {n.replace('_', ' ')}")
    check(u["workflows"] == 1 and u["recipes"] == 1, "counts workflows and recipes scanned")

    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    shutil.rmtree(T.ROOT, ignore_errors=True)
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()

"""Metadata bridge: LoRA Manager .metadata.json <-> Stability Matrix .cm-info.json."""
import json
import os
import shutil
import sys

import test_shared as T

check = T.check


def mk(name, data=b"\0" * 32):
    p = os.path.join(T.LORA, name)
    open(p, "wb").write(data)
    return p


def main():
    os.makedirs(T.LORA, exist_ok=True)
    base, user = T.fake_install("Bridge")
    smf = T.load_smf(base, user)
    stem = lambda p: os.path.splitext(p)[0]  # noqa: E731
    sha_a = "a1" * 32

    # 1) LM has CivitAI data, no SM info; LM has a .webp preview
    a = mk("fromLM.safetensors", b"\1" * 40)
    open(stem(a) + ".webp", "wb").write(b"RIFFwebp")
    json.dump({"file_name": "fromLM", "model_name": "From LM", "file_path": a.replace("\\", "/"), "sha256": sha_a,
               "base_model": "Illustrious", "preview_url": (stem(a) + ".webp").replace("\\", "/"),
               "civitai": {"id": 11, "modelId": 1, "name": "v1", "baseModel": "Illustrious", "trainedWords": ["tw1"],
                           "model": {"name": "From LM", "type": "LORA", "tags": ["style"]},
                           "creator": {"username": "maker"},
                           "files": [{"name": "fromLM.safetensors", "id": 5, "primary": True,
                                      "hashes": {"SHA256": sha_a.upper(), "AutoV2": "A1A1A1A1A1"}}],
                           "images": [{"url": "https://img/1.jpg", "type": "image"}]}},
              open(stem(a) + ".metadata.json", "w"))

    # 2) SM has CivitAI data, LM entry is bare (LM hashed it but never fetched)
    b = mk("fromSM.safetensors", b"\2" * 40)
    json.dump({"ModelId": 2, "ModelName": "From SM", "VersionId": 22, "VersionName": "v2", "BaseModel": "Pony",
               "ModelType": "LORA", "Tags": ["char"], "TrainedWords": ["tw2"], "AuthorUsername": "smuser",
               "Hashes": {}, "ThumbnailImageUrl": "https://img/2.jpg"}, open(stem(b) + ".cm-info.json", "w"))
    json.dump({"file_name": "fromSM", "model_name": "fromSM", "file_path": b.replace("\\", "/"), "sha256": "b2" * 32,
               "base_model": "", "preview_url": "", "civitai": {}, "from_civitai": False, "favorite": True},
              open(stem(b) + ".metadata.json", "w"))

    # 3) SM data, no LM file, hashed by us -> new LM entry; 4) same but not hashed -> skipped
    c = mk("newLM.safetensors", b"\3" * 40)
    smf.hashing.store(c, "c3" * 32)
    json.dump({"ModelId": 3, "VersionId": 33, "ModelName": "New", "Hashes": {"SHA256": ("c3" * 32).upper()}},
              open(stem(c) + ".cm-info.json", "w"))
    d = mk("unhashed.safetensors", b"\4" * 40)
    json.dump({"ModelId": 4, "VersionId": 44, "ModelName": "Unhashed"}, open(stem(d) + ".cm-info.json", "w"))
    # 5) SM hash disagrees with the file -> never create LM metadata from it
    e = mk("mismatch.safetensors", b"\5" * 40)
    smf.hashing.store(e, "e5" * 32)
    json.dump({"ModelId": 5, "VersionId": 55, "Hashes": {"SHA256": "FF" * 32}}, open(stem(e) + ".cm-info.json", "w"))

    p = smf.bridge.plan(["loras"])
    acts = {it["name"]: it["actions"] for it in p["items"]}
    check(acts.get("fromLM.safetensors") == ["to_sm", "preview"], f"LM-only model: write SM info + copy preview ({acts.get('fromLM.safetensors')})")
    check(acts.get("fromSM.safetensors") == ["sha_to_sm", "to_lm"], f"SM-only CivitAI data: fill LM + SHA to SM ({acts.get('fromSM.safetensors')})")
    check(acts.get("newLM.safetensors") == ["new_lm"], "hashed LoRA with SM data: create LM entry")
    skipped = {s["name"]: s["why"] for s in p["skipped"]}
    check("unhashed.safetensors" in skipped and "unhashed.safetensors" not in acts, "unhashed: skipped, not trusted")
    check("mismatch.safetensors" in skipped and "doesn't match" in skipped["mismatch.safetensors"], "SHA mismatch: skipped with reason")

    r = smf.bridge.apply([it["id"] for it in p["items"]])
    check(r["failed"] == 0 and r["lm_sections"] == ["loras"], "apply ok; LM rebuild requested for loras")

    cm = json.load(open(stem(a) + ".cm-info.json"))
    check(cm["ModelId"] == 1 and cm["VersionId"] == 11 and cm["BaseModel"] == "Illustrious", "SM info from LM: ids + base model")
    check(cm["Hashes"] == {"SHA256": sha_a.upper()}, "SM info: SHA256 (SM's format has no AutoV2 field)")
    check(cm["TrainedWords"] == ["tw1"] and cm["AuthorUsername"] == "maker", "SM info: trigger words + author")
    check(os.path.isfile(stem(a) + ".preview.webp"), "preview copied as <stem>.preview.webp")

    lm = json.load(open(stem(b) + ".metadata.json"))
    check(lm["civitai"]["id"] == 22 and lm["civitai"]["modelId"] == 2 and lm["from_civitai"], "LM filled from SM: ids")
    check(lm["model_name"] == "From SM" and lm["base_model"] == "Pony" and lm["civitai"]["trainedWords"] == ["tw2"], "LM: name, base model, triggers")
    check(lm["favorite"] is True and lm["sha256"] == "b2" * 32, "LM's own fields (favorite, sha256) untouched")
    check(json.load(open(stem(b) + ".cm-info.json"))["Hashes"]["SHA256"] == ("b2" * 32).upper(), "SM gets LM's SHA256")

    new = json.load(open(stem(c) + ".metadata.json"))
    check(new["sha256"] == "c3" * 32 and new["civitai"]["id"] == 33 and new["hash_status"] == "completed", "new LM entry with verified hash")
    check(new["file_path"] == c.replace("\\", "/") and new["file_name"] == "newLM", "new LM entry: path + stem")
    check(not os.path.exists(stem(d) + ".metadata.json") and not os.path.exists(stem(e) + ".metadata.json"), "nothing created from untrusted hashes")

    p2 = smf.bridge.plan(["loras"])
    check(not p2["items"], f"second run: already in sync ({[i['actions'] for i in p2['items']]})")

    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    shutil.rmtree(T.ROOT, ignore_errors=True)
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()

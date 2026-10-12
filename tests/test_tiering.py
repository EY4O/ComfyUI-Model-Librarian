"""SSD/HDD storage tiers: usage tracking, archive suggestions, verified archive/restore, restore after use."""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time

import test_shared as T

check = T.check


def install_folder_paths(roots: dict):
    """A folder_paths stub that, like ComfyUI's, supports extra folders per type."""
    fp = sys.modules["folder_paths"]
    fp.folder_names_and_paths = {k: (v, set()) for k, v in roots.items()}

    def get_folder_paths(k):
        return list(roots.get(k, []))

    def add_model_folder_path(k, p, is_default=False):
        lst = roots.setdefault(k, [])
        if p not in lst:
            lst.insert(0, p) if is_default else lst.append(p)
        fp.folder_names_and_paths[k] = (lst, set())

    def get_filename_list(k):
        seen = []
        for r in roots.get(k, []):
            for dp, _, fns in os.walk(r):
                for fn in fns:
                    if fn.endswith((".safetensors", ".gguf")):
                        rel = os.path.relpath(os.path.join(dp, fn), r)
                        if rel not in seen:
                            seen.append(rel)
        return seen

    def get_full_path(k, name):
        for r in roots.get(k, []):
            p = os.path.join(r, name)
            if os.path.isfile(p):
                return p
        return None
    fp.get_folder_paths, fp.add_model_folder_path = get_folder_paths, add_model_folder_path
    fp.get_filename_list, fp.get_full_path = get_filename_list, get_full_path


def put(rel, data=b"\0" * 4096):
    p = os.path.join(T.LORA, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(data)
    return p


def main():
    base, user = T.fake_install("Tier")
    hdd = tempfile.mkdtemp(prefix="smf_hdd_")
    idle = put("Illustrious/idle.safetensors", os.urandom(300_000))
    open(os.path.splitext(idle)[0] + ".preview.png", "wb").write(b"png")
    busy_f = put("Illustrious/busy.safetensors", os.urandom(1000))
    fresh = put("fresh.safetensors", os.urandom(1000))
    smf = T.load_smf(base, user)
    roots = {"loras": [T.LORA]}
    install_folder_paths(roots)

    # ---- which models does a queued prompt use?
    prompt = {
        "1": {"class_type": "LoraLoader", "inputs": {"lora_name": "Illustrious\\busy.safetensors", "strength_model": 1}},
        "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "ck.safetensors"}},
        "3": {"class_type": "Lora Loader (LoraManager)", "inputs": {"text": "x", "loras": {"__value__": [
            {"name": "lmA", "strength": 1, "active": True}, {"name": "lmOff", "strength": 1, "active": False}]}}},
        "4": {"class_type": "Text (LoraManager)", "inputs": {"text": "cat <lora:inText:0.5>"}},
        "5": {"class_type": "Power Lora Loader (rgthree)", "inputs": {"lora_1": {"on": True, "lora": "rg.safetensors", "strength": 1},
                                                                       "lora_2": {"on": False, "lora": "rgOff.safetensors"}}},
        "6": {"class_type": "KSampler", "inputs": {"sampler_name": "euler", "seed": 1}},
    }
    got = set(smf.tiering.models_in_prompt(prompt))
    want = {("loras", "Illustrious\\busy.safetensors"), ("checkpoints", "ck.safetensors"), ("loras", "lmA"),
            ("loras", "inText"), ("loras", "rg.safetensors")}
    check(got == want, f"models found in a prompt: plain, LM list, <lora:> text, rgthree; inactive skipped ({got ^ want or 'ok'})")

    # ---- suggestions: idle for N days (first-seen counts for never-used models)
    smf.config.save({"archive_dir": hdd, "archive_after_days": 30, "archive_sections": ["loras"]})
    check(smf.config.load()["archive_sections"] == ["loras"], "archive sections saved as a plain list")
    smf.tiering.reset_cache()
    smf.tiering.plan()  # first look: everything gets first_seen = now
    k_idle = smf.tiering.key_for("loras", "idle.safetensors")
    smf.config.update_json("usage.json", {}, lambda u: u["first_seen"].__setitem__(k_idle, time.time() - 40 * 86400))
    k_busy = smf.tiering.key_for("loras", "busy.safetensors")
    smf.config.update_json("usage.json", {}, lambda u: u["first_seen"].__setitem__(k_busy, time.time() - 90 * 86400))
    smf.tiering.record_use(smf.tiering.models_in_prompt(prompt))  # busy was used just now
    p = smf.tiering.plan()
    ready = {x["name"] for x in p["ready"]}
    check(ready == {"idle.safetensors"}, f"only the idle model is suggested ({ready})")
    check(p["connected"] and p["free"] > 0, "archive drive connected, free space reported")
    check(p["goal"] and p["goal"]["goal"] is None and p["goal"]["free"] > 0, "SSD free space reported; no goal set")

    # ---- free-space goal: least recently used models added until the goal would be met
    k_fresh = smf.tiering.key_for("loras", "fresh.safetensors")
    smf.config.update_json("usage.json", {}, lambda u: u["first_seen"].__setitem__(k_fresh, time.time() - 20 * 86400))
    real_free = smf.tiering.free_bytes
    smf.tiering.free_bytes = lambda path: 0
    GB = 1024 ** 3
    smf.config.save({"free_goal_gb": 200_000 / GB})  # idle.safetensors (300 KB) alone covers it
    g = smf.tiering.plan()
    check(g["goal"]["reachable"] and g["goal"]["picked"] == 0 and {x["name"] for x in g["ready"]} == {"idle.safetensors"},
          "goal already met by the time-based suggestions: nothing added")
    smf.config.save({"free_goal_gb": 600_000 / GB})
    g = smf.tiering.plan()
    reasons = {x["name"]: x["reason"] for x in g["ready"]}
    check(reasons == {"idle.safetensors": "idle", "fresh.safetensors": "goal"},
          f"below the goal: least recently used model added, the one used just now protected ({reasons})")
    check(not g["goal"]["reachable"] and g["goal"]["after"] == 301_000 and g["ready"][0]["name"] == "fresh.safetensors",
          "goal out of reach is reported; goal suggestions listed first")
    smf.config.save({"protect_days": 0})
    g = smf.tiering.plan()
    check({x["name"] for x in g["ready"]} == {"idle.safetensors", "fresh.safetensors", "busy.safetensors"}, "protection period 0: recently used models allowed")
    smf.config.save({"free_goal_gb": 0, "protect_days": 14})
    smf.tiering.free_bytes = real_free
    check({x["name"] for x in smf.tiering.plan()["ready"]} == {"idle.safetensors"}, "goal off: back to time-based suggestions")

    # ---- archive (verified), names unchanged, sidecars moved, undoable
    async def run_job(kind, ids):
        await smf.tiering.start_job(kind, ids)
        while smf.tiering.job_status()["status"] == "running":
            await asyncio.sleep(0.05)
        return smf.tiering.job_status()
    idle_id = next(x["id"] for x in p["ready"])
    j = asyncio.run(run_job("archive", [idle_id]))
    arch = os.path.join(hdd, "Lora", "Illustrious", "idle.safetensors")
    check(j["ok"] == 1 and os.path.isfile(arch) and not os.path.exists(idle), "archived: moved to <archive>/Lora/... and gone from the SSD")
    check(os.path.isfile(os.path.splitext(arch)[0] + ".preview.png"), "sidecar moved with it")
    check(os.path.join(hdd, "Lora") in roots["loras"], "archive folder registered with ComfyUI")
    check(os.path.join("Illustrious", "idle.safetensors") in sys.modules["folder_paths"].get_filename_list("loras"),
          "ComfyUI still lists it under the same name")
    check(smf.hashing.cached(arch) is not None, "hash cache follows the file")
    p = smf.tiering.plan()
    check([x["name"] for x in p["archived"]] == ["idle.safetensors"] and not p["ready"], "plan shows it as archived")
    lib = {e["name"]: smf.library.public(e) for e in smf.library.build("loras")}
    check(lib["idle.safetensors"]["archived"] and not lib["busy.safetensors"]["archived"], "Library flags archived models")
    check(not any(m["name"] == "idle.safetensors" for m in smf.organize.plan(["loras"], "full")["moves"]), "Organize leaves the archive alone")
    run = smf.organize.history()[0]
    check(run["kind"] == "archive", "archive run logged (undo via Organize history)")

    # ---- drive disconnected -> refused, nothing touched
    smf.config.save({"archive_dir": "Q:\\definitely-not-here"})
    smf.tiering.reset_cache()
    fresh_id = next(e["id"] for e in smf.library.build("loras") if e["name"] == "fresh.safetensors")
    j = asyncio.run(run_job("archive", [fresh_id]))
    check(j["failed"] == 1 and "connected" in j["results"][0]["error"] and os.path.exists(fresh), "disconnected drive: refused, file untouched")
    smf.config.save({"archive_dir": hdd})
    smf.tiering.reset_cache()

    # ---- restore after use: prompt uses the archived model -> back on the SSD when the queue is idle
    smf.tiering.on_prompt({"prompt": {"1": {"class_type": "LoraLoader", "inputs": {"lora_name": os.path.join("Illustrious", "idle.safetensors")}}}})
    for _ in range(80):
        if os.path.exists(idle) and not os.path.exists(arch):
            break
        time.sleep(0.25)
    check(os.path.exists(idle) and not os.path.exists(arch), "used while archived -> moved back to the SSD automatically")
    check(os.path.isfile(os.path.splitext(idle)[0] + ".preview.png"), "its sidecar came back too")
    ev = smf.tiering.events()
    check(any(e["kind"] == "restored" and e.get("auto") for e in ev), "restore reported to the UI (LM rescan + toast)")

    # ---- restore while the archive copy is still open (ComfyUI loaded it from the HDD)
    j = asyncio.run(run_job("archive", [next(e["id"] for e in smf.library.build("loras") if e["name"] == "idle.safetensors")]))
    check(j["ok"] == 1 and os.path.exists(arch), "archived again")
    held = open(arch, "rb")
    try:
        smf.tiering._restore_path(arch)
        check(os.path.exists(idle), "copied back to the SSD even though the HDD copy is open")
        still = os.path.exists(arch)
        cleanup = smf.tiering._usage()["cleanup"]
        check(not still or arch in cleanup, "HDD copy that couldn't be removed is remembered for cleanup")
    finally:
        held.close()
    smf.tiering.retry_cleanup()
    check(not os.path.exists(arch) and not smf.tiering._usage()["cleanup"], "cleanup retried once it's no longer in use")

    # ---- restore when the SSD already has a file with that name
    j = asyncio.run(run_job("archive", [next(e["id"] for e in smf.library.build("loras") if e["name"] == "idle.safetensors")]))
    archived_bytes = open(arch, "rb").read()
    open(idle, "wb").write(b"a different file")
    try:
        smf.tiering._restore_path(arch)
        check(False, "different SSD file: refused")
    except FileExistsError as ex:
        check("both kept" in str(ex), "different SSD file with the same name: refused")
    check(os.path.exists(arch) and open(arch, "rb").read() == archived_bytes, "...and the HDD copy is NOT deleted")
    open(idle, "wb").write(archived_bytes)
    smf.tiering._restore_path(arch)
    check(not os.path.exists(arch) and os.path.exists(idle), "identical SSD file: the redundant HDD copy is removed")

    # ---- undo an archive run
    j = asyncio.run(run_job("archive", [next(e["id"] for e in smf.library.build("loras") if e["name"] == "idle.safetensors")]))
    rid = next(r["id"] for r in smf.organize.history() if r["kind"] == "archive")
    smf.organize.undo(rid)
    check(os.path.exists(idle) and not os.path.exists(arch), "Undo brings an archived model back")

    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    shutil.rmtree(T.ROOT, ignore_errors=True)
    shutil.rmtree(hdd, ignore_errors=True)
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()

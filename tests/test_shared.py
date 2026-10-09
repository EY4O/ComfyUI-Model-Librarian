"""Behavioural tests for shared data + LoRA Manager matching (fake ComfyUI installs)."""
import importlib
import json
import multiprocessing as mp
import os
import shutil
import sys
import tempfile
import time
import types

PLUGIN = os.environ.get("SMF_PLUGIN") or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "comfyui-sm-model-fetcher"))
ROOT = tempfile.mkdtemp(prefix="smf_test_")
MODELS = os.path.join(ROOT, "SM", "Data", "Models")
LORA = os.path.join(MODELS, "Lora")


def fake_install(name):
    base = os.path.join(ROOT, "SM", "Data", "Packages", name)
    user = os.path.join(base, "user")
    os.makedirs(user, exist_ok=True)
    with open(os.path.join(base, "extra_model_paths.yaml"), "w") as f:
        f.write(f"stability_matrix:\n  loras: {LORA}\n  checkpoints: {os.path.join(MODELS, 'StableDiffusion')}\n")
    return base, user


def load_smf(base, user):
    """Fresh import of the plugin modules for a given fake install."""
    fp = types.ModuleType("folder_paths")
    fp.base_path = base
    fp.__file__ = os.path.join(base, "folder_paths.py")
    fp.get_user_directory = lambda: user
    fp.folder_names_and_paths = {"loras": ([LORA], set())}
    fp.get_folder_paths = lambda k: [LORA] if k == "loras" else []

    def names(k):
        out = []
        for dp, _, fns in os.walk(LORA):
            for fn in fns:
                out.append(os.path.relpath(os.path.join(dp, fn), LORA))
        return out if k == "loras" else []
    fp.get_filename_list = names
    fp.get_full_path = lambda k, n: os.path.join(LORA, n)
    sys.modules["folder_paths"] = fp
    for m in [m for m in sys.modules if m == "smf" or m.startswith("smf.")]:
        del sys.modules[m]
    if PLUGIN not in sys.path:
        sys.path.insert(0, PLUGIN)
    import smf.routes  # noqa: F401  (registers every merger)
    return importlib.import_module("smf")


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        check.failed += 1
check.failed = 0


def seed_legacy(user, tag, model_path):
    d = os.path.join(user, "sm_model_fetcher")
    os.makedirs(d, exist_ok=True)
    w = lambda n, o: json.dump(o, open(os.path.join(d, n), "w"))
    w("config.json", {"civitai_token": f"tok-{tag}", "vram_gb": 8.0 if tag == "A" else 24.0})
    w("registry.json", {"version": 1, "entries": {
        f"{tag.lower()}.safetensors": {"filename": f"{tag}.safetensors", "url": "https://x/" + tag, "updated": 1},
        "both.safetensors": {"filename": "both.safetensors", "url": "https://x/both-" + tag,
                             "updated": 5 if tag == "B" else 2}}})
    st = os.stat(model_path)
    w("hash_cache.json", {os.path.abspath(model_path): {"size": st.st_size, "mtime": st.st_mtime, "sha256": "ab" * 32}})
    w("organize_log.json", {"runs": [{"id": "run" + tag, "kind": "organize", "time": 10 if tag == "A" else 20, "moves": []}]})
    w("civitai_not_found.json", {"dead" + tag: 1})


def worker(args):
    base, user, n, tag = args
    smf = load_smf(base, user)
    for i in range(n):
        smf.registry.remember(f"{tag}{i}.safetensors", f"https://x/{tag}{i}", source="test")
    return True


def main():
    os.makedirs(os.path.join(LORA, "Illustrious"), exist_ok=True)
    os.makedirs(os.path.join(MODELS, "StableDiffusion"), exist_ok=True)
    model = os.path.join(LORA, "Illustrious", "styleX.safetensors")
    open(model, "wb").write(b"\0" * 1024)
    open(os.path.join(LORA, "loose.ckpt"), "wb").write(b"\0" * 10)
    open(os.path.join(LORA, "notalora.gguf"), "wb").write(b"\0" * 10)

    baseA, userA = fake_install("ComfyA")
    baseB, userB = fake_install("ComfyB")
    seed_legacy(userA, "A", model)
    seed_legacy(userB, "B", model)
    shared = os.path.join(MODELS, ".sm_model_fetcher")

    # ---- install A starts: detects SM, migrates
    smf = load_smf(baseA, userA)
    smf.routes.register(type("R", (), {"get": lambda *a: (lambda f: f), "post": lambda *a: (lambda f: f),
                                       "delete": lambda *a: (lambda f: f)})())
    check(smf.config.shared_dir() and os.path.samefile(smf.config.shared_dir(), shared), "shared dir = Data/Models/.sm_model_fetcher")
    cfg = smf.config.load()
    check(cfg["civitai_token"] == "tok-A" and cfg["vram_gb"] == 8.0, "A: token local, settings seeded from A")
    shared_cfg = json.load(open(os.path.join(shared, "config.json")))
    check("civitai_token" not in shared_cfg and "share_data" not in shared_cfg, "no secrets in shared config.json")
    check(smf.hashing.cached(model) == "ab" * 32, "legacy abspath hash entry rekeyed and still hits")

    # ---- install B starts: merges into existing shared data
    smf = load_smf(baseB, userB)
    smf.routes.register(type("R", (), {"get": lambda *a: (lambda f: f), "post": lambda *a: (lambda f: f),
                                       "delete": lambda *a: (lambda f: f)})())
    cfg = smf.config.load()
    check(cfg["civitai_token"] == "tok-B", "B keeps its own token")
    check(cfg["vram_gb"] == 8.0, "B sees shared settings (first install's settings win)")
    reg = json.load(open(os.path.join(shared, "registry.json")))["entries"]
    check({"a.safetensors", "b.safetensors", "both.safetensors"} <= set(reg), "registry union of A and B")
    check(reg["both.safetensors"]["url"].endswith("both-B"), "registry conflict -> newest 'updated' wins")
    log = json.load(open(os.path.join(shared, "organize_log.json")))["runs"]
    check([r["id"] for r in log] == ["runA", "runB"], "undo history union, time ordered")
    nf = json.load(open(os.path.join(shared, "civitai_not_found.json")))
    check({"deadA", "deadB"} <= set(nf), "not-found cache union")
    check(len(smf.config.migrate_to_shared()) == 0, "migration runs once per install")

    # ---- settings save in shared mode
    smf.config.save({"vram_gb": 16, "civitai_token": "new-B"})
    check(json.load(open(os.path.join(shared, "config.json")))["vram_gb"] == 16.0, "save writes settings to shared")
    check(json.load(open(os.path.join(userB, "sm_model_fetcher", "config.json")))["civitai_token"] == "new-B", "save writes token locally")
    try:
        smf.config.save({"vram_gb": ""})
        check(False, "empty vram rejected")
    except ValueError:
        check(True, "empty vram -> ValueError (400), not a crash")

    # ---- hash cache batching + rename
    smf.hashing.store(model, "cd" * 32)
    smf.hashing.flush()
    hc = json.load(open(os.path.join(shared, "hash_cache.json")))
    check(hc["version"] == 2 and any(e["sha256"] == "cd" * 32 for e in hc["entries"].values()), "hash flush writes v2 format")
    newp = os.path.join(LORA, "Illustrious", "styleY.safetensors")
    os.rename(model, newp)
    smf.hashing.rename(model, newp)
    smf.hashing.flush()
    check(smf.hashing.cached(newp) == "cd" * 32, "hash follows a rename")
    os.rename(newp, model)
    smf.hashing.rename(newp, model)
    smf.hashing.flush()

    # ---- another process changes the file: reload picked up
    hc = json.load(open(os.path.join(shared, "hash_cache.json")))
    for e in hc["entries"].values():
        e["sha256"] = "ef" * 32
    json.dump(hc, open(os.path.join(shared, "hash_cache.json"), "w"))
    time.sleep(3.2)
    check(smf.hashing.cached(model) == "ef" * 32, "external hash cache change reloaded")

    # ---- concurrent writers from two processes
    with mp.Pool(2) as pool:
        pool.map(worker, [(baseA, userA, 60, "pa"), (baseB, userB, 60, "pb")])
    reg = json.load(open(os.path.join(shared, "registry.json")))["entries"]
    n = sum(1 for k in reg if k.startswith(("pa", "pb")))
    check(n == 120, f"no lost registry updates across processes ({n}/120)")
    check(not [f for f in os.listdir(shared) if f.endswith((".lock", ".tmp"))], "no stray lock/tmp files")

    # ---- toggle sharing off -> local, back on -> shared
    smf.config.save({"share_data": False})
    check(not smf.config.shared_dir() and smf.config.load()["vram_gb"] == 16.0, "sharing off keeps current settings locally")
    smf.config.save({"share_data": True})
    check(bool(smf.config.shared_dir()), "sharing back on")

    # ---- LoRA Manager name resolution
    inv = smf.paths.Inventory()
    check(inv.find_lm("styleX")[0] == "present", "LM: bare stem in a subfolder resolves")
    check(inv.find_lm("Illustrious/styleX")[0] == "present", "LM: folder/stem resolves")
    check(inv.find_lm("Pony/styleX")[0] == "present", "LM: wrong folder falls back to basename (like LM)")
    check(inv.find_lm("loose")[0] == "present", "LM: .ckpt LoRA resolves")
    check(inv.find_lm("notalora")[0] == "missing", "LM: .gguf isn't an LM LoRA")
    check(inv.find_lm("nope")[0] == "missing", "LM: missing name")
    g = smf.routes._lm_group("Pony/newOne", inv)
    check(g["status"] == "missing" and g["dest"].replace("\\", "/").endswith("Lora/Pony/newOne.safetensors"),
          "LM missing -> dest keeps requested name + .safetensors")
    check(g["search_name"] == "newOne.safetensors", "LM search name has an extension")
    check(smf.routes._lm_group(model[:-12], inv)["status"] == "present", "LM absolute path that exists")
    check(smf.net.is_civitai("https://civitai.red/api/download/models/1"), "civitai.red gets the CivitAI key")

    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    shutil.rmtree(ROOT, ignore_errors=True)
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()

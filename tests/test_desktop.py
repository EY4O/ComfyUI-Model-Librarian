"""Merged ComfyUI Desktop fixes: SM-named folder keys, dest preference, local-by-sha names."""
import os
import shutil
import sys

import test_shared as T

check = T.check


def main():
    os.makedirs(os.path.join(T.LORA, "Illustrious"), exist_ok=True)
    f = os.path.join(T.LORA, "Illustrious", "MixedCase.safetensors")
    open(f, "wb").write(b"\5" * 100)
    base, user = T.fake_install("Desktop")
    smf = T.load_smf(base, user)
    fp = sys.modules["folder_paths"]
    names = fp.get_filename_list
    fp.folder_names_and_paths["Lora"] = ([T.LORA], set())  # what Desktop's "Shared Models" adds
    fp.get_filename_list = lambda k: names("loras") if k in ("loras", "Lora") else []

    inv = smf.paths.Inventory()
    check(inv._folders_for("loras") == ["loras"], "Desktop's 'Lora' key isn't treated as a loader folder")
    d, shared = smf.paths.dest_dir("loras")
    check(os.path.normcase(d) == os.path.normcase(os.path.normpath(T.LORA)) and shared, "downloads go to SM's Models/Lora")
    check(smf.paths.canonical("StableDiffusion") == "checkpoints" and smf.paths.canonical("T2IAdapter") == "controlnet",
          "SM folder names map to ComfyUI types")

    smf.hashing.store(f, "77" * 32)
    m = smf.routes._local_by_sha("loras", inv)
    want = os.path.join("Illustrious", "MixedCase.safetensors")
    check(m.get("77" * 32) == want, f"local-by-sha keeps ComfyUI's exact name ({m.get('77' * 32)!r})")
    check("My" in smf.sources.core_tokens("My%20Lora%20v2.safetensors"), "URL-encoded names are decoded for search")

    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    shutil.rmtree(T.ROOT, ignore_errors=True)
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()

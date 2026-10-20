"""After moving off Stability Matrix, its folder names (Lora, DiffusionModels) are junctions to
ComfyUI-named folders. Downloads go to the real, ComfyUI-named folder; a real SM folder still wins."""
import os
import sys

import test_shared as T

check = T.check


def junction(link, target):
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(target, link)
    else:
        os.symlink(target, link)


def main():
    base, user = T.fake_install("JUNCTION")
    real_dm = os.path.join(T.MODELS, "diffusion_models")
    os.makedirs(real_dm, exist_ok=True)
    junction(os.path.join(T.MODELS, "DiffusionModels"), real_dm)
    real_lora_sm = os.path.join(T.MODELS, "Lora")  # a real SM folder (not a junction)
    os.makedirs(real_lora_sm, exist_ok=True)
    os.makedirs(os.path.join(T.MODELS, "loras"), exist_ok=True)
    with open(os.path.join(base, "extra_model_paths.yaml"), "w") as f:
        f.write(f"stability_matrix:\n  base_path: {T.MODELS}\n  diffusion_models: |\n    DiffusionModels\n    diffusion_models\n"
                f"  loras: |\n    Lora\n    loras\n  checkpoints: StableDiffusion\n")
    smf = T.load_smf(base, user)
    d, shared = smf.paths.dest_dir("diffusion_models")
    check(os.path.normcase(d) == os.path.normcase(os.path.realpath(real_dm)) and shared,
          f"an SM-named junction: downloads go to the real diffusion_models folder ({d})")
    d, _ = smf.paths.dest_dir("loras")
    check(os.path.normcase(d) == os.path.normcase(real_lora_sm), f"a real SM folder still wins (Lora) ({d})")
    full, _ = smf.paths.dest_path("diffusion_models", "Krea 2/muse.safetensors")
    check(os.sep + "diffusion_models" + os.sep in full and "DiffusionModels" not in full, f"full paths use the real name ({full})")
    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    return 1 if check.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Stability Matrix shared-folder detection and model-location helpers.

Stability Matrix (Configuration mode, the default for ComfyUI) writes a
`stability_matrix:` section into ComfyUI's extra_model_paths.yaml that maps
ComfyUI folder keys to its shared Data/Models/* folders, e.g.

    stability_matrix:
      checkpoints: C:/StabilityMatrix/Data/Models/StableDiffusion
      loras: |
        C:/StabilityMatrix/Data/Models/Lora
        C:/StabilityMatrix/Data/Models/LyCORIS

In Symlink mode, ComfyUI's own models/* folders are links into Data/Models,
so writing there also lands in the shared library.
"""
from __future__ import annotations

import os
import re

try:
    import folder_paths
except ImportError:  # unit tests inject a stub
    folder_paths = None

try:
    import yaml
except ImportError:
    yaml = None

MODEL_EXTS = (".safetensors", ".ckpt", ".pt", ".pt2", ".pth", ".bin", ".gguf", ".sft", ".onnx")
# LoRA Manager refers to LoRAs by name without extension and only scans these
LM_EXTS = (".safetensors", ".ckpt", ".pt", ".bin")

# ComfyUI folder key -> Stability Matrix SharedFolderType (Data/Models/<name>)
COMFY_TO_SM = {
    "checkpoints": "StableDiffusion",
    "diffusers": "Diffusers",
    "loras": "Lora",
    "text_encoders": "TextEncoders",
    "clip_vision": "ClipVision",
    "embeddings": "Embeddings",
    "vae": "VAE",
    "vae_approx": "ApproxVAE",
    "controlnet": "ControlNet",
    "gligen": "GLIGEN",
    "upscale_models": "ESRGAN",
    "hypernetworks": "Hypernetwork",
    "ipadapter": "IpAdapter",
    "prompt_expansion": "PromptExpansion",
    "ultralytics": "Ultralytics",
    "ultralytics_bbox": "Ultralytics/bbox",
    "ultralytics_segm": "Ultralytics/segm",
    "sams": "Sams",
    "diffusion_models": "DiffusionModels",
    "style_models": "StyleModels",
    "audio_encoders": "AudioEncoders",
    "model_patches": "ModelPatches",
    "background_removal": "BackgroundRemoval",
}

ALIASES = {
    "unet": "diffusion_models",
    "unet_gguf": "diffusion_models",
    "clip": "text_encoders",
    "clip_gguf": "text_encoders",
    "t2i_adapter": "controlnet",
    "lycoris": "loras",
    "upscale": "upscale_models",
    "esrgan": "upscale_models",
    "diffusion_model": "diffusion_models",
    "checkpoint": "checkpoints",
    "lora": "loras",
    "text_encoder": "text_encoders",
    "embedding": "embeddings",
    "controlnets": "controlnet",
}
# Stability Matrix folder names used as keys (ComfyUI Desktop registers them like this)
for _comfy, _sm in COMFY_TO_SM.items():
    ALIASES.setdefault(_sm.split("/")[0].lower(), _comfy if "/" not in _sm else "ultralytics")
ALIASES.update({"lycoris": "loras", "realesrgan": "upscale_models", "swinir": "upscale_models",
                "t2iadapter": "controlnet", "ipadapters15": "ipadapter", "ipadaptersxl": "ipadapter",
                "vae_approx": "vae_approx"})

# folders that never hold downloadable model weights
_SKIP_FOLDERS = {"custom_nodes", "configs", "datasets", "classifiers", "custom_nodes"}


def canonical(folder: str | None) -> str | None:
    if not folder:
        return None
    f = folder.strip().strip("/\\").replace("\\", "/").split("/")[0].lower()
    return ALIASES.get(f, f)


def is_model_value(v) -> bool:
    return isinstance(v, str) and v.lower().endswith(MODEL_EXTS)


def norm_rel(p: str) -> str:
    return p.replace("\\", "/").strip("/")


def strip_lm_ext(name: str) -> str:
    for ext in LM_EXTS:
        if name.lower().endswith(ext):
            return name[:-len(ext)]
    return name


def safe_rel_path(p: str) -> str:
    """Validate a workflow-supplied relative path (may contain sub-folders)."""
    p = norm_rel(p)
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if not parts or any(x == ".." for x in parts) or re.match(r"^[a-zA-Z]:", parts[0]):
        raise ValueError(f"Unsafe model path: {p!r}")
    bad = re.compile(r'[<>:"|?*\x00-\x1f]')
    if any(bad.search(x) for x in parts):
        raise ValueError(f"Illegal characters in model path: {p!r}")
    return "/".join(parts)


# ---------------------------------------------------------------- SM detection
def _comfy_base() -> str:
    return getattr(folder_paths, "base_path", os.getcwd())


_SM_DIRNAMES = {v.split("/")[0].lower() for v in COMFY_TO_SM.values()}


def _looks_like_sm_path(p: str) -> bool:
    """.../Models/<SharedFolderType> — Stability Matrix's shared layout."""
    p = os.path.normpath(p)
    name, parent = os.path.basename(p).lower(), os.path.basename(os.path.dirname(p)).lower()
    if parent in ("bbox", "segm"):  # Ultralytics/bbox
        name, parent = os.path.basename(os.path.dirname(p)).lower(), \
            os.path.basename(os.path.dirname(os.path.dirname(p))).lower()
    return parent == "models" and name in _SM_DIRNAMES


def _config_files() -> list[str]:
    """Every extra-model-paths yaml ComfyUI loaded (SM package, portable, Desktop)."""
    files = []
    if folder_paths is not None:
        files.append(os.path.join(os.path.dirname(os.path.realpath(folder_paths.__file__)), "extra_model_paths.yaml"))
    files.append(os.path.join(_comfy_base(), "extra_model_paths.yaml"))
    try:
        from comfy.cli_args import args
        for group in args.extra_model_paths_config or []:
            files += list(group) if isinstance(group, (list, tuple)) else [group]
    except Exception:
        pass
    # ComfyUI Desktop keeps its config here (it passes it via --extra-model-paths-config,
    # but check directly too in case of older launchers)
    appdata = os.environ.get("APPDATA")
    if appdata:
        files.append(os.path.join(appdata, "ComfyUI", "extra_models_config.yaml"))
    out, seen = [], set()
    for f in files:
        k = os.path.normcase(os.path.abspath(f))
        if k not in seen and os.path.isfile(f):
            seen.add(k)
            out.append(f)
    return out


def _section_paths(sec: dict, yaml_dir: str) -> dict[str, list[str]]:
    base = sec.get("base_path")
    if base:
        base = os.path.expandvars(os.path.expanduser(str(base)))
        if not os.path.isabs(base):
            base = os.path.join(yaml_dir, base)
    out: dict[str, list[str]] = {}
    for key, val in sec.items():
        if key in ("base_path", "is_default") or val is None:
            continue
        vals = val if isinstance(val, list) else str(val).split("\n")
        for v in vals:
            v = str(v).strip()
            if not v:
                continue
            if base:
                v = os.path.join(base, v)
            elif not os.path.isabs(v):
                v = os.path.join(yaml_dir, v)
            out.setdefault(key, []).append(os.path.normpath(v))
    return out


def _yaml_paths() -> dict[str, list[str]]:
    """Shared-folder paths from a `stability_matrix:` section, or from any section
    (e.g. one you added to ComfyUI Desktop) that points into an SM Data/Models tree."""
    if yaml is None:
        return {}
    out: dict[str, list[str]] = {}
    for p in _config_files():
        try:
            with open(p, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            continue
        if not isinstance(cfg, dict):
            continue
        for name, sec in cfg.items():
            if not isinstance(sec, dict):
                continue
            paths = _section_paths(sec, os.path.dirname(os.path.abspath(p)))
            is_sm = name == "stability_matrix" or any(
                _looks_like_sm_path(x) for v in paths.values() for x in v)
            if not is_sm:
                continue
            for k, v in paths.items():
                for x in v:
                    if x not in out.setdefault(k, []):
                        out[k].append(x)
    return out


def _guess_models_root() -> str | None:
    """Data/Models when ComfyUI lives in Data/Packages/<name>."""
    base = os.path.realpath(_comfy_base())
    parent = os.path.dirname(base)
    if os.path.basename(parent).lower() == "packages":
        cand = os.path.join(os.path.dirname(parent), "Models")
        if os.path.isdir(cand):
            return cand
    # symlink mode: models/checkpoints -> .../Data/Models/StableDiffusion
    ck = os.path.join(base, "models", "checkpoints")
    real = os.path.realpath(ck)
    if real != os.path.normpath(ck) and os.path.basename(real) == "StableDiffusion":
        return os.path.dirname(real)
    return None


def sm_info() -> dict:
    yp = _yaml_paths()
    root = None
    for k in ["checkpoints"] + list(yp):
        cand = next((x for x in yp.get(k, []) if _looks_like_sm_path(x)), None)
        if cand:
            root = os.path.dirname(cand)
            if os.path.basename(root).lower() in ("bbox", "segm"):
                root = os.path.dirname(os.path.dirname(root))
            break
    root = root or _guess_models_root()
    mode = "config" if yp else ("symlink-or-detected" if root else "none")
    return {"mode": mode, "models_root": root, "yaml_paths": yp}


def dest_dir(folder: str) -> tuple[str, bool]:
    """Directory a model of this ComfyUI folder type should be downloaded to.

    Returns (directory, is_shared_with_stability_matrix).
    """
    c = canonical(folder) or folder
    info = sm_info()
    yp, root = info["yaml_paths"], info["models_root"]
    # Gather every configured path for this type (any key spelling), then prefer
    # Stability Matrix's own folder (e.g. Models/Lora over an empty Models/loras
    # that ComfyUI Desktop's "Shared Models" creates).
    cands = []
    for k, v in yp.items():
        if k == folder or canonical(k) == c:
            cands += [x for x in v if x not in cands]
    sm_name = COMFY_TO_SM.get(c, "").split("/")[-1].lower()
    for pick in (
        lambda x: os.path.basename(os.path.normpath(x)).lower() == sm_name,
        _looks_like_sm_path,
    ):
        hit = next((x for x in cands if pick(x)), None)
        if hit:
            return hit, True
    if cands and root is None:
        return cands[0], True
    # Not in the yaml: use ComfyUI's own path (symlinked into SM in symlink mode)
    fps = []
    if folder_paths is not None:
        try:
            fps = folder_paths.get_folder_paths(c)
        except Exception:
            fps = []
    if fps:
        d = next((p for p in fps if os.path.basename(p) == c), fps[0])
        shared = bool(root) and os.path.normcase(os.path.realpath(d)).startswith(
            os.path.normcase(os.path.realpath(root)) + os.sep)
        return d, shared
    if root and c in COMFY_TO_SM and info["mode"] != "config":
        return os.path.join(root, *COMFY_TO_SM[c].split("/")), True
    models_dir = getattr(folder_paths, "models_dir", os.path.join(_comfy_base(), "models"))
    return os.path.join(models_dir, c), False


def dest_path(folder: str, rel: str) -> tuple[str, bool]:
    d, shared = dest_dir(folder)
    rel = safe_rel_path(rel)
    root = os.path.normpath(d)
    full = os.path.normpath(os.path.join(root, *rel.split("/")))
    if not full.startswith(root + os.sep):
        raise ValueError("Destination escapes the model folder")
    return full, shared


# ---------------------------------------------------------------- inventory
def _folders() -> list[str]:
    if folder_paths is None:
        return []
    return [k for k in folder_paths.folder_names_and_paths.keys() if k not in _SKIP_FOLDERS]


def invalidate() -> None:
    if folder_paths is None:
        return
    for attr in ("filename_list_cache",):
        c = getattr(folder_paths, attr, None)
        if isinstance(c, dict):
            c.clear()


class Inventory:
    """Snapshot of every model file ComfyUI can currently see."""

    def __init__(self):
        self.lists: dict[str, set[str]] = {}
        self.norm: dict[str, dict[str, str]] = {}   # folder -> normalized rel -> exact name
        self.base: dict[str, dict[str, str]] = {}   # folder -> basename(lower) -> exact name
        for f in _folders():
            try:
                names = folder_paths.get_filename_list(f)
            except Exception:
                continue
            self.lists[f] = set(names)
            nm, bm = {}, {}
            for n in names:
                r = norm_rel(n).lower()
                nm.setdefault(r, n)
                bm.setdefault(r.rsplit("/", 1)[-1], n)
            self.norm[f], self.base[f] = nm, bm

    def _folders_for(self, folder: str | None) -> list[str]:
        if not folder:
            return list(self.lists)
        c = canonical(folder)
        # Keys named after SM folders ("Lora", "StableDiffusion" — ComfyUI Desktop adds
        # these) aren't used by the standard loader nodes, so they don't count.
        return [f for f in self.lists if canonical(f) == c and (f == c or f.lower() not in _SM_DIRNAMES)]

    def find(self, value: str, folder: str | None = None):
        """-> (state, folder, exact_name, hint)

        present   : ComfyUI's list contains exactly this string (what validation checks)
        elsewhere : same file under a different path/case/slash style -> Repoint fixes it
        missing   : not in the right folder (hint names another folder that has it)
        """
        fs = self._folders_for(folder)
        for f in fs:
            if value in self.lists[f]:
                return "present", f, value, None
        r = norm_rel(value).lower()
        for f in fs:
            n = self.norm[f].get(r)
            if n:
                return "elsewhere", f, n, None
        b = r.rsplit("/", 1)[-1]
        for f in fs:
            n = self.base[f].get(b)
            if n:
                return "elsewhere", f, n, None
        if folder:
            for f in self.lists:
                if f not in fs and (self.norm[f].get(r) or self.base[f].get(b)):
                    return "missing", None, None, f"A file with this name exists in '{f}', not '{canonical(folder)}'"
        return "missing", None, None, None

    def find_lm(self, name: str):
        """LoRA Manager lookup: `name` is 'stem' or 'folder/stem' (no extension).

        Mirrors LoRA Manager's resolver: exact stem or folder/stem match, else the
        first file with the same stem anywhere under the LoRA roots. Moved files
        therefore still resolve, so there is no 'elsewhere' state here.
        -> (state, folder, exact_name)
        """
        r = strip_lm_ext(norm_rel(name)).lower()
        b = r.rsplit("/", 1)[-1]
        fallback = None
        for f in self._folders_for("loras"):
            for n in self.lists[f]:
                if not n.lower().endswith(LM_EXTS):
                    continue
                s = strip_lm_ext(norm_rel(n)).lower()
                if s == r or s.rsplit("/", 1)[-1] == r:
                    return "present", f, n
                if fallback is None and s.rsplit("/", 1)[-1] == b:
                    fallback = (f, n)
        if fallback:
            return "present", fallback[0], fallback[1]
        return "missing", None, None

    def full_path(self, folder: str, name: str) -> str | None:
        try:
            return folder_paths.get_full_path(folder, name)
        except Exception:
            return None

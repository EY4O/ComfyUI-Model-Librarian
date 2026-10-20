"""What a diffusion model needs besides itself (text encoders, VAE, CLIP vision), read from ComfyUI's
own workflow templates: each template lists the models it loads, with their folder and official
download link. A model is matched to the templates of its base family (Krea 2, Flux, Wan, ...), and
to the template whose model file is most like it. Nothing here is a hand-made list, so it follows
ComfyUI's releases."""
from __future__ import annotations

import functools
import glob
import importlib.util
import json
import os
import re

from . import basemodel, paths

COMPANION_DIRS = ("text_encoders", "vae", "clip_vision")
TEMPLATE_PACKAGES = ("comfyui_workflow_templates_json", "comfyui_workflow_templates")


def _template_files() -> list[str]:
    out = []
    for pkg in TEMPLATE_PACKAGES:
        try:
            spec = importlib.util.find_spec(pkg)
        except (ImportError, ValueError):
            spec = None
        for loc in (spec.submodule_search_locations or []) if spec else []:
            out += glob.glob(os.path.join(loc, "templates", "*.json"))
    seen, files = set(), []
    for f in sorted(out):
        n = os.path.basename(f)
        # api_ templates run on paid API nodes (no local models); audio models aren't what CivitAI pages offer
        if n not in seen and not n.startswith(("api_", "index", "audio_")):
            seen.add(n)
            files.append(f)
    return files


def _models_in(template: dict) -> list[dict]:
    found = []

    def walk(nodes):
        for n in nodes or []:
            for m in ((n.get("properties") or {}).get("models") or []):
                if isinstance(m, dict) and m.get("name") and m.get("directory"):
                    found.append({"folder": m["directory"], "name": os.path.basename(str(m["name"]).replace("\\", "/")), "url": m.get("url")})
    walk(template.get("nodes"))
    for sg in ((template.get("definitions") or {}).get("subgraphs") or []):
        walk(sg.get("nodes"))
    uniq = {}
    for m in found:
        uniq.setdefault((m["folder"], m["name"].lower()), m)
    return list(uniq.values())


@functools.lru_cache(maxsize=4)
def _index(files: tuple[str, ...]) -> list[dict]:
    out = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                models = _models_in(json.load(fh))
        except (OSError, ValueError):
            continue
        # a standalone diffusion model is what needs companions (an all-in-one checkpoint has its own)
        mains = [m for m in models if m["folder"] in ("diffusion_models", "unet")]
        comps = [m for m in models if m["folder"] in COMPANION_DIRS and (m.get("url") or "").startswith("https://")]
        if not mains or not comps:
            continue
        fam = basemodel.from_text(mains[0]["name"])
        if fam:
            out.append({"template": os.path.splitext(os.path.basename(f))[0], "family": fam,
                        "mains": [m["name"] for m in mains], "companions": comps})
    return out


def index() -> list[dict]:
    return _index(tuple(_template_files()))


def stem(name: str) -> str:
    """The encoder or VAE without its precision: t5xxl_fp16 and t5xxl_fp8_e4m3fn are the same model."""
    s = os.path.splitext(os.path.basename(str(name)))[0].lower()
    return re.sub(r"[_.-](?:fp|bf|int|nvfp|mxfp|q)\d.*$", "", s)


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z]+|\d+", os.path.splitext(str(s).lower())[0]))


def for_model(base_model: str | None, file_name: str | None, inv: paths.Inventory | None = None) -> dict:
    """-> {family, source (the template), companions: [{folder, name, url, have, alt}]}: `have` is the
    installed file (any subfolder), `alt` one of the same model in another precision."""
    fam = basemodel.from_text(base_model or "") or basemodel.from_text(file_name or "")
    cands = [t for t in index() if t["family"] == fam] if fam else []
    if not cands:
        return {"family": fam, "source": None, "companions": []}
    want = _tokens(file_name or "") | _tokens(base_model or "")
    sets = {}
    for t in cands:
        key = tuple(sorted(c["name"].lower() for c in t["companions"]))
        sets[key] = sets.get(key, 0) + 1

    def score(t):
        overlap = max(len(want & _tokens(m)) for m in t["mains"])
        return (overlap, sets[tuple(sorted(c["name"].lower() for c in t["companions"]))], -len(t["template"]))
    best = max(cands, key=score)
    inv = inv or paths.Inventory()
    out = []
    for c in best["companions"]:
        names = inv.base.get(c["folder"], {})
        have = names.get(c["name"].lower())
        alt = None
        if not have:
            st = stem(c["name"])
            alt = next((n for b, n in sorted(names.items()) if stem(b) == st), None)
        out.append({**c, "have": have, "alt": alt})
    return {"family": fam, "source": best["template"], "companions": out}

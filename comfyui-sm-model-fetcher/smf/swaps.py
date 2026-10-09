"""VRAM advisor: smaller versions of models that don't fit the configured GPU.

Two kinds of alternatives:
  fp8   about half of fp16, loads in the *same* loader node, so the workflow is
        simply repointed after the download
  GGUF  quantized (Q8 … Q2); UNets swap to 'Unet Loader (GGUF)' automatically,
        text encoders need 'CLIPLoader (GGUF)' (download only, with a note)

Text encoders are flagged too: T5-XXL / Qwen-VL encoders in fp16 compete with
the diffusion model for VRAM and RAM.
"""
from __future__ import annotations

import re

from . import config, registry, sources

QUANT_RE = re.compile(r"(?i)(?:^|[-_.])((?:I?Q\d(?:_K)?(?:_[A-Z0-9]+)?)|BF16|F16|F32)(?=\.gguf$)")
FP8_RE = re.compile(r"(?i)fp8|e4m3|e5m2|float8")

# Popular models whose smaller versions live in repos with different naming.
KNOWN_GGUF_REPOS = {
    "flux1-dev": ["city96/FLUX.1-dev-gguf"],
    "flux1-schnell": ["city96/FLUX.1-schnell-gguf"],
    "t5xxl": ["city96/t5-v1_1-xxl-encoder-gguf"],
    "t5-v1_1-xxl": ["city96/t5-v1_1-xxl-encoder-gguf"],
}
KNOWN_FP8_REPOS = {
    "t5xxl": ["comfyanonymous/flux_text_encoders"],
}

UNET_TYPES = {"UNETLoader", "UnetLoaderGGUF", "UnetLoaderGGUFAdvanced", "Unet Loader (LoraManager)"}
TE_TYPES = {"CLIPLoader", "DualCLIPLoader", "TripleCLIPLoader", "QuadrupleCLIPLoader"}
TE_SHARE = 0.5  # a text encoder over half the VRAM budget gets a suggestion

GB = 1024 ** 3


def budget_bytes(cfg: dict | None = None) -> int:
    cfg = cfg or config.load()
    return int(max(1.0, float(cfg["vram_gb"]) - float(cfg["headroom_gb"])) * GB)


def quant_label(name: str) -> str:
    if FP8_RE.search(name):
        return "FP8"
    m = QUANT_RE.search(name)
    return m.group(1).upper() if m else "?"


def is_small_format(name: str) -> bool:
    n = name.lower()
    return n.endswith(".gguf") or bool(FP8_RE.search(n)) or "nvfp4" in n or "int4" in n


def too_big(name: str, size: int | None, node_types, budget: int) -> str | None:
    """-> "model" / "text_encoder" when a smaller version is worth suggesting."""
    if not size or is_small_format(name):
        return None
    types = set(node_types or [])
    big_model = UNET_TYPES | {"CheckpointLoaderSimple", "CheckpointLoader", "Checkpoint Loader (LoraManager)"}
    if types & big_model and size > budget:
        return "model"
    if types & TE_TYPES and size > budget * TE_SHARE:
        return "text_encoder"
    return None


def _known(table: dict, filename: str) -> list[str]:
    st = sources.stem(filename).lower()
    return [r for k, v in table.items() if st.startswith(k) for r in v]


def _source_repo(filename: str) -> str | None:
    """The HuggingFace repo the original came from (registry), if any."""
    e = registry.lookup(filename)
    m = re.match(r"https://(?:huggingface\.co|hf\.co)/([^/]+/[^/]+)/resolve/", (e or {}).get("url") or "")
    return m.group(1) if m else None


async def _search(filename: str, suffix: str, must: str, limit: int = 4) -> list[str]:
    repos: list[str] = []
    for q in sources.hf_query_variants(filename)[:3]:
        for r in await sources.hf_search(f"{q} {suffix}", limit=6) + await sources.hf_search(f"{q}-{suffix}", limit=6):
            rid = r.get("id") or r.get("modelId") or ""
            if rid and (not must or must in rid.lower()) and rid not in repos:
                repos.append(rid)
        if len(repos) >= limit:
            break
    return repos[:limit]


def _option(repo: str, f: dict, budget: int, kind: str, action: str) -> dict:
    sz = f.get("size") or (f.get("lfs") or {}).get("size") or 0
    return {
        "repo": repo, "path": f["path"], "filename": sources.basename(f["path"]),
        "url": sources.hf_file_url(repo, f["path"]), "size": sz,
        "sha256": (f.get("lfs") or {}).get("oid"), "quant": quant_label(f["path"]),
        "fits": 0 < sz <= budget, "kind": kind, "action": action,
        "page_url": f"https://huggingface.co/{repo}",
    }


async def _fp8_options(filename: str, size: int, budget: int) -> list[dict]:
    toks = [t.lower() for t in sources.core_tokens(filename)[:2]]
    repos = []
    for r in [_source_repo(filename)] + _known(KNOWN_FP8_REPOS, filename) + await _search(filename, "fp8", "", 3):
        if r and r not in repos:
            repos.append(r)
    out, seen = [], set()
    for repo in repos[:5]:
        for f in await sources.hf_tree(repo):
            name = sources.basename(f["path"]).lower()
            if not name.endswith((".safetensors", ".sft")) or not FP8_RE.search(name):
                continue
            if toks and not all(t in name for t in toks):
                continue  # another model in the same repo
            o = _option(repo, f, budget, "fp8", "repoint")
            if 0 < o["size"] < size and o["filename"] not in seen:
                seen.add(o["filename"])
                out.append(o)
    return out


async def _gguf_options(filename: str, budget: int, action: str) -> list[dict]:
    repos = []
    for r in _known(KNOWN_GGUF_REPOS, filename) + await _search(filename, "gguf", "gguf"):
        if r not in repos:
            repos.append(r)
    for repo in repos[:4]:
        opts = [_option(repo, f, budget, "gguf", action) for f in await sources.hf_tree(repo)
                if f["path"].lower().endswith(".gguf")]
        if opts:
            return opts  # first repo with GGUF files wins
    return []


async def suggest(filename: str, size: int | None, node_type: str | None = None, node_types=None) -> dict:
    cfg = config.load()
    budget = budget_bytes(cfg)
    types = set(node_types or ([node_type] if node_type else []))
    kind = too_big(filename, size, types, budget)
    res = {"filename": filename, "size": size, "budget": budget, "too_big": bool(kind), "kind": kind,
           "swappable": "UNETLoader" in types, "options": [], "note": None}
    if types & {"CheckpointLoaderSimple", "CheckpointLoader", "Checkpoint Loader (LoraManager)"}:
        res["note"] = ("All-in-one checkpoint: to use GGUF, load the UNet with 'Unet Loader (GGUF)' and the "
                       "text encoder / VAE with their own loaders. fp8 checkpoints load in the same node.")
    elif kind == "text_encoder":
        res["note"] = ("fp8 text encoders load in the same node (the workflow is repointed after download). "
                       "GGUF ones need 'CLIPLoader (GGUF)' from ComfyUI-GGUF — swap the node yourself.")
    if not kind:
        return res
    res["options"] = await _fp8_options(filename, size or 0, budget)
    res["options"] += await _gguf_options(filename, budget, "swap" if kind == "model" and "UNETLoader" in types else "download")
    fitting = [o for o in res["options"] if o["fits"]]
    best = max(fitting, key=lambda o: o["size"], default=None)  # biggest that fits = best quality
    for o in res["options"]:
        o["recommended"] = o is best
    res["options"].sort(key=lambda o: -o["size"])
    return res

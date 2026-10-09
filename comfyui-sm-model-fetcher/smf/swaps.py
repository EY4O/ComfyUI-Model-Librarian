"""VRAM advisor: find GGUF quantizations that fit the configured GPU."""
from __future__ import annotations

import re

from . import config, sources

QUANT_RE = re.compile(r"(?i)(?:^|[-_.])((?:I?Q\d(?:_K)?(?:_[A-Z0-9]+)?)|BF16|F16|F32)(?=\.gguf$)")

# Popular models whose GGUF repos don't share the original file's naming.
KNOWN_GGUF_REPOS = {
    "flux1-dev": ["city96/FLUX.1-dev-gguf"],
    "flux1-schnell": ["city96/FLUX.1-schnell-gguf"],
}

GB = 1024 ** 3


def budget_bytes(cfg: dict | None = None) -> int:
    cfg = cfg or config.load()
    return int(max(1.0, float(cfg["vram_gb"]) - float(cfg["headroom_gb"])) * GB)


def quant_label(name: str) -> str:
    m = QUANT_RE.search(name)
    return m.group(1).upper() if m else "?"


async def _gguf_repos(filename: str) -> list[str]:
    st = sources.stem(filename).lower()
    repos: list[str] = []
    for k, v in KNOWN_GGUF_REPOS.items():
        if st.startswith(k):
            repos += v
    for q in sources.hf_query_variants(filename)[:3]:
        for r in await sources.hf_search(f"{q} gguf", limit=6) + await sources.hf_search(f"{q}-gguf", limit=6):
            rid = r.get("id") or r.get("modelId") or ""
            if "gguf" in rid.lower() and rid not in repos:
                repos.append(rid)
        if len(repos) >= 4:
            break
    return repos[:4]


async def suggest(filename: str, size: int | None, node_type: str | None = None) -> dict:
    cfg = config.load()
    budget = budget_bytes(cfg)
    res = {
        "filename": filename, "size": size, "budget": budget,
        "too_big": bool(size and size > budget),
        "swappable": node_type in ("UNETLoader",),
        "options": [],
        "note": None,
    }
    if node_type == "CheckpointLoaderSimple":
        res["note"] = ("All-in-one checkpoint: to use GGUF, load the UNet with 'Unet Loader (GGUF)' and the "
                       "text encoder / VAE with their own loaders.")
    if not res["too_big"]:
        return res
    for repo in await _gguf_repos(filename):
        files = await sources.hf_tree(repo)
        gg = [f for f in files if f["path"].lower().endswith(".gguf")]
        for f in gg:
            sz = f.get("size") or (f.get("lfs") or {}).get("size") or 0
            res["options"].append({
                "repo": repo, "path": f["path"], "filename": sources.basename(f["path"]),
                "url": sources.hf_file_url(repo, f["path"]), "size": sz,
                "sha256": (f.get("lfs") or {}).get("oid"), "quant": quant_label(f["path"]),
                "fits": 0 < sz <= budget,
                "page_url": f"https://huggingface.co/{repo}",
            })
        if res["options"]:
            break  # first repo with GGUF files wins
    fitting = [o for o in res["options"] if o["fits"]]
    best = max(fitting, key=lambda o: o["size"], default=None)  # biggest that fits = best quality
    for o in res["options"]:
        o["recommended"] = o is best
    res["options"].sort(key=lambda o: -o["size"])
    return res

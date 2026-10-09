"""Which models are actually used? (for the Library's "Unused" filter)

A model counts as used when this install's saved workflows reference it (by
file name, by LoRA Manager name or <lora:name:...> text) or a LoRA Manager
recipe uses it (by SHA256 or name). Workflows of other ComfyUI installs aren't
visible from here, so "unused" means unused *by this install*.
"""
from __future__ import annotations

import glob
import json
import os
import re

from . import hashing, library, paths, workflows

_LORA_SYNTAX = re.compile(r"<lora:([^:>]+):[^>]*>", re.I)


def _stem(name: str) -> str:
    b = paths.norm_rel(name).rsplit("/", 1)[-1].lower()
    return os.path.splitext(b)[0] if paths.is_model_value(b) else b


def _walk(obj, fn, depth=0):
    if depth > 5:
        return
    if isinstance(obj, dict):
        fn(obj)
        for v in obj.values():
            _walk(v, fn, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, fn, depth + 1)
    elif isinstance(obj, str):
        fn(obj)


def referenced() -> dict:
    """-> {"names": stems referenced, "hashes": sha256s, "workflows": n, "recipes": n}"""
    names, hashes = set(), set()
    n_wf = n_rec = 0

    def take(x):
        if isinstance(x, str):
            if paths.is_model_value(x):
                names.add(_stem(x))
            elif "<lora:" in x.lower():
                names.update(_stem(m) for m in _LORA_SYNTAX.findall(x))
        elif isinstance(x, dict) and isinstance(x.get("name"), str) and ("strength" in x or "active" in x):
            names.add(_stem(x["name"]))  # LoRA Manager list entry {name, strength, active}

    for _, p in workflows.workflow_files():
        try:
            with open(p, "r", encoding="utf-8") as f:
                wf = json.load(f)
        except Exception:
            continue
        n_wf += 1
        graphs = [wf] + list(((wf.get("definitions") or {}).get("subgraphs") or []) if isinstance(wf, dict) else [])
        for g in graphs:
            for node in (g.get("nodes") or []) if isinstance(g, dict) else []:
                if isinstance(node, dict):
                    _walk(node.get("widgets_values") or [], take)

    for root in library.roots("loras"):
        for p in glob.glob(os.path.join(root, "recipes", "**", "*.recipe.json"), recursive=True):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    rec = json.load(f)
            except Exception:
                continue
            n_rec += 1
            for lora in rec.get("loras") or []:
                if isinstance(lora, dict):
                    if lora.get("hash"):
                        hashes.add(str(lora["hash"]).lower())
                    if lora.get("file_name"):
                        names.add(_stem(lora["file_name"]))
            ck = rec.get("checkpoint")
            if isinstance(ck, str):
                names.add(_stem(ck))
            elif isinstance(ck, dict):
                for k in ("file_name", "name"):
                    if ck.get(k):
                        names.add(_stem(ck[k]))
                if ck.get("hash"):
                    hashes.add(str(ck["hash"]).lower())
    return {"names": names, "hashes": hashes, "workflows": n_wf, "recipes": n_rec}


def unused(section: str) -> dict:
    ref = referenced()
    out = []
    for e in library.build(section):
        if _stem(e["name"]) in ref["names"]:
            continue
        sha = (e.get("sha256") or hashing.cached(e["path"]) or "").lower()
        if sha and (sha in ref["hashes"] or any(len(h) < 64 and sha.startswith(h) for h in ref["hashes"])):
            continue
        out.append(e["id"])
    return {"unused_ids": out, "workflows": ref["workflows"], "recipes": ref["recipes"]}

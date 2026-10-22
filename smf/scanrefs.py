"""Model references → scan results, shared by the open-workflow scan (/scan) and
the saved-workflow health check (workflows.health).

A reference is {key, node_type, widget, value, embedded?, lm?}; references to
the same file in the same folder are grouped into one item with every key.
"""
from __future__ import annotations

import os
import re
from urllib.parse import unquote

from . import infer, paths, smmeta, swaps


def lm_group(name: str, inv: paths.Inventory) -> dict:
    """Scan result for a LoRA Manager reference (a LoRA name without extension)."""
    raw = paths.strip_lm_ext(name.replace("\\", "/"))
    name = paths.strip_lm_ext(paths.norm_rel(name))
    g = {"value": name, "folder": "loras", "how": "lora-manager", "lm": True, "refs": [], "node_types": [],
         "embedded": None, "size": None, "dest": None, "shared": None, "too_big": False, "hint": None,
         "found_as": None, "found_folder": None,
         "search_name": name.rsplit("/", 1)[-1] + ".safetensors"}
    if raw.startswith("/") or re.match(r"^[a-zA-Z]:", raw):
        # LoRA Manager accepts raw absolute paths that exist on disk
        if any(os.path.isfile(raw + e) for e in ("",) + paths.LM_EXTS):
            g["status"] = "present"
            return g
        name = name.rsplit("/", 1)[-1]
    state, ffolder, fname = inv.find_lm(name)
    g.update(status=state, found_as=fname, found_folder=ffolder)
    if state == "present":
        fp = inv.full_path(ffolder, fname)
        if fp and os.path.exists(fp):
            g["size"] = os.path.getsize(fp)
        return g
    try:
        g["dest"], g["shared"] = paths.dest_path("loras", name + ".safetensors")
    except ValueError as ex:
        g["status"], g["error"] = "invalid", str(ex)
    return g


def _file_group(val: str, folder: str | None, how: str, emb: dict | None, inv: paths.Inventory) -> dict:
    state, ffolder, fname, hint = inv.find(val, folder)
    if state == "missing" and "%" in val:
        # URL-encoded names from browser downloads ("My%20Lora.safetensors")
        s2, f2, n2, _ = inv.find(unquote(val), folder)
        if s2 != "missing":
            state, ffolder, fname = "elsewhere", f2, n2
    g = {"value": val, "folder": folder, "how": how, "status": state,
         "found_as": fname, "found_folder": ffolder, "refs": [], "node_types": [],
         "embedded": emb, "size": None, "dest": None, "shared": None, "too_big": False,
         "hint": hint}
    if state != "missing":
        fp = inv.full_path(ffolder, fname)
        if fp and os.path.exists(fp):
            g["size"] = os.path.getsize(fp)
    try:
        paths.safe_rel_path(val)
    except ValueError as ex:
        g["status"], g["error"] = "invalid", str(ex)
    if folder and g["status"] != "invalid":
        try:
            d, shared = paths.dest_path(folder, val)
            g["dest"], g["shared"] = d, shared
        except ValueError as ex:
            g["status"], g["error"] = "invalid", str(ex)
    return g


_ORDER = {"missing": 0, "invalid": 1, "elsewhere": 2, "present": 3}


def add_trigger_words(items: list[dict], inv: paths.Inventory) -> None:
    """The trigger words of the LoRAs you have (from CivitAI, Stability Matrix or LoRA Manager metadata)."""
    for g in items:
        if g.get("folder") != "loras" or g.get("status") not in ("present", "elsewhere"):
            continue
        name = g.get("found_as") or g["value"]
        if g.get("lm") and not os.path.splitext(name)[1]:
            name += ".safetensors"
        fp = inv.full_path(g.get("found_folder") or "loras", name)
        words = smmeta.merged_info(fp).get("trained_words") if fp and os.path.isfile(fp) else None
        if words:
            g["trained_words"] = [str(w) for w in words if str(w).strip()][:30]


def group(refs: list[dict], inv: paths.Inventory, budget: int | None = None) -> list[dict]:
    budget = swaps.budget_bytes() if budget is None else budget
    infer.clear_cache()  # node option lists include model files, which change
    groups: dict[tuple, dict] = {}
    for ref in refs:
        val = ref.get("value")
        if ref.get("lm"):
            if not isinstance(val, str) or not val.strip():
                continue
            key = (paths.strip_lm_ext(paths.norm_rel(val)).lower(), "loras", "lm")
            g = groups.get(key)
            if g is None:
                g = groups[key] = lm_group(val, inv)
        else:
            if not paths.is_model_value(val):
                continue
            emb = ref.get("embedded") or None
            folder, how = infer.infer_folder(ref.get("node_type", ""), ref.get("widget", ""),
                                             (emb or {}).get("directory"), inv)
            key = (paths.norm_rel(val).lower(), folder)
            g = groups.get(key)
            if g is None:
                g = groups[key] = _file_group(val, folder, how, emb, inv)
                if g["status"] == "missing" and val in (infer._combo_options(ref.get("node_type", ""), ref.get("widget", "")) or ()):
                    # the node offers this value itself (e.g. frame-interpolation models it
                    # downloads on first use): ComfyUI accepts it, so nothing is missing
                    g.update(status="present", how="node-provided", dest=None, shared=None)
            if emb and not g["embedded"]:
                g["embedded"] = emb
        g["refs"].append(ref.get("key"))
        if ref.get("node_type") not in g["node_types"]:
            g["node_types"].append(ref.get("node_type"))
    items = list(groups.values())
    for g in items:
        g["big_kind"] = swaps.too_big(g.get("found_as") or g["value"], g["size"], g["node_types"], budget)
        g["too_big"] = bool(g["big_kind"])
    items.sort(key=lambda g: (_ORDER.get(g["status"], 9), g["value"].lower()))
    return items

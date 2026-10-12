"""Keep saved workflows working after models move.

Organize (and undo, and other ComfyUI installs sharing the folders) change
model paths, which breaks every saved workflow that names them. Instead of
replaying move logs, this is state-based: each model reference in a saved
workflow that no longer exists is repointed when exactly one file with that
name exists now. Ambiguous names are reported, never guessed. Changed files
are backed up first.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import time

from . import config, infer, paths, scanrefs

try:
    import folder_paths
except ImportError:
    folder_paths = None

_MAX_DEPTH = 4


def workflow_files() -> list[tuple[str, str]]:
    """-> [(user_dir, path)] for every saved workflow and subgraph blueprint."""
    if folder_paths is None:
        return []
    root = folder_paths.get_user_directory()
    out = []
    for kind in ("workflows", "subgraphs"):
        for p in glob.glob(os.path.join(root, "*", kind, "**", "*.json"), recursive=True):
            out.append((root, p))
    return out


def _walk_values(obj, fn, depth=0):
    """Call fn(container, key, value) for every string inside widgets/models."""
    if depth > _MAX_DEPTH:
        return
    items = obj.items() if isinstance(obj, dict) else enumerate(obj) if isinstance(obj, list) else ()
    for k, v in items:
        if isinstance(v, str):
            fn(obj, k, v)
        elif isinstance(v, (dict, list)):
            _walk_values(v, fn, depth + 1)


def _model_slots(wf: dict):
    """Yield (container, key, value) for model-file strings a workflow references."""
    found = []

    def take(c, k, v):
        if paths.is_model_value(v):
            found.append((c, k, v))

    def nodes_of(graph):
        for n in graph.get("nodes") or []:
            if isinstance(n, dict):
                _walk_values(n.get("widgets_values") or [], take)
                for m in (n.get("properties") or {}).get("models") or []:
                    if isinstance(m, dict) and isinstance(m.get("name"), str):
                        take(m, "name", m["name"])

    if isinstance(wf, dict):
        nodes_of(wf)
        for sg in (wf.get("definitions") or {}).get("subgraphs") or []:
            if isinstance(sg, dict):
                nodes_of(sg)
        for m in wf.get("models") or []:
            if isinstance(m, dict) and isinstance(m.get("name"), str):
                take(m, "name", m["name"])
    return found


class _Index:
    """Every model name ComfyUI can see, for repointing."""

    def __init__(self):
        inv = paths.Inventory()
        self.present = set()
        self.by_norm: dict[str, set[str]] = {}
        self.by_base: dict[str, set[str]] = {}
        for names in inv.lists.values():
            for n in names:
                self.present.add(n)
                r = paths.norm_rel(n).lower()
                self.by_norm.setdefault(r, set()).add(n)
                self.by_base.setdefault(r.rsplit("/", 1)[-1], set()).add(n)

    def resolve(self, v: str) -> tuple[str, str | None]:
        """-> (state, new name): ok | fix | missing | ambiguous"""
        if v in self.present:
            return "ok", None
        r = paths.norm_rel(v).lower()
        for cands in (self.by_norm.get(r), self.by_base.get(r.rsplit("/", 1)[-1])):
            if cands:
                if len(cands) == 1:
                    return "fix", next(iter(cands))
                return "ambiguous", None
        return "missing", None


def scan(apply: bool = False) -> dict:
    idx = _Index()
    results = []
    backup_dir = os.path.join(config.local_dir(), "workflow_backups", time.strftime("%Y%m%d-%H%M%S"))
    for root, p in workflow_files():
        try:
            with open(p, "r", encoding="utf-8") as f:
                text = f.read()
            wf = json.loads(text)
        except Exception:
            continue
        fixes, missing, ambiguous = {}, set(), set()
        slots = _model_slots(wf)
        for c, k, v in slots:
            state, new = idx.resolve(v)
            if state == "fix":
                fixes[v] = new
            elif state == "missing":
                missing.add(v)
            elif state == "ambiguous":
                ambiguous.add(v)
        if not (fixes or missing or ambiguous):
            continue
        rel = os.path.relpath(p, root)
        item = {"file": rel.replace("\\", "/"), "fixes": [{"old": a, "new": b} for a, b in sorted(fixes.items())],
                "missing": sorted(missing), "ambiguous": sorted(ambiguous), "written": False}
        if apply and fixes:
            for c, k, v in slots:
                if v in fixes:
                    c[k] = fixes[v]
            dst = os.path.join(backup_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(p, dst)
            tmp = p + ".smf-tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(wf, f, ensure_ascii=False, indent=2 if "\n" in text.strip() else None)
            os.replace(tmp, p)
            item["written"] = True
        results.append(item)
    return {
        "workflows": results,
        "fixed_files": sum(1 for r in results if r["written"]),
        "fixable_files": sum(1 for r in results if r["fixes"]),
        "fixes": sum(len(r["fixes"]) for r in results),
        "backup_dir": backup_dir if any(r["written"] for r in results) else None,
    }


# ---------------------------------------------------------------- health check
# LoRA Manager nodes name LoRAs without an extension: a `loras` list widget or
# <lora:name:strength> text. Pool/randomizer/cycler pick LoRAs at run time.
_LM_NODE = re.compile(r"\(LoraManager\)$")
_LM_SKIP = {"Lora Pool (LoraManager)", "Lora Randomizer (LoraManager)", "Lora Cycler (LoraManager)"}
_LM_SYNTAX = re.compile(r"<lora:([^:>]+):[^:>]+(?::[^:>]+)?>", re.I)


def _embedded(m: dict | None) -> dict | None:
    if not isinstance(m, dict) or not m.get("url"):
        return None
    return {k: m.get(k) for k in ("url", "directory", "hash", "hash_type")}


def _lm_names(values) -> list[str] | None:
    """LoRA names in a LoRA Manager node's widgets_values (the list wins over text)."""
    for v in values:
        lst = v.get("__value__") if isinstance(v, dict) else v
        if isinstance(lst, list) and lst and all(isinstance(e, dict) for e in lst) and any("name" in e for e in lst):
            return [str(e["name"]) for e in lst if e.get("active", True) and e.get("name")]
    names = [m.group(1).strip() for v in values if isinstance(v, str) for m in _LM_SYNTAX.finditer(v)]
    return names or None


def refs_of(wf: dict, file: str) -> list[dict]:
    """Model references in a saved (UI-format) workflow, in /scan's ref shape.
    Keys start with the workflow's file name."""
    out: list[dict] = []
    top = {}
    for m in (wf.get("models") if isinstance(wf, dict) else None) or []:
        if isinstance(m, dict) and isinstance(m.get("name"), str):
            top[m["name"].replace("\\", "/").rsplit("/", 1)[-1].lower()] = m

    def nodes_of(graph: dict, prefix: str):
        for n in graph.get("nodes") or []:
            if not isinstance(n, dict) or "Note" in str(n.get("type", "")):
                continue
            ntype = str(n.get("type") or "")
            key = f"{file}|{prefix}{n.get('id')}"
            wv = n.get("widgets_values")
            values = wv if isinstance(wv, list) else list(wv.values()) if isinstance(wv, dict) else []
            if _LM_NODE.search(ntype):
                if ntype in _LM_SKIP:
                    continue
                names = _lm_names(values)
                if names is not None:
                    for i, name in enumerate(names):
                        base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
                        out.append({"key": f"{key}|lm{i}", "node_type": ntype, "widget": "loras", "value": name, "lm": True,
                                    "embedded": _embedded(top.get(base + ".safetensors"))})
                    continue
            emb = {}
            for m in (n.get("properties") or {}).get("models") or []:
                if isinstance(m, dict) and isinstance(m.get("name"), str):
                    emb[m["name"].lower()] = m
            items = wv.items() if isinstance(wv, dict) else enumerate(values)
            for i, v in items:
                widget = i if isinstance(i, str) else infer.widget_at(ntype, i)
                found = []
                if isinstance(v, str):
                    found.append(v)
                else:
                    _walk_values(v if isinstance(v, (dict, list)) else [], lambda c, k, x: found.append(x))
                for val in found:
                    if not paths.is_model_value(val):
                        continue
                    base = val.replace("\\", "/").rsplit("/", 1)[-1].lower()
                    e = emb.get(val.lower()) or emb.get(base) or top.get(base)
                    out.append({"key": f"{key}|{i}", "node_type": ntype, "widget": widget, "value": val,
                                "embedded": _embedded(e)})

    if isinstance(wf, dict):
        nodes_of(wf, "")
        for sg in (wf.get("definitions") or {}).get("subgraphs") or []:
            if isinstance(sg, dict):
                nodes_of(sg, f"sg:{sg.get('id')}:")
    return out


def health() -> dict:
    """Every saved workflow and subgraph blueprint, checked for missing models.
    -> {workflows: [{file, user, path, models, missing, moved, error?}], items: scan items
    (each with `workflows`: the files that use it)}"""
    inv = paths.Inventory()
    refs, files = [], {}
    for root, p in workflow_files():
        rel = os.path.relpath(p, root).replace("\\", "/")
        user, _, path = rel.partition("/")
        entry = files[rel] = {"file": rel, "user": user, "path": path, "models": 0, "missing": 0, "moved": 0}
        try:
            with open(p, "r", encoding="utf-8") as f:
                wf = json.load(f)
        except Exception:
            entry["error"] = "couldn't read this file"
            continue
        refs.extend(refs_of(wf, rel))
    items = scanrefs.group(refs, inv)
    for it in items:
        it["workflows"] = sorted({k.split("|", 1)[0] for k in it["refs"]})
        for w in it["workflows"]:
            e = files.get(w)
            if e:
                e["models"] += 1
                e["missing"] += it["status"] in ("missing", "invalid")
                e["moved"] += it["status"] == "elsewhere"
    wfs = sorted(files.values(), key=lambda e: (-e["missing"], -e["moved"], e["file"].lower()))
    return {"workflows": wfs, "items": items, "sm_mode": paths.sm_info()["mode"]}

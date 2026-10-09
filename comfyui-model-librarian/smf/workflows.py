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
import shutil
import time

from . import config, paths

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

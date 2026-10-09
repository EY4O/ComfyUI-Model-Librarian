"""Sort models into base-model folders, find duplicates, undo."""
from __future__ import annotations

import asyncio
import errno
import json
import os
import re
import shutil
import time
import uuid

from . import basemodel, busy, config, hashing, library, paths, smmeta

_LOG = "organize_log.json"

ALIASES = {  # extra folder names people commonly use for each family
    "Illustrious": ["il", "illustriousxl", "illu", "ilxl"],
    "NoobAI": ["noob", "noobxl", "nai"],
    "Pony": ["pdxl", "ponyxl", "ponydiffusion"],
    "SDXL": ["xl", "sdxl10", "sdxl1.0", "sd xl"],
    "SD1.5": ["sd15", "sd1", "sd 1.5", "15", "sd1x"],
    "SD2": ["sd21", "sd20", "sd2x"],
    "Flux": ["flux1", "flux.1", "fluxdev", "flux1dev"],
    "Flux.2": ["flux2"],
    "Wan": ["wan21", "wan22", "wan2.1", "wan2.2", "wanvideo"],
    "Z-Image": ["zimage", "z image", "zimageturbo"],
    "Qwen": ["qwenimage", "qwen-image", "qwen image", "qwenimageedit"],
    "HunyuanVideo": ["hunyuan", "hyvideo"],
    "LTXV": ["ltx", "ltxvideo"],
}


# Architecture-level detection can't tell these apart from their parent
PARENT = {"Illustrious": "SDXL", "Pony": "SDXL", "NoobAI": "SDXL", "Flux Kontext": "Flux", "Chroma": "Flux",
          "Krea 2": None}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def folder_for(family: str, cfg: dict | None = None) -> str:
    cfg = cfg or config.load()
    return (cfg.get("folder_names") or {}).get(family) or family


def _known_family_folders(cfg: dict) -> dict[str, str]:
    """normalized folder name -> family"""
    out = {}
    for fam in basemodel.FAMILIES:
        for n in [fam, folder_for(fam, cfg)] + ALIASES.get(fam, []):
            out[_norm(n)] = fam
    return out


# ------------------------------------------------------------------ plan
def plan(sections: list[str], mode: str = "loose") -> dict:
    cfg = config.load()
    known = _known_family_folders(cfg)
    moves, unknown, ok = [], [], 0
    taken: set[str] = set()
    for section in sections:
        for e in library.build(section):
            parts = e["rel"].split("/")
            fname, dirs = parts[-1], parts[:-1]
            if mode == "loose" and dirs:
                continue
            fam = e["family"]
            if not fam:
                unknown.append(library.public(e))
                continue
            target = folder_for(fam, cfg)
            cur = dirs[0] if dirs else None
            if cur and _norm(cur) == _norm(target):
                ok += 1
                continue
            cur_fam = known.get(_norm(cur)) if cur else None
            if cur_fam and PARENT.get(cur_fam) == fam and e["confidence"] != "high":
                # e.g. tensor layout says "SDXL" and it sits in Illustrious/ — consistent, leave it
                ok += 1
                continue
            if cur and _norm(cur) in known:
                new_dirs = [target] + dirs[1:]
                reason = f"In “{cur}” but detected {fam}"
            elif cur:
                new_dirs = [target] + dirs
                reason = f"Custom folder “{cur}” kept inside {target}"
            else:
                new_dirs = [target]
                reason = "Loose in root"
            to_rel = "/".join(new_dirs + [fname])
            dst = os.path.join(e["root"], *to_rel.split("/"))
            conflict = None
            if os.path.exists(dst) or dst.lower() in taken:
                conflict = "A file with this name already exists there"
            taken.add(dst.lower())
            moves.append({
                **library.public(e), "from_rel": e["rel"], "to_rel": to_rel, "target_folder": target,
                "reason": reason, "conflict": conflict,
                "checked": (e["confidence"] in ("high", "medium")) and not conflict,
            })
    order = {"high": 0, "medium": 1, "low": 2}
    moves.sort(key=lambda m: (order.get(m["confidence"], 3), m["rel"].lower()))
    return {"mode": mode, "moves": moves, "unknown": unknown, "already_sorted": ok,
            "folders": sorted({folder_for(f, cfg) for f in basemodel.FAMILIES})}


# ------------------------------------------------------------------ moving
def _exclusive(fn):
    """Moves refuse to run alongside a metadata fetch / duplicate scan (busy.Busy)."""
    import functools

    @functools.wraps(fn)
    def wrapper(*a, **k):
        with busy.operation("Moving files"):
            return fn(*a, **k)
    return wrapper


class MoveError(Exception):
    def __init__(self, msg, stranded=None):
        super().__init__(msg)
        self.stranded = stranded or []


def _mv(a: str, b: str) -> None:
    """Rename; copy+delete only for a genuine cross-drive move. A locked file
    (WinError 32) or permission problem fails instead of leaving a copy behind."""
    try:
        os.rename(a, b)
        return
    except OSError as ex:
        if ex.errno != errno.EXDEV and getattr(ex, "winerror", None) != 17:
            raise
    try:
        shutil.copy2(a, b)
        os.unlink(a)
    except BaseException:
        if os.path.exists(a) and os.path.exists(b):
            try:
                os.remove(b)  # drop the partial / duplicate copy
            except OSError:
                pass
        raise


def _fix_lm_metadata(dst_model: str) -> None:
    """LoRA Manager's .metadata.json stores absolute paths; keep them current."""
    p = smmeta.model_stem(dst_model) + ".metadata.json"
    if not os.path.isfile(p):
        return
    try:
        with open(p, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["file_path"] = dst_model.replace("\\", "/")
        prev = smmeta.find_preview(dst_model)
        if prev and meta.get("preview_url"):
            meta["preview_url"] = prev.replace("\\", "/")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _move_one(src: str, dst: str) -> list[tuple[str, str]]:
    """Move a model + its sidecars. Returns list of (src, dst) actually moved."""
    if os.path.exists(dst):
        raise FileExistsError(f"{os.path.basename(dst)} already exists in the target folder")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    done = []
    pairs = [(src, dst)]
    s_stem, d_stem = smmeta.model_stem(src), smmeta.model_stem(dst)
    for sc in smmeta.sidecars(src):
        pairs.append((sc, d_stem + sc[len(s_stem):]))
    try:
        for a, b in pairs:
            if os.path.exists(b):
                continue  # never overwrite a sidecar either
            _mv(a, b)
            done.append((a, b))
    except Exception as ex:
        stranded = []
        for a, b in reversed(done):  # roll back this model
            try:
                _mv(b, a)
            except Exception:
                stranded.append((a, b))
        if isinstance(ex, PermissionError) or getattr(ex, "winerror", None) in (5, 32):
            raise MoveError("File is in use (loaded by ComfyUI or another app) — skipped", stranded)
        raise MoveError(str(ex), stranded)
    hashing.rename(src, dst)
    _fix_lm_metadata(dst)
    return done


_KEEP_RUNS = 20


def _merge_log(shared, local):
    runs = {r["id"]: r for r in (shared or {}).get("runs", [])}
    for r in local.get("runs", []):
        runs.setdefault(r["id"], r)
    return {"runs": sorted(runs.values(), key=lambda r: r["time"])[-_KEEP_RUNS:]}


config.register_merger(_LOG, _merge_log)


def _log_run(kind: str, moved: list[tuple[str, str]]) -> str:
    rid = uuid.uuid4().hex[:10]

    def mut(log):
        log.setdefault("runs", []).append({"id": rid, "kind": kind, "time": time.time(),
                                           "moves": [{"src": a, "dst": b} for a, b in moved]})
        log["runs"] = log["runs"][-_KEEP_RUNS:]

    config.update_json(_LOG, {"runs": []}, mut)
    return rid


@_exclusive
def apply(items: list[dict], kind: str = "organize") -> dict:
    """items: [{id, to_rel}] (ids from the last library build)."""
    results, moved = [], []
    for it in items:
        e = library.get(it.get("id", ""))
        if not e:
            results.append({"id": it.get("id"), "ok": False, "error": "Unknown file (rescan)"})
            continue
        try:
            rel = paths.safe_rel_path(it["to_rel"])
            root = os.path.normpath(e["root"])
            dst = os.path.normpath(os.path.join(root, *rel.split("/")))
            if not os.path.normcase(dst).startswith(os.path.normcase(root) + os.sep):
                raise ValueError("Target escapes the model folder")
            moved += _move_one(e["path"], dst)
            results.append({"id": e["id"], "ok": True, "from": e["rel"], "to": rel,
                            "section": e["section"]})
        except MoveError as ex:
            moved += ex.stranded
            results.append({"id": e["id"], "ok": False, "error": str(ex)})
        except Exception as ex:
            results.append({"id": e["id"], "ok": False, "error": str(ex)})
    rid = _log_run(kind, moved) if moved else None
    paths.invalidate()
    return {"run_id": rid, "results": results,
            "moved": sum(1 for r in results if r["ok"]), "failed": sum(1 for r in results if not r["ok"])}


def history() -> list[dict]:
    log = config.read_json(_LOG, {"runs": []})
    return [{"id": r["id"], "kind": r["kind"], "time": r["time"],
             "count": sum(1 for m in r["moves"] if m["src"].lower().endswith(paths.MODEL_EXTS))}
            for r in reversed(log["runs"])]


@_exclusive
def undo(run_id: str | None = None) -> dict:
    log = config.read_json(_LOG, {"runs": []})
    if not log["runs"]:
        return {"ok": False, "error": "Nothing to undo"}
    run = next((r for r in log["runs"] if r["id"] == run_id), None) if run_id else log["runs"][-1]
    if not run:
        return {"ok": False, "error": "Run not found"}
    restored, failed, keep = 0, [], []
    for m in reversed(run["moves"]):
        a, b = m["src"], m["dst"]
        if not os.path.exists(b) or os.path.exists(a):
            failed.append(os.path.basename(b))
            continue
        try:
            os.makedirs(os.path.dirname(a), exist_ok=True)
            _mv(b, a)
            hashing.rename(b, a)
            if a.lower().endswith(paths.MODEL_EXTS):
                _fix_lm_metadata(a)
            restored += 1
        except Exception:
            failed.append(os.path.basename(b))
            keep.append(m)
    # remove now-empty folders we created — never climb to/above the original folder
    for m in run["moves"]:
        d = os.path.dirname(m["dst"])
        src_dir = os.path.normcase(os.path.dirname(m["src"])) + os.sep
        try:
            while d and not src_dir.startswith(os.path.normcase(d) + os.sep) and not os.listdir(d):
                os.rmdir(d)
                d = os.path.dirname(d)
        except OSError:
            pass
    # Moving can take minutes (cross-drive copies), so the log isn't locked while it
    # runs; re-read it now so runs other ComfyUI processes logged meanwhile survive.
    def mut(cur):
        runs = cur.setdefault("runs", [])
        if keep:
            for r in runs:
                if r["id"] == run["id"]:
                    r["moves"] = list(reversed(keep))  # still undoable later (e.g. after closing ComfyUI)
        else:
            cur["runs"] = [r for r in runs if r["id"] != run["id"]]

    config.update_json(_LOG, {"runs": []}, mut)
    paths.invalidate()
    return {"ok": True, "restored": restored, "failed": failed}


# ------------------------------------------------------------------ duplicates
_dup: dict = {"status": "idle"}


def dup_status() -> dict:
    return {k: v for k, v in _dup.items() if not k.startswith("_")}


async def find_duplicates(sections: list[str]) -> dict:
    if _dup.get("status") == "running":
        return dup_status()
    busy.begin("Scanning for duplicates")  # raises busy.Busy while files are being moved
    _dup.clear()
    _dup.update(status="running", phase="listing", done=0, total=0, groups=[], current=None)
    _dup["_task"] = asyncio.ensure_future(_find_dups(sections))
    return dup_status()


def _keeper_score(e: dict, known: dict) -> tuple:
    dirs = e["rel"].split("/")[:-1]
    in_family = bool(dirs) and _norm(dirs[0]) in known
    return (e["has_meta"], bool(e.get("preview")), in_family, -len(dirs), -e["mtime"])


async def _find_dups(sections: list[str]):
    cfg = config.load()
    known = _known_family_folders(cfg)
    try:
        entries = []
        for s in sections:
            entries += await asyncio.to_thread(library.build, s)
        by_size: dict[int, list[dict]] = {}
        for e in entries:
            if e["size"] >= 1024 * 1024:
                by_size.setdefault(e["size"], []).append(e)
        cands = [g for g in by_size.values() if len(g) > 1]
        todo = [e for g in cands for e in g]
        _dup.update(phase="hashing", total=len(todo))
        for e in todo:
            _dup["current"] = e["name"]
            # never trust sidecar hashes here — a stale one could quarantine a unique file
            e["sha256"] = hashing.cached(e["path"]) or await hashing.sha256_file(e["path"])
            _dup["done"] += 1
        by_hash: dict[str, list[dict]] = {}
        for e in todo:
            by_hash.setdefault(e["sha256"].lower(), []).append(e)
        groups = []
        for sha, g in by_hash.items():
            if len(g) < 2:
                continue
            g.sort(key=lambda e: _keeper_score(e, known), reverse=True)
            groups.append({"sha256": sha, "size": g[0]["size"],
                           "keep": library.public(g[0]),
                           "duplicates": [library.public(x) for x in g[1:]]})
        groups.sort(key=lambda g: -g["size"] * len(g["duplicates"]))
        _dup.update(status="done", phase="done", groups=groups,
                    wasted=sum(g["size"] * len(g["duplicates"]) for g in groups))
    except asyncio.CancelledError:
        _dup["status"] = "cancelled"
    except Exception as ex:
        _dup.update(status="error", error=str(ex))
    finally:
        _dup["current"] = None
        busy.end("Scanning for duplicates")


def quarantine_dir(e: dict) -> str:
    root = paths.sm_info().get("models_root") or os.path.dirname(os.path.normpath(e["root"]))
    return os.path.join(root, "_duplicates", e["section"])


@_exclusive
def quarantine(ids: list[str]) -> dict:
    results, moved = [], []
    for fid in ids:
        e = library.get(fid)
        if not e:
            results.append({"id": fid, "ok": False, "error": "Unknown file (rescan)"})
            continue
        dst = os.path.join(quarantine_dir(e), *e["rel"].split("/"))
        base, ext = os.path.splitext(dst)
        n = 1
        while os.path.exists(dst):
            dst = f"{base} ({n}){ext}"
            n += 1
        try:
            moved += _move_one(e["path"], dst)
            results.append({"id": fid, "ok": True, "to": dst})
        except MoveError as ex:
            moved += ex.stranded
            results.append({"id": fid, "ok": False, "error": str(ex)})
        except Exception as ex:
            results.append({"id": fid, "ok": False, "error": str(ex)})
    rid = _log_run("duplicates", moved) if moved else None
    paths.invalidate()
    return {"run_id": rid, "results": results, "moved": sum(r["ok"] for r in results),
            "quarantine": quarantine_dir(library.get(ids[0])) if ids and library.get(ids[0]) else None}

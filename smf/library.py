"""Model library index (for the gallery + organizer) and the CivitAI 'identify' job."""
from __future__ import annotations

import asyncio
import hashlib
import os
import time

from . import basemodel, busy, civarchive, config, hashing, hfmeta, paths, registry, smmeta, sources

try:
    import folder_paths
except ImportError:
    folder_paths = None

# Library sections shown in the UI -> ComfyUI folder key
SECTIONS = {
    "loras": "LoRAs",
    "checkpoints": "Checkpoints",
    "diffusion_models": "Diffusion models",
    "embeddings": "Embeddings",
    "controlnet": "ControlNet",
    "text_encoders": "Text encoders",
    "vae": "VAE",
    "upscale_models": "Upscalers",
}

SHORT = {  # badge text
    "Illustrious": "IL", "NoobAI": "NOOB", "Pony": "PONY", "SDXL": "XL", "SD1.5": "1.5", "SD2": "2.x",
    "SD3": "SD3", "Flux": "FLUX", "Flux Kontext": "KONTEXT", "Flux.2": "FLUX2", "Chroma": "CHROMA",
    "Qwen": "QWEN", "Wan": "WAN", "HunyuanVideo": "HUNYUAN", "LTXV": "LTX", "Lumina": "LUMINA",
    "Z-Image": "ZIMG", "Anima": "ANIMA", "HiDream": "HIDREAM",
}

_index: dict[str, dict] = {}       # id -> entry
_NF = "civitai_not_found.json"      # sha256 -> time of last failed lookup
NOT_FOUND_TTL = 30 * 24 * 3600


def _not_found() -> dict:
    return config.read_json(_NF, {})


def _merge_nf(shared, local):
    out = dict(shared or {})
    for k, t in local.items():
        out[k] = max(t, out.get(k, 0))
    return out


config.register_merger(_NF, _merge_nf)
_detect_cache: dict[str, tuple] = {}  # path -> (size, mtime, result)


def file_id(path: str) -> str:
    return hashlib.sha1(os.path.abspath(path).encode("utf-8", "surrogatepass")).hexdigest()[:16]


def roots(section: str) -> list[str]:
    """All real directories holding this kind of model (SM shared first)."""
    info = paths.sm_info()
    cands: list[str] = []
    for k, v in info["yaml_paths"].items():
        if paths.canonical(k) == section and not k.startswith("ultralytics_"):
            cands += v
    if folder_paths is not None:
        try:
            cands += folder_paths.get_folder_paths(section)
        except Exception:
            pass
    out, seen = [], set()
    for c in cands:
        if not os.path.isdir(c):
            continue
        r = os.path.realpath(c)
        if r in seen:
            continue
        seen.add(r)
        out.append(c)
    # drop roots nested inside another root
    reals = [os.path.realpath(c) for c in out]
    return [c for c, r in zip(out, reals)
            if not any(r != o and r.startswith(o + os.sep) for o in reals)]


def walk(section: str):
    """Yield (root, rel, full) for every model file, deduped by inode."""
    seen = set()
    for root in roots(section):
        for dp, dns, fns in os.walk(root, followlinks=True):
            dns[:] = [d for d in dns if not d.startswith((".", "_duplicates"))]
            for fn in fns:
                if not fn.lower().endswith(paths.MODEL_EXTS) or fn.endswith(".smf-part"):
                    continue
                full = os.path.join(dp, fn)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                key = (st.st_dev, st.st_ino) if st.st_ino else os.path.realpath(full)
                if key in seen:
                    continue
                seen.add(key)
                yield root, os.path.relpath(full, root).replace("\\", "/"), full, st


def _rules():
    cfg = config.load()
    return [(r.get("match", ""), r.get("family", "")) for r in cfg.get("extra_rules", []) if r.get("match")]


def detect_cached(full: str, st, section: str, info: dict) -> dict:
    hit = _detect_cache.get(full)
    if hit and hit[0] == st.st_size and hit[1] == st.st_mtime and hit[3] == info.get("base"):
        return hit[2]
    res = basemodel.detect(full, kind=section, civitai_base=info.get("base"), extra_rules=_rules())
    _detect_cache[full] = (st.st_size, st.st_mtime, res, info.get("base"))
    return res


def build(section: str) -> list[dict]:
    entries = []
    nf = _not_found()
    for root, rel, full, st in walk(section):
        info = smmeta.merged_info(full)
        det = detect_cached(full, st, section, info)
        prev = smmeta.find_preview(full)
        fid = file_id(full)
        e = {
            "id": fid, "section": section, "root": root, "rel": rel, "path": full,
            "name": os.path.basename(full), "size": st.st_size, "mtime": st.st_mtime,
            "title": info.get("title"), "version": info.get("version"),
            "base_label": info.get("base"), "family": det["family"], "confidence": det["confidence"],
            "evidence": det["evidence"], "badge": SHORT.get(det["family"] or "", (det["family"] or "UNKN").upper()[:7]),
            "trained_words": info.get("trained_words") or [], "model_id": info.get("model_id"),
            "version_id": info.get("version_id"), "sha256": info.get("sha256") or hashing.cached(full),
            "meta_source": info.get("source"), "has_meta": bool(info.get("title")),
            "preview": prev, "preview_video": bool(prev and prev.lower().endswith((".mp4", ".webm"))),
            "favorite": bool(info.get("favorite")), "nsfw": bool(info.get("nsfw")),
        }
        # "not on CivitAI" is re-checked after a while: files get uploaded later
        failed_at = nf.get((e["sha256"] or "").lower(), 0)
        e["lookup_failed"] = bool(failed_at and time.time() - failed_at < NOT_FOUND_TTL and not e["has_meta"])
        if e["model_id"]:
            e["page_url"] = f"https://civitai.com/models/{e['model_id']}" + (
                f"?modelVersionId={e['version_id']}" if e.get("version_id") else "")
        entries.append(e)
        _index[fid] = e
    entries.sort(key=lambda e: e["rel"].lower())
    return entries


def get(fid: str) -> dict | None:
    return _index.get(fid)


def public(e: dict) -> dict:
    out = {k: v for k, v in e.items() if k not in ("path", "root", "preview")}
    out["has_preview"] = bool(e.get("preview"))
    from . import tiering  # late import: tiering imports library
    out["archived"] = tiering.is_archived(e["path"])
    out["root_name"] = os.path.basename(e["root"].rstrip("/\\"))
    return out


# ------------------------------------------------------------ identify job
_job: dict = {"status": "idle"}


def job_status() -> dict:
    return {k: v for k, v in _job.items() if not k.startswith("_")}


async def identify(sections: list[str], force: bool = False, ids: list[str] | None = None) -> dict:
    if _job.get("status") == "running":
        return job_status()
    busy.begin("Fetching metadata")  # raises busy.Busy while files are being moved
    _job.clear()
    _job.update(status="running", done=0, total=0, found=0, not_found=0, errors=0, current=None,
                log=[], started=time.time())
    _job["_task"] = asyncio.ensure_future(_identify(sections, force, ids))
    return job_status()


def cancel_identify():
    t = _job.get("_task")
    if t and not t.done():
        t.cancel()


async def _identify(sections: list[str], force: bool, ids: list[str] | None = None):
    cfg = config.load()
    try:
        todo, everything = [], []
        for s in sections:
            for e in await asyncio.to_thread(build, s):
                everything.append(e)
                if ids is not None:
                    if e["id"] in ids:
                        todo.append(e)
                elif force or (not e["has_meta"] and not e["lookup_failed"]):
                    todo.append(e)
        force = force or ids is not None
        _job["total"] = len(todo)
        for e in todo:
            _job["current"] = e["name"]
            try:
                sha = e.get("sha256") or await hashing.sha256_file(e["path"])
                cand = await sources.civitai_by_hash(sha)
                ca = None
                if not (cand and cand.get("meta")) and civarchive.enabled():
                    try:  # not on CivitAI (any more): CivArchive may have kept its details
                        ca = await civarchive.by_hash(sha)
                    except Exception:
                        ca = None
                if not os.path.exists(e["path"]):  # moved by another ComfyUI meanwhile
                    raise FileNotFoundError("file moved or deleted during the lookup")
                if cand and cand.get("meta"):
                    meta = cand["meta"]
                    if cfg.get("write_sm_metadata"):
                        meta = await sources.with_description(meta)
                        smmeta.write_cm_info(e["path"], meta, overwrite=force)
                    if cfg.get("download_previews"):
                        await smmeta.download_preview(e["path"], meta.get("preview"))
                    registry.remember(e["name"], cand["url"], source="civitai", sha256=sha, size=e["size"],
                                      folder=e["section"], page_url=cand.get("page_url"), title=cand.get("title"))
                    _job["found"] += 1
                    _job["log"].append({"name": e["name"], "ok": True, "title": cand.get("title")})
                elif ca and (ca.get("meta") or civarchive.best_url(ca)):
                    meta = ca.get("meta") or {}
                    if meta.get("modelName") and cfg.get("write_sm_metadata"):
                        smmeta.write_cm_info(e["path"], meta, overwrite=force)
                    if cfg.get("download_previews"):
                        await smmeta.download_preview(e["path"], meta.get("preview"))
                    title = " — ".join(x for x in (meta.get("modelName"), meta.get("versionName")) if x) or None
                    url = civarchive.best_url(ca)
                    if url:
                        registry.remember(e["name"], url, source="civarchive", sha256=sha, size=e["size"],
                                          folder=e["section"], page_url=ca["page_url"], title=title)
                    if not (meta.get("modelName") and cfg.get("write_sm_metadata")):
                        # nothing written next to it: remember the lookup, or every run asks again
                        config.update_json(_NF, {}, lambda nf: nf.__setitem__(sha.lower(), time.time()))
                    _job["found"] += 1
                    _job["archived"] = _job.get("archived", 0) + 1
                    _job["log"].append({"name": e["name"], "ok": True,
                                        "title": f"{title or 'Listed'} (CivArchive" + (", removed from CivitAI)" if ca.get("deleted_on_civitai") else ")")})
                else:
                    config.update_json(_NF, {}, lambda nf: nf.__setitem__(sha.lower(), time.time()))
                    _job["not_found"] += 1
                    _job["log"].append({"name": e["name"], "ok": False, "title": "Not on CivitAI"})
                await asyncio.sleep(0.25)  # be polite to the API
            except asyncio.CancelledError:
                raise
            except Exception as ex:
                _job["errors"] += 1
                _job["log"].append({"name": e["name"], "ok": False, "title": f"Error: {ex}"})
            _job["done"] += 1
            _job["log"] = _job["log"][-200:]
        # models from HuggingFace: license, tags and model card (not on CivitAI, so the loop above skips them)
        pool = [e for e in everything if ids is None or e["id"] in ids]
        _job["hf"] = await hfmeta.fetch_missing(pool, progress=lambda repo: _job.__setitem__("current", f"HuggingFace: {repo}"))
        _job["status"] = "done"
    except asyncio.CancelledError:
        _job["status"] = "cancelled"
    except Exception as ex:
        _job["status"], _job["error"] = "error", str(ex)
    finally:
        _job["current"] = None
        busy.end("Fetching metadata")

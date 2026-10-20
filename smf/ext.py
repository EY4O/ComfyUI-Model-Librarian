"""What the Model Librarian Chrome extension asks for: who's there, which CivitAI
versions are already in the library, and "download this version's file" (planned
like the Recipes tab plans downloads: the right folder for its type, sorted by
base model, SHA256-verified, with metadata and preview). Keys stay here: the
extension never sees or sends them."""
from __future__ import annotations

import os
import re
import threading
import time

from . import basemodel, config, downloader, hashing, net, organize, paths, sources

# CivitAI model type -> ComfyUI folder (types that aren't model files ComfyUI loads are refused)
TYPE_FOLDERS = {
    "Checkpoint": "checkpoints", "LORA": "loras", "LoCon": "loras", "DoRA": "loras",
    "TextualInversion": "embeddings", "VAE": "vae", "Controlnet": "controlnet", "Upscaler": "upscale_models",
    "MotionModule": "animatediff_models", "Hypernetwork": "hypernetworks",
}
FILE_TYPE_FOLDERS = {"VAE": "vae", "Diffusion Model": "diffusion_models", "Text Encoder": "text_encoders"}
SORTED_FOLDERS =("checkpoints", "loras", "diffusion_models")  # sorted into base-model subfolders, as Organize does
LIBRARY_SECTIONS = ("checkpoints", "diffusion_models", "loras", "embeddings", "vae", "controlnet", "upscale_models")
OWNED_TTL = 300
ACTIVE = ("queued", "downloading", "verifying")


def plugin_version() -> str:
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pyproject.toml"), encoding="utf-8") as f:
            m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M)
        return m.group(1) if m else "?"
    except OSError:
        return "?"


def hello() -> dict:
    cfg = config.load()
    info = paths.sm_info()
    root = info.get("models_root")
    from . import tiering
    return {"app": "model-librarian", "version": plugin_version(), "models_root": root,
            "free_bytes": tiering.free_bytes(root), "civitai_key": bool(cfg.get("civitai_token")),
            "active_downloads": sum(1 for j in downloader.jobs() if j.get("status") in ACTIVE),
            "system": system(cfg)}


_system: dict | None = None


def system(cfg: dict | None = None) -> dict:
    """What decides which file of a model suits this PC: the GPU and its VRAM, the formats this
    ComfyUI runs at full speed (its own checks), and the loaders installed. The GPU part is read
    once; the budget follows Settings' headroom."""
    global _system
    cfg = cfg or config.load()
    if _system is None:
        s = {"gpu": None, "vram_total": None, "capability": None, "fast": {}, "formats": [], "loaders": {}}
        try:
            import comfy.model_management as mm
            dev = mm.get_torch_device()
            s["gpu"] = mm.get_torch_device_name(dev)
            if getattr(dev, "type", "") != "cpu":  # on the CPU "VRAM" is RAM: no fit to suggest
                s["vram_total"] = int(mm.get_total_memory(dev))
            else:
                s["cpu"] = True
            if getattr(dev, "type", "") == "cuda":
                import torch
                s["capability"] = ".".join(map(str, torch.cuda.get_device_capability(dev)))
            for key, fn in (("fp8", "supports_fp8_compute"), ("nvfp4", "supports_nvfp4_compute"),
                            ("mxfp8", "supports_mxfp8_compute"), ("int8", "supports_int8_compute")):
                f = getattr(mm, fn, None)
                if f:
                    try:
                        s["fast"][key] = bool(f(dev))
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            from comfy import quant_ops
            s["formats"] = sorted(getattr(quant_ops, "QUANT_ALGOS", {}))  # quantized formats ComfyUI loads itself
        except Exception:
            pass
        try:
            import nodes
            classes = list(getattr(nodes, "NODE_CLASS_MAPPINGS", {}))
            s["loaders"] = {"gguf": any("GGUF" in c for c in classes), "nunchaku": any(c.startswith("Nunchaku") for c in classes)}
        except Exception:
            pass
        if s["gpu"] is not None or s["loaders"]:
            _system = s
    s = dict(_system or {"gpu": None, "vram_total": None, "capability": None, "fast": {}, "formats": [], "loaders": {}})
    gb = 1024 ** 3
    vram = s["vram_total"] / gb if s.get("vram_total") else 0 if s.get("cpu") else float(cfg.get("vram_gb") or 0)
    s["budget"] = int(max(1.0, vram - float(cfg.get("headroom_gb") or 0)) * gb) if vram else None
    return s


# ---------------------------------------------------------------- what's already here
_owned: dict = {"at": 0.0, "versions": {}, "hashes": {}}
_owned_lock = threading.Lock()


def _owned_index(force: bool = False) -> dict:
    """versionId -> file and sha256 -> file over the library (rebuilt every few minutes)."""
    with _owned_lock:
        if not force and time.time() - _owned["at"] < OWNED_TTL:
            return _owned
        from . import library, smmeta
        versions, hashes = {}, {}
        for sec in LIBRARY_SECTIONS:
            try:
                walked = list(library.walk(sec))
            except Exception:
                continue
            for _root, rel, full, _st in walked:
                try:
                    info = smmeta.merged_info(full)
                except Exception:
                    info = {}
                where = {"folder": sec, "rel": rel}
                if info.get("version_id"):
                    versions[str(info["version_id"])] = where
                sha = (info.get("sha256") or hashing.cached(full) or "").lower()
                if sha:
                    hashes[sha] = where
        _owned.update(at=time.time(), versions=versions, hashes=hashes)
        return _owned


def _job_for(version_id: str) -> dict | None:
    """This session's download of that version (newest first)."""
    for j in sorted(downloader.jobs(), key=lambda j: j.get("created") or 0, reverse=True):
        if str((j.get("meta") or {}).get("versionId") or "") == version_id:
            return j
    return None


def lookup(version_ids: list, hashes: list | None = None) -> dict:
    """-> {versions: {id: {status: have|downloading|missing, folder, rel, job}}, hashes: {sha: {...}}}."""
    idx = _owned_index()
    out_v, out_h = {}, {}
    for vid in [str(v) for v in version_ids or [] if str(v).isdigit()][:200]:
        where = idx["versions"].get(vid)
        j = _job_for(vid)
        if where:
            out_v[vid] = {"status": "have", **where}
        elif j and j.get("status") in ACTIVE:
            out_v[vid] = {"status": "downloading", "job": slim_job(j)}
        elif j and j.get("status") == "done":
            out_v[vid] = {"status": "have", "folder": j.get("folder"), "rel": j.get("rel")}
        else:
            out_v[vid] = {"status": "missing"}
    for sha in [str(h).lower() for h in hashes or [] if re.fullmatch(r"[0-9a-fA-F]{64}", str(h))][:200]:
        where = idx["hashes"].get(sha)
        out_h[sha] = {"status": "have", **where} if where else {"status": "missing"}
    return {"versions": out_v, "hashes": out_h}


# ---------------------------------------------------------------- download
async def _version_file(version_id: int, file_id: int | None) -> tuple[dict, dict, dict]:
    v = await net.get_json(f"{net.CIVITAI_BASE}/api/v1/model-versions/{int(version_id)}")
    if not v or not v.get("files"):
        raise LookupError("CivitAI doesn't have that version (removed, or it needs a login)")
    model = dict(v.get("model") or {})
    model.setdefault("id", v.get("modelId"))
    files = v["files"]
    f = next((f for f in files if file_id and f.get("id") == int(file_id)), None)
    if file_id and not f:
        raise LookupError("That file isn't in this version any more")
    f = f or next((f for f in files if f.get("primary")), files[0])
    return model, v, f


def plan(model: dict, version: dict, file: dict) -> dict:
    """Where CivitAI's file goes: the folder for its type, a base-model subfolder for
    checkpoints, LoRAs and diffusion models (Organize's names)."""
    mtype = model.get("type") or ""
    ftype = str(file.get("type") or "")
    if ftype in ("Training Data", "Archive"):
        raise ValueError(f"That file is the model's {ftype.lower()}, not a model ComfyUI loads")
    # what the file itself is wins over the model's type: a "Checkpoint" page often offers just the
    # diffusion model (UNet), or bundles its VAE and text encoder as separate files
    folder = FILE_TYPE_FOLDERS.get(ftype) or TYPE_FOLDERS.get(mtype)
    if not folder:
        raise ValueError(f"A {mtype or 'file of this type'} isn't a model ComfyUI loads, so it isn't downloaded here")
    if folder == "checkpoints" and str((file.get("metadata") or {}).get("format") or "").lower() == "gguf":
        folder = "diffusion_models"  # a GGUF "checkpoint" is a UNet: ComfyUI-GGUF loads it from here
    name = os.path.basename(str(file.get("name") or "").replace("\\", "/")) or f"civitai_{version.get('id')}.safetensors"
    fam = basemodel.from_text(version.get("baseModel") or "") if version.get("baseModel") else None
    rel = f"{organize.folder_for(fam)}/{name}" if fam and folder in SORTED_FOLDERS else name
    dest, shared = paths.dest_path(folder, rel)
    return {"folder": folder, "rel": rel, "dest": dest, "shared": shared}


def slim_job(j: dict) -> dict:
    keys = ("id", "status", "done", "total", "speed", "error", "folder", "rel", "dest", "title", "created", "finished")
    return {k: j.get(k) for k in keys if k in j}


async def download(version_id, file_id=None, dry_run: bool = False) -> dict:
    """-> {status: started|have|downloading|planned, ...}. Already-present files and running
    downloads of the same version aren't started again."""
    try:
        vid = int(version_id)
        fid = int(file_id) if file_id not in (None, "") else None
    except (TypeError, ValueError):
        raise ValueError("version_id must be a number") from None
    model, version, f = await _version_file(vid, fid)
    cand = sources._civ_file_cand(model, version, f, "high")
    p = plan(model, version, f)
    info = {"title": cand.get("title"), "file": f.get("name"), "size": cand.get("size"), "base_model": version.get("baseModel"),
            "type": model.get("type"), "folder": p["folder"], "rel": p["rel"], "dest": p["dest"]}
    sha = (cand.get("sha256") or "").lower()
    owned = _owned_index()["hashes"].get(sha) if sha else None
    if os.path.exists(p["dest"]) or owned:
        where = owned or {"folder": p["folder"], "rel": p["rel"]}
        return {"status": "have", **info, **where}
    running = next((j for j in downloader.jobs() if j.get("status") in ACTIVE
                    and (j.get("dest") == p["dest"] or (sha and (j.get("sha256") or "").lower() == sha))), None)
    if running:
        return {"status": "downloading", **info, "job": slim_job(running)}
    if not cand.get("url"):
        raise LookupError("CivitAI doesn't offer a download for that file")
    if dry_run:
        return {"status": "planned", **info, "civitai_key": bool(config.load().get("civitai_token"))}
    job = downloader.start(url=cand["url"], folder=p["folder"], rel=p["rel"], sha256=cand.get("sha256"), size=cand.get("size"),
                           source="civitai", page_url=cand.get("page_url"), title=cand.get("title"), meta=cand.get("meta"),
                           auto_place=p["folder"] == "checkpoints")
    with _owned_lock:
        _owned["at"] = 0.0  # the next lookup sees it
    return {"status": "started", **info, "job": slim_job(job)}


def jobs(ids: list[str]) -> list[dict]:
    want = set(ids or [])
    return [slim_job(j) for j in downloader.jobs() if not want or j.get("id") in want]

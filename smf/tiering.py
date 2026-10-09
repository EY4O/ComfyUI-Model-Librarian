"""SSD/HDD storage tiers.

Models you haven't used for a while can move to an archive folder (e.g. on an
external HDD) and come back to the SSD when a workflow uses them again.

* The archive mirrors Stability Matrix's layout (<archive>/Lora/Illustrious/x)
  and is registered with ComfyUI at startup, so archived models keep their
  exact names: workflows don't break, they just load more slowly from the HDD.
* "Used" means a queued prompt loaded it (recorded by an on-prompt hook) —
  including LoRA Manager lists and <lora:...> text. Models never seen used start
  their clock when they're first seen, so nothing is archived on day one.
* Archiving is suggested and needs approval. Every copy is SHA256-verified
  before the original is removed; sidecars move with the model; runs are
  logged in the organize history, so Undo works.
* After a prompt uses an archived model, it's copied back to the SSD once the
  queue is idle. If ComfyUI still holds the HDD copy open, removing it is
  retried later (the SSD copy wins in ComfyUI's lists meanwhile).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import threading
import time

from . import busy, config, hashing, infer, library, paths, smmeta

try:
    import folder_paths
except ImportError:
    folder_paths = None

_USAGE = "usage.json"   # shared: {"last_used": {key: ts}, "first_seen": {key: ts}, "cleanup": [paths]}
_CHUNK = 16 * 1024 * 1024
_LORA_SYNTAX = re.compile(r"<lora:([^:>]+):[^>]*>", re.I)
log = logging.getLogger("Model Librarian")

_events: list[dict] = []          # for the UI: archived / restored / errors
_job: dict = {"status": "idle"}
_restore_q: dict[str, float] = {}  # archived path -> queued at
_q_lock = threading.Lock()
_worker: threading.Thread | None = None


# ---------------------------------------------------------------- locations
_ad_cache: tuple[float, str | None] = (0.0, None)


def archive_dir() -> str | None:
    """The archive folder setting (cached briefly: is_archived runs once per model)."""
    global _ad_cache
    if time.time() - _ad_cache[0] < 2:
        return _ad_cache[1]
    d = str(config.load().get("archive_dir") or "").strip()
    d = os.path.normpath(os.path.expandvars(os.path.expanduser(d))) if d else None
    _ad_cache = (time.time(), d)
    return d


def reset_cache() -> None:
    global _ad_cache
    _ad_cache = (0.0, None)


def archive_root(section: str) -> str | None:
    d = archive_dir()
    sm = paths.COMFY_TO_SM.get(section)
    return os.path.join(d, *sm.split("/")) if d and sm else None


def connected() -> bool:
    d = archive_dir()
    if not d:
        return False
    drive = os.path.splitdrive(d)[0]
    return os.path.isdir(drive + os.sep) if drive else os.path.isdir(os.path.dirname(d) or d)


def is_archived(path: str) -> bool:
    d = archive_dir()
    if not d:
        return False
    a = os.path.normcase(os.path.abspath(d)) + os.sep
    return os.path.normcase(os.path.abspath(path)).startswith(a)


def ssd_root(section: str) -> str | None:
    return next((r for r in library.roots(section) if not is_archived(r)), None)


def register_folders() -> list[str]:
    """Add existing archive folders to ComfyUI's model folder lists (after the
    SSD ones, so an SSD copy always wins)."""
    added = []
    reset_cache()  # called after settings change
    if folder_paths is None or not archive_dir():
        return added
    for section in paths.COMFY_TO_SM:
        root = archive_root(section)
        if root and os.path.isdir(root):
            try:
                if root not in folder_paths.get_folder_paths(section):
                    folder_paths.add_model_folder_path(section, root, is_default=False)
                    added.append(root)
            except Exception:
                pass
    paths.invalidate()
    return added


def lm_extra_paths() -> dict:
    """Archive folders in LoRA Manager's extra_folder_paths format."""
    out = {}
    for lm_key, section in (("loras", "loras"), ("checkpoints", "checkpoints"), ("unet", "diffusion_models"),
                            ("embeddings", "embeddings")):
        r = archive_root(section)
        if r:
            out[lm_key] = [r.replace("\\", "/")]
    return out


# ---------------------------------------------------------------- usage
def key_for(section: str, name: str) -> str:
    stem = paths.norm_rel(name).rsplit("/", 1)[-1].lower()
    if paths.is_model_value(stem):
        stem = os.path.splitext(stem)[0]
    return f"{paths.canonical(section) or '*'}:{stem}"


def _merge_usage(shared, local):
    out = shared or {"last_used": {}, "first_seen": {}, "cleanup": []}
    for k in ("last_used", "first_seen"):
        d = out.setdefault(k, {})
        for key, t in (local.get(k) or {}).items():
            d[key] = max(t, d.get(key, 0)) if k == "last_used" else min(t, d.get(key, t))
    out["cleanup"] = sorted(set(out.get("cleanup") or []) | set(local.get("cleanup") or []))
    return out


config.register_merger(_USAGE, _merge_usage)


def _usage() -> dict:
    u = config.read_json(_USAGE, {})
    for k in ("last_used", "first_seen"):
        u.setdefault(k, {})
    u.setdefault("cleanup", [])
    return u


def _folder_for(class_type: str, input_name: str) -> str:
    f = infer.KNOWN.get((class_type, input_name)) or infer.KNOWN.get((class_type, "*"))
    if f:
        return f
    w = f"{input_name} {class_type}".lower()
    return next((folder for needle, folder in infer.HEURISTICS if needle in w), "*")


def models_in_prompt(prompt: dict) -> list[tuple[str, str]]:
    """(section, name) for every model a queued prompt (API format) uses.
    LoRA Manager names come without an extension."""
    out = []
    for node in (prompt or {}).values():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type") or "")
        lm = ct.endswith("(LoraManager)")
        for name, v in (node.get("inputs") or {}).items():
            if isinstance(v, str):
                if paths.is_model_value(v):
                    out.append((_folder_for(ct, name), v))
                elif lm and "<lora:" in v.lower():
                    out += [("loras", m.strip()) for m in _LORA_SYNTAX.findall(v)]
            elif lm and name == "loras":
                lst = v.get("__value__") if isinstance(v, dict) else v
                out += [("loras", str(e["name"])) for e in lst or []
                        if isinstance(e, dict) and e.get("active") and e.get("name")]
            elif isinstance(v, dict) and v.get("on", True):  # rgthree Power Lora Loader rows
                out += [("loras" if "lora" in ct.lower() else "*", s) for s in v.values()
                        if isinstance(s, str) and paths.is_model_value(s)]
    return out


def record_use(models: list[tuple[str, str]]) -> None:
    if not models:
        return
    now = time.time()

    def mut(u):
        d = u.setdefault("last_used", {})
        for section, name in models:
            d[key_for(section, name)] = now
            d[key_for("*", name)] = now  # folder unknown to the hook: match by name too
    config.update_json(_USAGE, {"last_used": {}, "first_seen": {}, "cleanup": []}, mut)


def last_used(u: dict, section: str, name: str) -> float:
    lu = u.get("last_used") or {}
    return max(lu.get(key_for(section, name), 0), lu.get(key_for("*", name), 0))


# ---------------------------------------------------------------- copying
def _sha256(path: str, progress=None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(_CHUNK)
            if not b:
                break
            h.update(b)
            if progress:
                progress(len(b))
    return h.hexdigest()


def _copy_verified(src: str, dst: str, progress=None) -> str:
    """Copy src -> dst via a temp file, verify SHA256, keep mtime. -> sha256.
    Raises (and leaves nothing behind) on any mismatch."""
    want = hashing.cached_strict(src) or _sha256(src)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".smf-copy"
    h = hashlib.sha256()
    try:
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            while True:
                b = fi.read(_CHUNK)
                if not b:
                    break
                fo.write(b)
                if progress:
                    progress(len(b))
            fo.flush()
            os.fsync(fo.fileno())
        shutil.copystat(src, tmp)
        got = _sha256(tmp)  # re-read from the target disk, not the write buffer
        if got != want:
            raise OSError("copy verification failed (SHA256 mismatch) — original kept")
        if os.path.exists(dst):
            raise FileExistsError(f"{os.path.basename(dst)} already exists in the target folder")
        os.replace(tmp, dst)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return want


def _move_verified(src: str, dst: str, progress=None) -> list[tuple[str, str]]:
    """Model + sidecars to another drive: verified copy, then remove the originals.
    -> moved pairs. If the original is in use it isn't removed and the copy is undone."""
    if os.path.exists(dst):
        raise FileExistsError(f"{os.path.basename(dst)} already exists in the target folder")
    sha = _copy_verified(src, dst, progress)
    s_stem, d_stem = smmeta.model_stem(src), smmeta.model_stem(dst)
    side = [(sc, d_stem + sc[len(s_stem):]) for sc in smmeta.sidecars(src)]
    try:
        os.remove(src)
    except PermissionError:
        os.remove(dst)
        raise PermissionError("File is in use (loaded by ComfyUI or another app) — skipped")
    moved = [(src, dst)]
    for a, b in side:
        if not os.path.exists(b):
            try:
                shutil.copy2(a, b)
                os.remove(a)
                moved.append((a, b))
            except OSError:
                pass
    hashing.store(dst, sha)
    from .organize import _fix_lm_metadata
    _fix_lm_metadata(dst)
    return moved


# ---------------------------------------------------------------- plan / jobs
def plan() -> dict:
    cfg = config.load()
    d = archive_dir()
    days = float(cfg.get("archive_after_days") or 60)
    sections = [s for s in cfg.get("archive_sections") or [] if s in library.SECTIONS]
    now = time.time()
    u = _usage()
    ready, archived, unseen = [], [], {}
    for section in sections:
        for e in library.build(section):
            item = {"id": e["id"], "name": e["name"], "rel": e["rel"], "section": section, "size": e["size"],
                    "title": e.get("title"), "family": e.get("family")}
            lu = last_used(u, section, e["name"])
            item["last_used"] = lu or None
            if is_archived(e["path"]):
                archived.append(item)
                continue
            k = key_for(section, e["name"])
            first = u["first_seen"].get(k)
            if not first:
                unseen[k] = first = now
            idle = (now - max(lu, first)) / 86400
            item["idle_days"] = round(idle, 1)
            if idle >= days:
                ready.append(item)
    if unseen:
        config.update_json(_USAGE, {"last_used": {}, "first_seen": {}, "cleanup": []},
                           lambda x: [x.setdefault("first_seen", {}).setdefault(k, t) for k, t in unseen.items()])
    free = None
    if d and connected():
        try:
            os.makedirs(d, exist_ok=True)
            free = shutil.disk_usage(d).free
        except OSError:
            free = None
    ready.sort(key=lambda x: -x["size"])
    return {"archive_dir": d, "connected": bool(d) and connected(), "free": free, "after_days": days,
            "sections": sections, "ready": ready, "archived": sorted(archived, key=lambda x: x["rel"].lower()),
            "ready_bytes": sum(x["size"] for x in ready), "archived_bytes": sum(x["size"] for x in archived),
            "restore_on_use": bool(cfg.get("restore_on_use", True)), "queued_restores": len(_restore_q)}


def job_status() -> dict:
    return {k: v for k, v in _job.items() if not k.startswith("_")}


def events(since: float = 0) -> list[dict]:
    return [e for e in _events if e["time"] > since]


def _event(kind: str, **kw) -> None:
    _events.append({"kind": kind, "time": time.time(), **kw})
    del _events[:-200]


def _archive_one(e: dict, progress) -> list[tuple[str, str]]:
    root = archive_root(e["section"])
    if not root:
        raise OSError("No archive folder set (Settings → Storage tiers)")
    if not connected():
        raise OSError("The archive drive isn't connected")
    os.makedirs(root, exist_ok=True)
    free = shutil.disk_usage(root).free
    if e["size"] + 512 * 1024 * 1024 > free:
        raise OSError(f"Not enough space on the archive drive ({free / 1e9:.1f} GB free)")
    dst = os.path.join(root, *e["rel"].split("/"))
    moved = _move_verified(e["path"], dst, progress)
    register_folders()
    return moved


def _restore_path(src: str, progress=None) -> list[tuple[str, str]]:
    """Archived file -> its SSD folder (same relative path)."""
    for section in paths.COMFY_TO_SM:
        root = archive_root(section)
        if root and os.path.normcase(os.path.abspath(src)).startswith(os.path.normcase(os.path.abspath(root)) + os.sep):
            ssd = ssd_root(section)
            if not ssd:
                raise OSError(f"No SSD folder for {section}")
            rel = os.path.relpath(src, root)
            dst = os.path.join(ssd, rel)
            if os.path.exists(dst):
                # Already back (e.g. an earlier cleanup failed)? Only drop the HDD copy
                # when it's provably the same file — never delete a different one.
                same = (hashing.cached_strict(dst) or _sha256(dst)) == (hashing.cached_strict(src) or _sha256(src))
                if not same:
                    raise FileExistsError(f"a different {os.path.basename(dst)} is already on the SSD — both kept")
                _try_cleanup(src)
                return []
            sha = _copy_verified(src, dst, progress)
            s_stem, d_stem = smmeta.model_stem(src), smmeta.model_stem(dst)
            moved = [(src, dst)]
            for sc in smmeta.sidecars(src):
                b = d_stem + sc[len(s_stem):]
                if not os.path.exists(b):
                    shutil.copy2(sc, b)
                    moved.append((sc, b))
            hashing.store(dst, sha)
            from .organize import _fix_lm_metadata
            _fix_lm_metadata(dst)
            for a, _b in moved:
                _try_cleanup(a)
            paths.invalidate()
            return moved
    raise OSError("Not in the archive")


def _try_cleanup(path: str) -> None:
    """Remove an archive copy that's back on the SSD; if ComfyUI still has it open,
    remember it and retry later."""
    try:
        os.remove(path)
        return
    except FileNotFoundError:
        return
    except OSError:
        pass
    config.update_json(_USAGE, {"last_used": {}, "first_seen": {}, "cleanup": []},
                       lambda u: u.setdefault("cleanup", []).append(path) if path not in u.get("cleanup", []) else None)


def retry_cleanup() -> int:
    """Remove archive copies whose SSD copy exists and that are no longer in use."""
    left, done = [], 0
    for p in _usage().get("cleanup") or []:
        try:
            os.remove(p)
            done += 1
        except FileNotFoundError:
            done += 1
        except OSError:
            left.append(p)
    if done:
        config.update_json(_USAGE, {"last_used": {}, "first_seen": {}, "cleanup": []},
                           lambda u: u.__setitem__("cleanup", [p for p in u.get("cleanup", []) if p in left]))
    return done


def _run_job(kind: str, ids: list[str]) -> None:
    from . import organize
    entries = [library.get(i) for i in ids]
    entries = [e for e in entries if e]
    _job.update(total_bytes=sum(e["size"] for e in entries), done_bytes=0, total=len(entries))

    def progress(n):
        _job["done_bytes"] = _job.get("done_bytes", 0) + n

    moved_all, results = [], []
    for e in entries:
        _job["current"] = e["name"]
        try:
            if kind == "archive":
                if is_archived(e["path"]):
                    raise OSError("already on the archive drive")
                moved = _archive_one(e, progress)
            else:
                if not is_archived(e["path"]):
                    raise OSError("not on the archive drive")
                moved = _restore_path(e["path"], progress)
            moved_all += moved
            results.append({"id": e["id"], "name": e["name"], "ok": True})
            _event("archived" if kind == "archive" else "restored", name=e["name"], section=e["section"])
        except Exception as ex:
            results.append({"id": e["id"], "name": e["name"], "ok": False, "error": str(ex)})
            _event("error", name=e["name"], section=e["section"], error=str(ex))
        _job["done"] = _job.get("done", 0) + 1
    if moved_all:
        organize._log_run(kind, moved_all)  # Organize → History can undo it
    paths.invalidate()
    _job.update(results=results, ok=sum(r["ok"] for r in results), failed=sum(not r["ok"] for r in results))


async def start_job(kind: str, ids: list[str]) -> dict:
    if _job.get("status") == "running":
        return job_status()
    name = "Archiving to the HDD" if kind == "archive" else "Restoring from the HDD"
    busy.begin(name)
    _job.clear()
    _job.update(status="running", kind=kind, done=0, total=len(ids), current=None, started=time.time())

    async def run():
        try:
            await asyncio.to_thread(_run_job, kind, ids)
            _job["status"] = "done"
        except Exception as ex:
            _job.update(status="error", error=str(ex))
        finally:
            _job["current"] = None
            busy.end(name)
    _job["_task"] = asyncio.ensure_future(run())
    return job_status()


# ---------------------------------------------------------------- restore after use
def _archived_files_for(models: list[tuple[str, str]]) -> list[str]:
    if not archive_dir() or folder_paths is None:
        return []
    out = []
    inv = None
    for section, name in models:
        full = None
        if section != "*" and paths.is_model_value(name):
            try:
                full = folder_paths.get_full_path(section, name)
            except Exception:
                full = None
        elif section == "loras" and not paths.is_model_value(name):  # LoRA Manager name
            inv = inv or paths.Inventory()
            state, f, n = inv.find_lm(name)
            full = inv.full_path(f, n) if state == "present" else None
        if full and is_archived(full) and full not in out:
            out.append(full)
    return out


def _queue_idle() -> bool:
    try:
        from server import PromptServer
        return PromptServer.instance.prompt_queue.get_tasks_remaining() == 0
    except Exception:
        return True


def _restore_worker() -> None:
    global _worker
    try:
        while True:
            time.sleep(5)
            with _q_lock:
                if not _restore_q:
                    return
            if not _queue_idle() or busy.current():
                continue
            with _q_lock:
                todo = list(_restore_q)
                _restore_q.clear()
            for p in todo:
                if not os.path.exists(p):
                    continue
                try:
                    busy.begin("Restoring from the HDD")
                except busy.Busy:
                    with _q_lock:
                        _restore_q[p] = time.time()
                    continue
                try:
                    from . import organize
                    moved = _restore_path(p)
                    if moved:
                        organize._log_run("restore", moved)
                    _event("restored", name=os.path.basename(p), section=_section_of(p), auto=True)
                except Exception as ex:
                    _event("error", name=os.path.basename(p), error=f"restore after use failed: {ex}")
                finally:
                    busy.end("Restoring from the HDD")
            retry_cleanup()
    finally:
        _worker = None


def _section_of(p: str) -> str | None:
    for section in paths.COMFY_TO_SM:
        r = archive_root(section)
        if r and os.path.normcase(os.path.abspath(p)).startswith(os.path.normcase(os.path.abspath(r)) + os.sep):
            return section
    return None


def _after_prompt(models: list[tuple[str, str]]) -> None:
    global _worker
    try:
        record_use(models)
        if not config.load().get("restore_on_use", True):
            return
        files = _archived_files_for(models)
        if not files:
            return
        with _q_lock:
            for f in files:
                _restore_q.setdefault(f, time.time())
            if _worker is None:
                _worker = threading.Thread(target=_restore_worker, name="smf-restore", daemon=True)
                _worker.start()
    except Exception:
        log.exception("[Model Librarian] usage tracking failed")


def on_prompt(json_data):
    """ComfyUI on-prompt handler: never changes or blocks the prompt."""
    try:
        models = models_in_prompt(json_data.get("prompt") or {})
        if models:
            threading.Thread(target=_after_prompt, args=(models,), daemon=True).start()
    except Exception:
        pass
    return json_data


def install() -> None:
    register_folders()
    try:
        from server import PromptServer
        PromptServer.instance.add_on_prompt_handler(on_prompt)
    except Exception:
        log.warning("[Model Librarian] couldn't hook prompts; usage tracking is off")
    threading.Thread(target=retry_cleanup, daemon=True).start()

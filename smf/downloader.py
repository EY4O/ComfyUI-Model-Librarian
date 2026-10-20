"""Background download queue with resume, SHA256 verification and progress."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import time
import uuid
from urllib.parse import urljoin

import aiohttp

from . import basemodel, config, hashing, hfmeta, net, paths, registry, smmeta, sources

PART = ".smf-part"
_STATE = "downloads.json"  # local to this install: these jobs run in this process
_ACTIVE = ("queued", "downloading", "verifying")
_RETRYABLE = ("error", "cancelled", "interrupted")
_jobs: dict[str, dict] = {}
_restored = False
_tasks: dict[str, asyncio.Task] = {}
_sem: asyncio.Semaphore | None = None
_sem_size = 0


class DownloadError(Exception):
    pass


def _semaphore() -> asyncio.Semaphore:
    global _sem, _sem_size
    n = int(config.load().get("max_concurrent", 2))
    if _sem is None or n != _sem_size:
        _sem, _sem_size = asyncio.Semaphore(n), n
    return _sem


def _state_path() -> str:
    return os.path.join(config.local_dir(), _STATE)


def _save() -> None:
    """Remember unfinished downloads so they survive a ComfyUI restart."""
    keep = [{k: v for k, v in j.items() if k != "speed"} for j in _jobs.values() if j["status"] != "done"]
    try:
        tmp = _state_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(keep[-100:], f)
        os.replace(tmp, _state_path())
    except OSError:
        pass


def _restore() -> None:
    global _restored
    if _restored:
        return
    _restored = True
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return
    for j in saved if isinstance(saved, list) else []:
        if not isinstance(j, dict) or not j.get("id") or j["id"] in _jobs:
            continue
        if j.get("status") in _ACTIVE:
            j["status"] = "interrupted"
            j["error"] = "ComfyUI was restarted. Retry resumes the partial download."
        j["speed"] = 0
        _jobs[j["id"]] = j


def jobs() -> list[dict]:
    _restore()
    return sorted((dict(j) for j in _jobs.values()), key=lambda j: j["created"], reverse=True)


def get(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def clear_finished() -> None:
    _restore()
    for k in [k for k, j in _jobs.items() if j["status"] in ("done",) + _RETRYABLE]:
        _jobs.pop(k, None)
    _save()


def retry(job_id: str) -> dict:
    """Start a failed / cancelled / interrupted download again (a partial file resumes)."""
    _restore()
    j = _jobs.get(job_id)
    if not j or j["status"] not in _RETRYABLE:
        raise ValueError("Only failed, cancelled or interrupted downloads can be retried")
    _jobs.pop(job_id, None)
    return start(url=j["url"], folder=j["folder"], rel=j["rel"], sha256=j.get("sha256"), size=j.get("size"),
                 source=j.get("source", "manual"), page_url=j.get("page_url"), title=j.get("title"),
                 meta=j.get("meta"), auto_place=bool(j.get("auto_place")))


def start(*, url: str, folder: str, rel: str, sha256: str | None = None, size: int | None = None,
          source: str = "manual", page_url: str | None = None, title: str | None = None,
          meta: dict | None = None, auto_place: bool = False) -> dict:
    """auto_place: a 'checkpoint' that turns out to be UNet-only (no VAE / text
    encoder inside) is moved to diffusion_models after download."""
    _restore()
    if not (url.startswith("https://") or (os.environ.get("SMF_TEST_ALLOW_HTTP") and url.startswith("http://127.0.0."))):
        raise ValueError("Only https:// downloads are allowed")
    url = net.canonical_download_url(url)
    dest, shared = paths.dest_path(folder, rel)
    for j in _jobs.values():
        if os.path.normcase(j["dest"]) == os.path.normcase(dest) and \
                j["status"] in ("queued", "downloading", "verifying"):
            return j
    jid = uuid.uuid4().hex[:12]
    job = {
        "id": jid, "url": url, "folder": paths.canonical(folder), "rel": paths.safe_rel_path(rel),
        "dest": dest, "shared": shared, "sha256": (sha256 or "").lower() or None, "size": size,
        "source": source, "page_url": page_url, "title": title, "meta": meta,
        "status": "queued", "done": 0, "total": size or 0, "speed": 0, "error": None,
        "created": time.time(), "finished": None, "auto_place": bool(auto_place),
    }
    _jobs[jid] = job
    _save()
    _tasks[jid] = asyncio.ensure_future(_run(job))
    return job


def cancel(job_id: str) -> bool:
    t = _tasks.get(job_id)
    if t and not t.done():
        t.cancel()
        return True
    return False


async def _open(url: str, headers: dict) -> aiohttp.ClientResponse:
    """GET with manual redirects so auth headers never leak to a CDN host."""
    s = net.session()
    cur = url
    for _ in range(10):
        h = dict(headers)
        h.update(net.auth_headers(cur))
        r = await s.get(cur, headers=h, allow_redirects=False)
        if r.status in (301, 302, 303, 307, 308):
            loc = r.headers.get("Location")
            r.release()
            if not loc:
                raise DownloadError("Redirect without Location")
            cur = urljoin(cur, loc)
            continue
        return r
    raise DownloadError("Too many redirects")


def _explain(status: int, url: str, body: str, meta: dict | None = None) -> str:
    if status in (401, 403):
        if net.is_hf(url):
            return ("HuggingFace refused the download (gated or private repo). Accept the model's "
                    "license on its HuggingFace page and add a HuggingFace token in Settings.")
        if net.is_civitai(url):
            meta = meta or {}
            if not config.load().get("civitai_token"):
                return "CivitAI requires an API key for this file. Add your CivitAI API key in Settings."
            if meta.get("access"):  # paid / early access: the key is fine, the version isn't free yet
                return f"CivitAI refused it even with your API key. {meta['access']}."
            mature = (meta.get("nsfwLevel") or 0) >= 4 or meta.get("nsfw")
            return ("CivitAI refused it even with your API key. "
                    + ("It's a mature model: your CivitAI account needs mature content turned on (CivitAI settings). " if mature else "")
                    + "It may also be paid or early access (check the model page), or the key may be expired.")
    if status == 404:
        return "File not found at source (404)."
    return f"HTTP {status}: {body[:200]}"


def _rm(p: str) -> None:
    try:
        os.remove(p)
    except OSError:
        pass


async def _retry(fn, *args, tries: int = 12, delay: float = 0.5):
    for i in range(tries):
        try:
            return fn(*args)
        except PermissionError:
            if i == tries - 1:
                raise
            await asyncio.sleep(delay)


async def _run(job: dict) -> None:
    dest = job["dest"]
    part = dest + PART
    loop = asyncio.get_running_loop()
    hasher = None
    try:
        async with _semaphore():
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if os.path.exists(dest):
                raise DownloadError("A file with this name already exists at the destination")
            job["status"] = "downloading"
            _save()
            # only resume a partial file that came from the same URL
            src_tag = part + ".src"
            if os.path.exists(part):
                try:
                    with open(src_tag, "r", encoding="utf-8") as f:
                        same = json.load(f).get("url") == job["url"]
                except Exception:
                    same = False
                if not same:
                    os.remove(part)
            with open(src_tag, "w", encoding="utf-8") as f:
                json.dump({"url": job["url"]}, f)
            have = os.path.getsize(part) if os.path.exists(part) else 0
            headers = {"Range": f"bytes={have}-"} if have else {}
            r = await _open(job["url"], headers)
            try:
                if r.status == 416 and have:  # already complete
                    job["done"] = job["total"] = have
                elif r.status not in (200, 206):
                    body = (await r.text(errors="replace"))[:500]
                    raise DownloadError(_explain(r.status, job["url"], body, job.get("meta")))
                else:
                    ctype = r.headers.get("Content-Type", "")
                    if ctype.startswith("text/html"):
                        raise DownloadError(_explain(401, job["url"], "", job.get("meta")) if net.is_civitai(job["url"])
                                            else "Source returned a web page instead of a file (login required?)")
                    if r.status == 200 and have:
                        have = 0  # server ignored Range: restart
                    clen = int(r.headers.get("Content-Length") or 0)
                    total = have + clen if clen else (job["size"] or 0)
                    job["total"] = total
                    if total:
                        free = shutil.disk_usage(os.path.dirname(dest)).free
                        if total - have > free:
                            raise DownloadError(f"Not enough disk space: need {(total - have) / 1e9:.1f} GB, "
                                                f"have {free / 1e9:.1f} GB")
                    hasher = hashlib.sha256() if not have else None
                    mode = "ab" if have else "wb"
                    job["done"] = have
                    t0, b0 = time.time(), have
                    with open(part, mode) as f:
                        async for chunk in r.content.iter_chunked(1024 * 1024):
                            await loop.run_in_executor(None, f.write, chunk)
                            if hasher:
                                hasher.update(chunk)
                            job["done"] += len(chunk)
                            dt = time.time() - t0
                            if dt >= 1:
                                job["speed"] = (job["done"] - b0) / dt
                                t0, b0 = time.time(), job["done"]
            finally:
                r.release()

            # verify
            job["status"] = "verifying"
            if hasher is not None and os.path.getsize(part) == job["done"]:
                digest = hasher.hexdigest()
            else:
                digest = await loop.run_in_executor(None, hashing._sha256_sync, part, None)
            if job["sha256"] and digest != job["sha256"]:
                await _retry(os.remove, part)
                _rm(part + ".src")
                raise DownloadError("SHA256 mismatch — the downloaded file is corrupt or different "
                                    "from what the source advertises. Deleted.")
            await _retry(os.replace, part, dest)  # antivirus may still hold the fresh file
            _rm(part + ".src")
            if job.get("auto_place") and job["folder"] == "checkpoints" and _is_unet_only(dest):
                dest = _relocate(job, "diffusion_models")
            hashing.store(dest, digest)
            job["sha256"] = digest

            # bookkeeping
            registry.remember(job["rel"], job["url"], source=job["source"], sha256=digest,
                              size=os.path.getsize(dest), folder=job["folder"], page_url=job["page_url"],
                              title=job["title"])
            cfg = config.load()
            meta = job.get("meta")
            if meta and cfg.get("write_sm_metadata"):
                meta = await sources.with_description(meta)  # the model page's text follows the file
                try:
                    smmeta.write_cm_info(dest, meta)
                except Exception:
                    pass
            if meta and cfg.get("download_previews"):
                await smmeta.download_preview(dest, meta.get("preview"))
            hf = hfmeta.repo_of(job["url"])
            if hf:  # license, tags and model card for the Library; never holds up the download
                asyncio.ensure_future(_hf_details(hf["repo"]))
            paths.invalidate()
            job["status"] = "done"
    except asyncio.CancelledError:
        job["status"] = "cancelled"
        # keep .smf-part so a retry resumes
    except DownloadError as e:
        job["status"], job["error"] = "error", str(e)
    except Exception as e:  # network etc.
        job["status"], job["error"] = "error", f"{type(e).__name__}: {e}"
    finally:
        job["finished"] = time.time()
        job["speed"] = 0
        _tasks.pop(job["id"], None)
        _save()


async def _hf_details(repo: str) -> None:
    try:
        await hfmeta.fetch(repo)
    except Exception:
        pass


# Key prefixes that only exist in an all-in-one checkpoint (VAE / text encoders)
_BUNDLED = ("first_stage_model.", "vae.", "cond_stage_model.", "conditioner.", "text_encoders.",
            "text_encoder.", "text_model.", "clip_l.", "clip_g.", "t5xxl.")


def _is_unet_only(path: str) -> bool:
    if not path.lower().endswith((".safetensors", ".sft")):
        return False
    header = basemodel.read_safetensors_header(path)
    keys = [k for k in (header or {}) if k != "__metadata__"]
    return bool(keys) and not any(k.startswith(_BUNDLED) for k in keys)


def _relocate(job: dict, folder: str) -> str:
    """Move a finished download to another model folder (same relative path)."""
    try:
        new, shared = paths.dest_path(folder, job["rel"])
    except ValueError:
        return job["dest"]
    if os.path.exists(new):
        return job["dest"]
    os.makedirs(os.path.dirname(new), exist_ok=True)
    shutil.move(job["dest"], new)
    job.update(dest=new, folder=folder, shared=shared, relocated=folder)
    return new


# ---------------------------------------------------------------- leftovers
# Partial files other downloaders leave behind, and which app usually writes them.
FOREIGN = {".crdownload": "Chrome / Edge", ".part": "Firefox or a download manager", ".partial": "a download manager",
           ".download": "Safari", ".incomplete": "HuggingFace", ".aria2": "aria2", ".downloading": "a download manager"}
MODEL_EXTS = (".safetensors", ".sft", ".ckpt", ".pt", ".pth", ".bin", ".gguf")
QUIET = 30 * 60  # other apps' files untouched this long aren't still downloading
_trunc_cache: dict[str, list] = {}   # path -> [size, mtime, truncated], kept across restarts
_trunc_loaded = False
_trunc_dirty = False
_TRUNC_FILE = "truncation_cache.json"  # this install's data folder: header checks of big HDD libraries are slow


def _trunc_load() -> None:
    global _trunc_loaded
    if _trunc_loaded:
        return
    _trunc_loaded = True
    try:
        with open(os.path.join(config.local_dir(), _TRUNC_FILE), encoding="utf-8") as f:
            data = json.load(f)
        _trunc_cache.update({k: v for k, v in data.items() if isinstance(v, list) and len(v) == 3})
    except (OSError, ValueError, AttributeError):
        pass


def _trunc_save(seen: set) -> None:
    global _trunc_dirty
    gone = [k for k in _trunc_cache if k not in seen]
    for k in gone:  # files that aren't there any more
        del _trunc_cache[k]
    if not (_trunc_dirty or gone):
        return
    p = os.path.join(config.local_dir(), _TRUNC_FILE)
    try:
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(_trunc_cache, f)
        os.replace(p + ".tmp", p)
        _trunc_dirty = False
    except OSError:
        pass


def truncated(path: str, size: int) -> bool:
    """A .safetensors file shorter than its own header says: an unfinished copy
    (another app's failed download, a full disk). Headers we can't read aren't judged."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
            if len(head) < 8:
                return True
            n = int.from_bytes(head, "little")
            if n <= 1 or n > 100_000_000:
                return False
            if 8 + n > size:
                return True
            hdr = json.loads(f.read(n))
    except (OSError, ValueError, UnicodeDecodeError):
        return False
    if not isinstance(hdr, dict):
        return False
    ends = [v["data_offsets"][1] for k, v in hdr.items()
            if k != "__metadata__" and isinstance(v, dict) and isinstance(v.get("data_offsets"), list) and len(v["data_offsets"]) == 2
            and type(v["data_offsets"][1]) is int]  # (not bool, not null: a header we can't judge)
    return bool(ends) and 8 + n + max(ends) > size


def _truncated_cached(path: str, st) -> bool:
    global _trunc_dirty
    hit = _trunc_cache.get(path)
    if hit and hit[0] == st.st_size and hit[1] == st.st_mtime:
        return hit[2]
    res = truncated(path, st.st_size)
    _trunc_cache[path] = [st.st_size, st.st_mtime, res]
    _trunc_dirty = True
    return res


def _leftover_kind(fn: str) -> tuple[str, str | None] | None:
    low = fn.lower()
    if low.endswith(PART):
        return "partial", None
    if low.endswith(".smf-link"):
        return "leftover", "Model Librarian (hard link)"
    ext = os.path.splitext(low)[1]
    if ext in FOREIGN:
        return "other", FOREIGN[ext]
    if ext == ".tmp" and low[:-4].endswith(MODEL_EXTS):
        return "other", "another app"
    return None


def partials() -> list[dict]:
    """Leftovers from unfinished downloads in the model folders: our .smf-part files
    (ones still behind a retryable download are flagged; active downloads are excluded),
    other apps' partial files, and .safetensors files cut short.
    -> [{path, size, age_days, kind: partial|leftover|other|truncated, app, retryable}]"""
    from . import library  # late import: library imports nothing from here
    _restore()
    active = {os.path.normcase(j["dest"] + PART) for j in _jobs.values() if j["status"] in _ACTIVE}
    active |= {os.path.normcase(j["dest"]) for j in _jobs.values() if j["status"] in _ACTIVE}
    retryable = {os.path.normcase(j["dest"] + PART) for j in _jobs.values() if j["status"] in _RETRYABLE}
    roots = []
    for s in library.SECTIONS:
        roots += library.roots(s)
    out, seen, checked = [], set(), set()
    now = time.time()
    _trunc_load()
    for root in roots:
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if not d.startswith(".")]
            for fn in fns:
                kind = _leftover_kind(fn)
                low = fn.lower()
                if not kind and not low.endswith((".safetensors", ".sft")):
                    continue
                p = os.path.join(dp, fn)
                k = os.path.normcase(os.path.realpath(p))
                if k in seen or os.path.normcase(p) in active:
                    continue
                seen.add(k)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if not kind:
                    checked.add(p)
                    if now - st.st_mtime < QUIET or not _truncated_cached(p, st):
                        continue
                    kind = ("truncated", None)
                elif kind[0] == "other" and now - st.st_mtime < QUIET:
                    continue  # may still be downloading
                out.append({"path": p, "size": st.st_size, "age_days": round((now - st.st_mtime) / 86400, 1),
                            "kind": kind[0], "app": kind[1], "retryable": os.path.normcase(p) in retryable})
    _trunc_save(checked)
    return sorted(out, key=lambda x: -x["size"])


def partials_summary() -> dict:
    items = partials()
    return {"count": len(items), "size": sum(x["size"] for x in items),
            "truncated": sum(1 for x in items if x["kind"] == "truncated"),
            "resumable": sum(1 for x in items if x["retryable"])}


def delete_partials(selected: list[str]) -> dict:
    """Delete leftover files; only paths partials() reports are accepted."""
    allowed = {os.path.normcase(x["path"]): x for x in partials()}
    deleted, freed, errors = 0, 0, []
    for p in selected:
        x = allowed.get(os.path.normcase(str(p)))
        if not x:
            errors.append(f"{os.path.basename(str(p))}: not a leftover partial download")
            continue
        try:
            os.remove(x["path"])
            _rm(x["path"] + ".src")
            deleted += 1
            freed += x["size"]
        except OSError as ex:
            errors.append(f"{os.path.basename(x['path'])}: {ex}")
    for j in [j for j in _jobs.values() if j["status"] in _RETRYABLE and not os.path.exists(j["dest"] + PART)]:
        j["partial_gone"] = True
    _save()
    return {"deleted": deleted, "freed": freed, "errors": errors}

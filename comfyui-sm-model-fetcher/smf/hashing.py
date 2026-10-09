"""SHA256 hashing with an on-disk cache (path + size + mtime).

The cache may live in the shared data folder and be used by several ComfyUI
processes, so:
  * entries are keyed by the file's real path, so a model reached through a
    symlink-mode package and through a yaml-configured one shares one entry;
  * new entries are buffered and merged into the file under a lock (one write
    per batch instead of one rewrite per hash);
  * the in-memory copy is reloaded when another process changed the file.
"""
from __future__ import annotations

import asyncio
import atexit
import functools
import hashlib
import os
import threading
import time

from . import config

_FILE = "hash_cache.json"
_VERSION = 2
_FLUSH_DELAY = 2.0
_RELOAD_EVERY = 3.0

_lock = threading.RLock()
_mem: dict | None = None             # key -> {"size", "mtime", "sha256"}
_mem_dir: str | None = None          # data dir _mem was loaded from
_mem_mtime: float | None = None
_checked = 0.0
_pending: dict[str, dict | None] = {}  # key -> entry, or None = delete
_timer: threading.Timer | None = None


@functools.lru_cache(maxsize=50000)
def _key(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _entries(data) -> dict:
    """Entries from a cache file, upgrading the v1 format (flat dict keyed by abspath)."""
    if not isinstance(data, dict):
        return {}
    if data.get("version") == _VERSION:
        return data.get("entries") or {}
    out = {}
    for p, e in data.items():
        if isinstance(e, dict) and e.get("sha256"):
            out[_key(p)] = e
    return out


def _merge(shared, local) -> dict:
    out = _entries(shared)
    for k, e in _entries(local).items():
        out.setdefault(k, e)
    return {"version": _VERSION, "entries": out}


config.register_merger(_FILE, _merge)


def _file_mtime() -> float | None:
    try:
        return os.path.getmtime(config.data_path(_FILE))
    except OSError:
        return None


def _get_cache() -> dict:
    global _mem, _mem_dir, _mem_mtime, _checked
    with _lock:
        now = time.time()
        d = config.data_dir()
        if _mem is not None and d == _mem_dir and now - _checked < _RELOAD_EVERY:
            return _mem
        _checked = now
        m = _file_mtime()
        if _mem is None or d != _mem_dir or m != _mem_mtime:
            _mem = _entries(config.read_json(_FILE, {}))
            _mem_dir, _mem_mtime = d, m
            for k, e in _pending.items():  # not flushed yet: keep our view
                if e is None:
                    _mem.pop(k, None)
                else:
                    _mem[k] = e
        return _mem


def flush() -> None:
    global _timer, _mem, _mem_mtime, _checked
    with _lock:
        _timer = None
        if not _pending:
            return
        pend = dict(_pending)
        _pending.clear()

        def mut(data):
            entries = _entries(data)
            for k, e in pend.items():
                if e is None:
                    entries.pop(k, None)
                else:
                    entries[k] = e
            data.clear()
            data.update(version=_VERSION, entries=entries)

        try:
            data = config.update_json(_FILE, {}, mut)
        except OSError:
            for k, e in pend.items():  # retry on the next store
                _pending.setdefault(k, e)
            return
        _mem = data["entries"]
        _mem_mtime, _checked = _file_mtime(), time.time()


def _schedule() -> None:
    global _timer
    if len(_pending) >= 200:
        flush()
    elif _timer is None:
        _timer = threading.Timer(_FLUSH_DELAY, flush)
        _timer.daemon = True
        _timer.start()


atexit.register(flush)


def cached(path: str) -> str | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    e = _get_cache().get(_key(path))
    if e and e.get("size") == st.st_size and abs(e.get("mtime", 0) - st.st_mtime) < 1:
        return e["sha256"]
    return None


def find_by_sha(sha256: str) -> str | None:
    """An existing, unchanged file with this SHA256 (full hash or a short prefix
    like CivitAI's AutoV2), from the cache only — nothing is hashed."""
    sha = (sha256 or "").lower()
    if len(sha) < 10:
        return None
    for k, e in list(_get_cache().items()):
        h = (e.get("sha256") or "").lower()
        if h == sha or (len(sha) < 64 and h.startswith(sha)):
            if cached(k) == e.get("sha256"):  # keys are real paths, so they're openable
                return k
    return None


def store(path: str, sha256: str) -> None:
    st = os.stat(path)
    e = {"size": st.st_size, "mtime": st.st_mtime, "sha256": sha256}
    with _lock:
        k = _key(path)
        _get_cache()[k] = e
        _pending[k] = e
        _schedule()


def rename(old: str, new: str) -> None:
    with _lock:
        c = _get_cache()
        ko = _key(old)
        _key.cache_clear()  # the old path no longer exists; don't keep resolving it
        kn = _key(new)
        e = c.pop(ko, None)
        if not e:
            return
        e = dict(e)
        try:
            e["mtime"] = os.stat(new).st_mtime
        except OSError:
            pass
        c[kn] = e
        _pending[ko] = None
        _pending[kn] = e
        _schedule()


def _sha256_sync(path: str, progress=None) -> str:
    h = hashlib.sha256()
    done = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(8 * 1024 * 1024)
            if not b:
                break
            h.update(b)
            done += len(b)
            if progress:
                progress(done)
    return h.hexdigest()


async def sha256_file(path: str, progress=None) -> str:
    hit = cached(path)
    if hit:
        return hit
    loop = asyncio.get_running_loop()
    digest = await loop.run_in_executor(None, _sha256_sync, path, progress)
    store(path, digest)
    return digest

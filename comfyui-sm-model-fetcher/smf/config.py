"""Persistent settings + data directories for SM Model Fetcher.

Two locations:

* local  - ComfyUI's user directory (user/sm_model_fetcher/). Holds API keys
  and the share_data switch, which belong to this ComfyUI install.
* shared - <Stability Matrix Data/Models>/.sm_model_fetcher/. Holds the
  registry, hash cache, undo log and every other setting, so all ComfyUI
  packages in Stability Matrix (and ComfyUI Desktop pointed at the same
  folders) see the same state. Used whenever SM's shared folders are detected
  and share_data is on; otherwise everything stays local.

Several ComfyUI processes may use the shared folder at once, so every
read-modify-write goes through update_json(), which holds a lock file.
"""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager

try:
    import folder_paths  # provided by ComfyUI
except ImportError:  # unit tests
    folder_paths = None

DEFAULTS = {
    "hf_token": "",
    "civitai_token": "",
    "share_data": True,          # keep registry/caches/undo next to SM's shared models
    "vram_gb": 12.0,             # your GPU's VRAM
    "headroom_gb": 1.5,          # VRAM kept free for activations / latents
    "write_sm_metadata": True,   # write .cm-info.json for Stability Matrix
    "download_previews": True,   # save <name>.preview.<ext> next to models
    "auto_check_on_load": True,  # scan every workflow when it's opened
    "auto_check_action": "notify",  # "notify" (corner notice) or "open" (open the window)
    "max_concurrent": 2,
    "nsfw_previews": False,      # allow NSFW preview images
    "blur_nsfw": True,           # blur NSFW cards in the gallery
    "folder_names": {},          # family -> folder name override, e.g. {"SD1.5": "SD15"}
    "extra_rules": [],           # [{"match": "regex", "family": "Illustrious"}] checked first
}
SECRET_KEYS = ("hf_token", "civitai_token")
LOCAL_KEYS = SECRET_KEYS + ("share_data",)  # never written to the shared folder
SHARED_DIRNAME = ".sm_model_fetcher"
_CONFIG = "config.json"
_MIGRATED = "shared_migrated.json"  # local marker: shared dirs this install's data was merged into

_lock = threading.RLock()
_override_dir: str | None = None
_shared_dir: str | None = None
_shared_resolved = False
_mergers: dict = {}  # file name -> fn(shared_data, local_data) -> merged


def set_data_dir(path: str) -> None:
    """Used by tests: one directory for everything, sharing off."""
    global _override_dir
    _override_dir = path
    reset_shared()


def reset_shared() -> None:
    global _shared_dir, _shared_resolved
    _shared_dir, _shared_resolved = None, False


def local_dir() -> str:
    if _override_dir:
        d = _override_dir
    elif folder_paths is not None:
        d = os.path.join(folder_paths.get_user_directory(), "sm_model_fetcher")
    else:
        d = os.path.join(os.path.dirname(__file__), "..", "_data")
    os.makedirs(d, exist_ok=True)
    return d


def _read_path(p: str, default):
    for i in range(5):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default
        except PermissionError:  # Windows: another process is replacing the file
            time.sleep(0.05 * (i + 1))
    return default


def _write_path(p: str, obj) -> None:
    tmp = f"{p}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    for i in range(10):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:  # target open in another process (Windows)
            if i == 9:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            time.sleep(0.05 * (i + 1))


def _local_cfg() -> dict:
    return _read_path(os.path.join(local_dir(), _CONFIG), {})


def shared_dir() -> str | None:
    """<SM Data/Models>/.sm_model_fetcher, or None when not sharing."""
    global _shared_dir, _shared_resolved
    if _shared_resolved:
        return _shared_dir
    d = None
    if not _override_dir and _local_cfg().get("share_data", DEFAULTS["share_data"]):
        d = os.environ.get("SMF_SHARED_DIR") or None
        if not d:
            from . import paths  # late import: paths doesn't depend on config
            root = paths.sm_info().get("models_root")
            d = os.path.join(root, SHARED_DIRNAME) if root else None
        if d:
            try:
                os.makedirs(d, exist_ok=True)
                probe = os.path.join(d, f".probe.{os.getpid()}")
                with open(probe, "w") as f:
                    f.write("ok")
                os.remove(probe)
            except OSError:
                d = None  # read-only or missing drive: fall back to local
    _shared_dir, _shared_resolved = d, True
    return d


def data_dir() -> str:
    return shared_dir() or local_dir()


def data_path(name: str) -> str:
    return os.path.join(data_dir(), name)


def read_json(name: str, default):
    return _read_path(data_path(name), default)


def write_json(name: str, obj) -> None:
    with _lock:
        _write_path(data_path(name), obj)


@contextmanager
def file_lock(path: str, timeout: float = 15.0, stale: float = 30.0):
    """Cross-process lock (a lock file created exclusively). Holders only do a
    quick read-modify-write, so an old lock file is from a crashed process."""
    lock = path + ".lock"
    deadline = time.time() + timeout
    owned = False
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            owned = True
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > stale:
                    os.remove(lock)
                    continue
            except OSError:
                pass
            if time.time() > deadline:
                break  # better a rare lost update than a hung ComfyUI
            time.sleep(0.05)
        except OSError:
            break  # can't create lock files here; proceed unlocked
    try:
        yield
    finally:
        if owned:
            try:
                os.remove(lock)
            except OSError:
                pass


def update_json(name: str, default, fn):
    """Atomically read, mutate (fn(data) edits in place) and write a data file.
    Returns the written data."""
    p = data_path(name)
    with _lock, file_lock(p):
        data = _read_path(p, default)
        fn(data)
        _write_path(p, data)
        return data


# ---------------------------------------------------------------- settings
def load() -> dict:
    cfg = dict(DEFAULTS)
    local = _local_cfg()
    if shared_dir():
        cfg.update({k: v for k, v in read_json(_CONFIG, {}).items() if k not in LOCAL_KEYS})
        cfg.update({k: v for k, v in local.items() if k in LOCAL_KEYS})
    else:
        cfg.update(local)
    # Environment variables win if set (handy for Stability Matrix launch options)
    cfg["hf_token"] = os.environ.get("HF_TOKEN") or cfg["hf_token"]
    cfg["civitai_token"] = os.environ.get("CIVITAI_API_KEY") or cfg["civitai_token"]
    return cfg


CHOICES = {"auto_check_action": ("notify", "open")}


def _coerce(k: str, v):
    default = DEFAULTS[k]
    if k in CHOICES:
        return v if v in CHOICES[k] else default
    if isinstance(default, dict):
        return {str(a): str(b).strip() for a, b in dict(v or {}).items() if str(b).strip()}
    if isinstance(default, list):
        return [dict(match=str(r.get("match", "")), family=str(r.get("family", "")))
                for r in (v or []) if isinstance(r, dict) and r.get("match")]
    if isinstance(default, bool):
        return bool(v)
    try:
        if isinstance(default, float):
            return float(v)
        if isinstance(default, int):
            return max(1, int(v))
    except (TypeError, ValueError):
        raise ValueError(f"{k} must be a number")
    return str(v).strip()


def save(patch: dict) -> dict:
    # file contents, not load(): env-var tokens must never be written to disk
    local = _local_cfg()
    if shared_dir():
        cfg = dict(DEFAULTS)
        cfg.update({k: v for k, v in read_json(_CONFIG, {}).items() if k not in LOCAL_KEYS})
        cfg.update({k: v for k, v in local.items() if k in LOCAL_KEYS})
    else:
        cfg = dict(DEFAULTS, **local)
    for k, v in patch.items():
        if k not in DEFAULTS:
            continue
        if k in SECRET_KEYS and v is None:
            continue  # None = leave unchanged
        cfg[k] = _coerce(k, v)
    with _lock:
        if cfg["share_data"] and shared_dir():
            shared = {k: v for k, v in cfg.items() if k not in LOCAL_KEYS}
            update_json(_CONFIG, {}, lambda d: (d.clear(), d.update(shared)))
            local.update({k: cfg[k] for k in LOCAL_KEYS})
        else:
            local = cfg  # sharing off: this install keeps a full copy of the settings
        _write_path(os.path.join(local_dir(), _CONFIG), local)
        if bool(cfg["share_data"]) != bool(shared_dir()):
            reset_shared()
            # re-enabling: merge whatever was written locally while sharing was off
            migrate_to_shared(force=True)
    return load()


def public(cfg: dict | None = None) -> dict:
    """Config safe to send to the browser: tokens are never returned."""
    cfg = cfg or load()
    out = {k: v for k, v in cfg.items() if k not in SECRET_KEYS}
    for k in SECRET_KEYS:
        out["has_" + k] = bool(cfg.get(k))
    out["data_dir"] = data_dir()
    out["data_shared"] = bool(shared_dir())
    return out


# ---------------------------------------------------------------- migration
def register_merger(name: str, fn) -> None:
    """fn(shared_data or None, local_data) -> merged data to write to the shared file."""
    _mergers[name] = fn


def _merge_config(shared, local):
    if shared:  # another install got there first; its settings win
        return shared
    return {k: v for k, v in local.items() if k not in LOCAL_KEYS}


register_merger(_CONFIG, _merge_config)


def migrate_to_shared(force: bool = False) -> list[str]:
    """Merge this install's local data files into the shared folder (once per
    shared folder). Local files are left in place as a backup."""
    sd = shared_dir()
    if not sd:
        return []
    marker = os.path.join(local_dir(), _MIGRATED)
    done = _read_path(marker, {})
    key = os.path.normcase(os.path.abspath(sd))
    if done.get(key) and not force:
        return []
    merged = []
    for name, fn in _mergers.items():
        src = _read_path(os.path.join(local_dir(), name), None)
        if src is None:
            continue
        p = os.path.join(sd, name)
        with _lock, file_lock(p):
            _write_path(p, fn(_read_path(p, None), src))
        merged.append(name)
    done[key] = time.time()
    _write_path(marker, done)
    return merged

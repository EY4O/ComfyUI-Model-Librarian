"""Storage history: free space on the models drive and the archive drive over
time, and how much the storage tiers moved each day.

A sample per drive is taken at most every 6 hours while ComfyUI runs (any
install sharing the data folder counts), kept for a year in the shared data
folder (storage_history.json). Moves are added up per day and direction.
"""
from __future__ import annotations

import os
import shutil
import threading
import time

from . import config, paths

FILE = "storage_history.json"
EVERY = 6 * 3600
KEEP_DAYS = 365
def _empty() -> dict:
    return {"samples": [], "moves": {}}


def _merge(shared, local):
    out = shared or {"samples": [], "moves": {}}
    seen = {s.get("t") for s in out.get("samples") or []}
    out["samples"] = sorted((out.get("samples") or []) + [s for s in local.get("samples") or [] if s.get("t") not in seen],
                            key=lambda s: s.get("t", 0))
    moves = dict(out.get("moves") or {})
    for day, d in (local.get("moves") or {}).items():
        cur = moves.get(day) or {}
        moves[day] = {k: max(cur.get(k, 0), v) for k, v in {**cur, **d}.items()}
    out["moves"] = moves
    return out


config.register_merger(FILE, _merge)


def _label(path: str) -> str:
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    return drive.upper() if drive else os.path.abspath(path)


def drives() -> list[dict]:
    """The drives worth watching: where the models are, and the archive drive."""
    from . import library, tiering  # late import: tiering imports this module
    out, seen = [], set()
    roots = [paths.sm_info().get("models_root")] + [tiering.ssd_root(s) for s in library.SECTIONS]
    for role, path in [("models", r) for r in roots if r] + [("archive", tiering.archive_dir())]:
        if not path or not os.path.isdir(path):
            continue
        lab = _label(path)
        if lab in seen:
            continue
        seen.add(lab)
        out.append({"label": lab, "role": role, "path": path})
    return out


def sample(force: bool = False, now: float | None = None) -> dict | None:
    """Record free space per drive (at most every EVERY seconds). -> the sample or None."""
    now = now or time.time()
    data = config.read_json(FILE, None) or _empty()
    last = (data.get("samples") or [{}])[-1].get("t", 0) if data.get("samples") else 0
    if not force and now - last < EVERY:
        return None
    added = []
    rec = {"t": now, "drives": {}}
    for d in drives():
        try:
            u = shutil.disk_usage(d["path"])
        except OSError:
            continue
        rec["drives"][d["label"]] = {"role": d["role"], "free": u.free, "total": u.total}
    if not rec["drives"]:
        return None

    def mut(data):
        prev = (data.get("samples") or [{}])[-1].get("t", 0) if data.get("samples") else 0
        if not force and now - prev < EVERY:
            return  # another install (or the background loop) sampled meanwhile
        added.append(rec)
        cut = now - KEEP_DAYS * 86400
        data["samples"] = [s for s in data.get("samples") or [] if s.get("t", 0) >= cut] + [rec]
        data["moves"] = {k: v for k, v in (data.get("moves") or {}).items() if k >= time.strftime("%Y-%m-%d", time.localtime(cut))}

    config.update_json(FILE, _empty(), mut)
    return rec if added else None


def record_move(kind: str, size: int | None, when: float | None = None) -> None:
    """kind: "archived" or "restored"."""
    if kind not in ("archived", "restored"):
        return
    day = time.strftime("%Y-%m-%d", time.localtime(when or time.time()))

    def mut(data):
        d = data.setdefault("moves", {}).setdefault(day, {})
        d[kind] = d.get(kind, 0) + int(size or 0)
        d[kind + "_n"] = d.get(kind + "_n", 0) + 1

    config.update_json(FILE, _empty(), mut)


def history(days: int = 90) -> dict:
    data = config.read_json(FILE, None) or _empty()
    cut = time.time() - days * 86400
    day_cut = time.strftime("%Y-%m-%d", time.localtime(cut))
    goal = float(config.load().get("free_goal_gb") or 0) * 1024 ** 3
    return {"samples": [s for s in data.get("samples") or [] if s.get("t", 0) >= cut],
            "moves": [{"day": k, **v} for k, v in sorted((data.get("moves") or {}).items()) if k >= day_cut],
            "drives": [{k: d[k] for k in ("label", "role")} for d in drives()],
            "goal": goal or None, "days": days, "now": time.time()}


def _loop() -> None:
    while True:
        try:
            sample()
        except Exception:
            pass
        time.sleep(3600)


_started = False


def start() -> None:
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="smf-storage-history").start()

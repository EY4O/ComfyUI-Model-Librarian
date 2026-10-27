"""Install (or update) Model Librarian into one or more ComfyUI installs.

    python tools/install.py <ComfyUI dir or custom_nodes dir> [more targets...] [--force] [--dry-run]

Examples:
    python tools/install.py "%LOCALAPPDATA%/Comfy-Desktop/ComfyUI-Installs/ComfyUI"
    python tools/install.py "C:/StabilityMatrix/Data/Packages/ComfyUI"

The project folder is the single source of truth. Each install gets a
.smf-install.json manifest (SHA256 of every file installed). If an installed
copy was edited in place since then, the update stops and lists the changed
files, so fixes made directly in an install are never silently overwritten;
copy them into the project first, or pass --force (the old copy is backed up
to backups/ either way; the newest few backups of each install are kept).
Restart ComfyUI afterwards.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = REPO  # the repo root is the extension (as ComfyUI-Manager / the registry install it)
NAME = "comfyui-model-librarian"
# What an install needs; tests/, tools/, docs/ stay in the repo
INCLUDE = ("__init__.py", "pyproject.toml", "README.md", "LICENSE", "js", "smf")
LEGACY_NAMES = ("comfyui-sm-model-fetcher",)  # earlier name: retired on install (both would load)
MANIFEST = ".smf-install.json"
SKIP_DIRS = {"__pycache__", "_data"}
# ComfyUI-Manager's record of a registry install: kept, so Manager can still update it
KEEP = (".tracking",)
KEEP_BACKUPS = 5  # per install folder name; older ones are removed after an update


def files(root: str, only=None) -> dict[str, str]:
    """SHA256 of every file under root (only: limit to these top-level entries)."""
    out = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        if only is not None and os.path.normpath(dp) == os.path.normpath(root):
            dns[:] = [d for d in dns if d in only]
            fns = [f for f in fns if f in only]
        for fn in fns:
            if fn == MANIFEST or fn.endswith(".pyc") or (fn in KEEP and os.path.normpath(dp) == os.path.normpath(root)):
                continue
            p = os.path.join(dp, fn)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root).replace("\\", "/")] = hashlib.sha256(f.read()).hexdigest()
    return out


def write_manifest(dest: str, src_files: dict) -> None:
    with open(os.path.join(dest, MANIFEST), "w", encoding="utf-8") as f:
        json.dump({"installed": time.strftime("%Y-%m-%d %H:%M:%S"), "source": SRC, "files": src_files}, f, indent=1)


def custom_nodes_dir(target: str) -> str:
    t = os.path.abspath(os.path.expandvars(os.path.expanduser(target)))
    if os.path.basename(t).lower() == "custom_nodes":
        return t
    for cand in (os.path.join(t, "custom_nodes"), os.path.join(t, "ComfyUI", "custom_nodes")):
        if os.path.isdir(cand):
            return cand  # ComfyUI Desktop nests the app one level down
    raise SystemExit(f"No custom_nodes folder found under {t}")


def diff(a: dict, b: dict) -> list[str]:
    return sorted([f"changed  {k}" for k in a.keys() & b.keys() if a[k] != b[k]] +
                  [f"added    {k}" for k in b.keys() - a.keys()] +
                  [f"removed  {k}" for k in a.keys() - b.keys()])


def _manifest_files(folder: str):
    try:
        with open(os.path.join(folder, MANIFEST), encoding="utf-8") as f:
            return json.load(f)["files"]
    except (OSError, ValueError, KeyError):
        return None


def retire_legacy(cn: str, force: bool, dry: bool) -> bool:
    """Back up and remove a copy installed under an earlier name."""
    for old in LEGACY_NAMES:
        path = os.path.join(cn, old)
        if not os.path.isdir(path):
            continue
        installed = _manifest_files(path)
        edits = diff(installed, files(path)) if installed is not None else None
        print(f"  found the earlier install {old}/ (would load alongside the new one)")
        if (edits or edits is None) and not force:
            what = "was edited since it was installed:" if edits else "has no install manifest (installed by hand?)"
            print(f"  ! {old}/ {what}")
            for line in edits or []:
                print("     ", line)
            print("  Not updated. Copy any fixes into the project, or pass --force (it's backed up first).")
            return False
        backup = _backup_path(f"{old}-{os.path.basename(os.path.dirname(cn.rstrip(os.sep)))}")
        if dry:
            print(f"  would back it up to {backup} and remove it")
            continue
        shutil.copytree(path, backup, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.rmtree(path)
        print(f"  retired it (backup: {backup})")
    return True


def install(target: str, force: bool, dry: bool) -> bool:
    cn = custom_nodes_dir(target)
    dest = os.path.join(cn, NAME)
    src_files = files(SRC, INCLUDE)
    print(f"\n→ {dest}")
    if not retire_legacy(cn, force, dry):
        return False
    kept = {}
    if os.path.isdir(dest):
        cur = files(dest)
        if cur == src_files:
            if not dry and not os.path.isfile(os.path.join(dest, MANIFEST)):
                write_manifest(dest, src_files)
            print("  already up to date")
            return True
        try:
            with open(os.path.join(dest, MANIFEST), encoding="utf-8") as f:
                installed = json.load(f)["files"]
        except (OSError, ValueError, KeyError):
            installed = None
        edits = diff(installed, cur) if installed is not None else None
        if edits or edits is None:
            what = "was edited since it was installed" if edits else "has no install manifest (installed by hand?)"
            print(f"  ! the installed copy {what}:")
            for line in (edits or diff(src_files, cur)):
                print("     ", line)
            if not force:
                print("  Not updated. Copy any fixes you want to keep into the project, then re-run "
                      "(or pass --force to replace it; it's backed up first).")
                return False
        backup_name = os.path.basename(os.path.dirname(cn.rstrip(os.sep)))
        backup = _backup_path(backup_name)
        if dry:
            print(f"  would back up to {backup} and update {len(diff(cur, src_files))} file(s)")
            return True
        shutil.copytree(dest, backup, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        print(f"  backed up the old copy to {backup}")
        pruned = prune_backups(backup_name)
        if pruned:
            print(f"  removed {pruned} older backup(s) of this install (keeps the newest {KEEP_BACKUPS})")
        kept ={k: open(os.path.join(dest, k), "rb").read() for k in KEEP if os.path.isfile(os.path.join(dest, k))}
        shutil.rmtree(dest)
    elif dry:
        print(f"  would install {len(src_files)} file(s)")
        return True
    os.makedirs(dest)
    for item in INCLUDE:
        a, b = os.path.join(SRC, item), os.path.join(dest, item)
        if os.path.isdir(a):
            shutil.copytree(a, b, ignore=shutil.ignore_patterns(*SKIP_DIRS, "*.pyc"))
        elif os.path.isfile(a):
            shutil.copy2(a, b)
    if files(dest) != src_files:
        print("  ! verification failed: installed files differ from the project")
        return False
    write_manifest(dest, src_files)
    for k, data in kept.items():
        with open(os.path.join(dest, k), "wb") as f:
            f.write(data)
    print(f"  installed {len(src_files)} file(s), verified. Restart this ComfyUI to load it.")
    return True


def _backup_path(name: str) -> str:
    """backups/<name>-<time>, numbered when two installs share a folder name (E:/A/ComfyUI and E:/B/ComfyUI)."""
    base = os.path.join(REPO, "backups", f"{name}-{time.strftime('%Y%m%d-%H%M%S')}")
    path, n = base, 2
    while os.path.exists(path):
        path, n = f"{base}-{n}", n + 1
    return path


def prune_backups(name: str, keep: int = KEEP_BACKUPS) -> int:
    """Remove all but the newest `keep` backups/<name>-<time>[-n] folders; anything else in backups/ is left alone."""
    root = os.path.join(REPO, "backups")
    pat = re.compile(re.escape(name) + r"-(\d{8}-\d{6})(?:-(\d+))?")
    found = []
    for d in os.listdir(root) if os.path.isdir(root) else []:
        m = pat.fullmatch(d)
        if m and os.path.isdir(os.path.join(root, d)):
            found.append(((m.group(1), int(m.group(2) or 1)), d))
    found.sort(reverse=True)
    for _, d in found[keep:]:
        shutil.rmtree(os.path.join(root, d))
    return max(0, len(found) - keep)


def main():
    for stream in (sys.stdout, sys.stderr):  # a cp1252 console can't print the arrows below
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("targets", nargs="+", help="ComfyUI folder(s) or custom_nodes folder(s)")
    ap.add_argument("--force", action="store_true", help="replace an installed copy even if it was edited")
    ap.add_argument("--dry-run", action="store_true", help="show what would happen")
    a = ap.parse_args()
    ok = all([install(t, a.force, a.dry_run) for t in a.targets])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

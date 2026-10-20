"""Archive: a folder of generated images -> what made each one, consolidated.

Scans a folder (and its subfolders), reads the generation data of every image
and video with the recipe readers, and writes `_ml_archive/` inside it:

  report.md      prompt families -> variants -> one row per image (seed, model, what differs)
  images.csv     one row per image, every field
  recipes.jsonl  the recipe of every image (shared recipe/1 format, without the workflow)
  workflows/     one ComfyUI workflow per prompt variant
  thumbs/        a small WebP per image (a video's first frame) that carries its own workflow, prompt and recipe:
                 drop one on ComfyUI to get that exact image's workflow back
  index.json     what was read, so a re-run only reads new or changed files

Prompts that differ only by a few words are grouped into one family (the
variant with most images is its base; the others show what changed).
Nothing in the scanned folder is changed outside `_ml_archive/`, unless the
originals are moved to another drive (move_originals: logged in moves/, undoable).
"""
from __future__ import annotations

import concurrent.futures
import csv
import difflib
import hashlib
import io
import json
import os
import re
import threading
import time

from . import imagemeta, recipe_parse

OUT = "_ml_archive"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_EXTS = (".mp4", ".webm", ".mov", ".mkv")
THUMB_PX = 512
WORKERS = 4
SIMILARITY = {"exact": 1.01, "similar": 0.8, "loose": 0.65}
FIELDS = ("seed", "model", "sampler", "scheduler", "steps", "cfg", "size", "denoise", "loras", "negative")

_job: dict = {"status": "idle"}
_lock = threading.Lock()


# ---------------------------------------------------------------- reading one file
def _slim(rec: dict) -> dict:
    """What the archive keeps of a recipe (the ComfyUI graph goes into the thumbnail and workflows/)."""
    s = rec.get("settings") or {}
    m = rec.get("model") or {}
    return {
        "prompt": (rec.get("prompt") or {}).get("positive") or "",
        "negative": (rec.get("prompt") or {}).get("negative") or "",
        "seed": s.get("seed"), "steps": s.get("steps"), "cfg": s.get("cfg"),
        "sampler": s.get("sampler_raw") or s.get("sampler"), "scheduler": s.get("scheduler"),
        "width": s.get("width"), "height": s.get("height"), "denoise": s.get("denoise"),
        "model": m.get("name") or m.get("file"), "model_file": m.get("file"), "model_hash": m.get("hash"),
        "loras": [{"name": l.get("name") or l.get("file"), "file": l.get("file"), "weight": l.get("weight"), "hash": l.get("hash")}
                  for l in rec.get("loras") or []],
        "vae": (rec.get("vae") or {}).get("name") or (rec.get("vae") or {}).get("file"),
        "base_model": rec.get("base_model"), "format": rec.get("format"),
    }


def _ascii_json(raw: str) -> str:
    try:
        return json.dumps(json.loads(raw), separators=(",", ":"))
    except ValueError:
        return raw.encode("ascii", "backslashreplace").decode("ascii")


def _video_frame(path: str):
    """The first frame of a video as a PIL image (PyAV, which ComfyUI ships). None without PyAV."""
    try:
        import av
    except ImportError:
        return None
    with av.open(path) as c:
        for frame in c.decode(video=0):
            return frame.to_image()
    raise ValueError("no video frames")


def _thumb(src, meta: dict, rec: dict | None, dest: str, embed: bool) -> int:
    """512 px WebP of the image (bytes) or video frame (PIL image), carrying its workflow, prompt,
    recipe and A1111 text. -> bytes written."""
    from PIL import Image, ImageOps
    with (Image.open(io.BytesIO(src)) if isinstance(src, (bytes, bytearray)) else src) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((THUMB_PX, THUMB_PX))
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        ex = Image.Exif()
        if embed:
            # what ComfyUI reads back from a WebP's EXIF (drag it onto the canvas), and Model Librarian / Prompto.
            # EXIF text is ASCII: JSON escapes everything else, as ComfyUI's own WebP saves do.
            if meta.get("workflow"):
                ex[0x010F] = "workflow:" + _ascii_json(meta["workflow"])
            if meta.get("prompt"):
                ex[0x0110] = "prompt:" + _ascii_json(meta["prompt"])
            if rec:
                r = {k: v for k, v in rec.items() if k != "comfy"}
                ex[0x010E] = "recipe:" + json.dumps(r, separators=(",", ":"))
            params = meta.get("parameters") or meta.get("UserComment")
            if params:
                ex.get_ifd(0x8769)[0x9286] = b"UNICODE\0" + params.encode("utf-16-be")
        tmp = dest + f".{threading.get_ident()}.tmp"
        im.save(tmp, "WEBP", quality=80, method=4, exif=ex.tobytes() if len(ex) or ex.get_ifd(0x8769) else b"")
    os.replace(tmp, dest)
    return os.path.getsize(dest)


def read_file(path: str, rel: str, out_dir: str, thumbs: bool, embed: bool) -> dict:
    """One image or video -> its archive entry."""
    st = os.stat(path)
    e = {"file": rel, "size": st.st_size, "mtime": st.st_mtime, "video": rel.lower().endswith(VIDEO_EXTS)}
    meta, rec, data = {}, None, None
    try:
        if e["video"]:
            rec = recipe_parse.from_video(path, os.path.basename(path))
            from . import videometa
            meta = videometa.read(path).get("text") or {}
        else:
            with open(path, "rb") as f:
                data = f.read()
            meta = imagemeta.read(data).get("text") or {}
            rec = recipe_parse.from_text(meta)
    except recipe_parse.NoMetadata:
        e["error"] = "no generation data"
    except Exception as ex:
        e["error"] = f"couldn't read it: {ex}"
    if rec:
        rec = recipe_parse.clean(rec)
        e.update(_slim(rec))
        e["recipe"] = {k: v for k, v in rec.items() if k != "comfy"}
        wf = (rec.get("comfy") or {}).get("workflow") or ((rec.get("comfy") or {}).get("prompt") if rec.get("comfy") else None)
        if wf:
            e["workflow_kind"] = "workflow" if (rec.get("comfy") or {}).get("workflow") else "api"
            e["_workflow"] = wf
    if thumbs and (data is not None or e["video"]):
        name = _thumb_name(rel)
        try:
            src = data if data is not None else _video_frame(path)
            if src is None:
                e["thumb_error"] = "PyAV isn't installed"
            else:
                e["thumb_bytes"] = _thumb(src, meta, e.get("recipe"), os.path.join(out_dir, "thumbs", name), embed)
                e["thumb"] = name
        except Exception as ex:
            e["thumb_error"] = str(ex)
    return e


def _thumb_name(rel: str) -> str:
    return hashlib.sha1(rel.replace("\\", "/").lower().encode()).hexdigest()[:16] + ".webp"


# ---------------------------------------------------------------- grouping
_LORA_TAG = re.compile(r"<lora:[^>]+>", re.I)
_WEIGHT = re.compile(r"\(([^():]+):[-\d.]+\)")


def norm_prompt(p: str) -> str:
    p = _LORA_TAG.sub("", p or "")
    p = _WEIGHT.sub(r"\1", p)
    return re.sub(r"\s+", " ", p).strip().lower()


def phrases(p: str) -> list[str]:
    return [x.strip(" .") for x in re.split(r"[,\n;]|\.\s", norm_prompt(p)) if x.strip(" .")]


def similarity(a: str, b: str) -> float:
    """0..1: how much two prompts share, by phrase (tag lists) or by word (prose)."""
    pa, pb = set(phrases(a)), set(phrases(b))
    jac = len(pa & pb) / len(pa | pb) if pa | pb else 1.0
    wa, wb = norm_prompt(a).split(), norm_prompt(b).split()
    sm = difflib.SequenceMatcher(None, wa, wb, autojunk=False)
    if sm.real_quick_ratio() < 0.5 or sm.quick_ratio() < 0.5:
        return jac
    return max(jac, sm.ratio())


def _word_ops(a: str, b: str, out: dict) -> None:
    wa, wb = a.split(), b.split()
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_opcodes():
        if op == "insert":
            out["added"].append(" ".join(wb[j1:j2]))
        elif op == "delete":
            out["removed"].append(" ".join(wa[i1:i2]))
        elif op == "replace":
            out["replaced"].append([" ".join(wa[i1:i2]), " ".join(wb[j1:j2])])


def diff(base: str, other: str) -> dict:
    """What a variant changes compared to its family's base prompt: phrases added or removed
    (tag-style prompts), and inside a phrase that was only edited, just the words that changed."""
    out = {"added": [], "removed": [], "replaced": []}
    pa, pb = phrases(base), phrases(other)
    if len(pa) >= 3 and len(pb) >= 3:
        sa, sb = set(pa), set(pb)
        added, removed = [x for x in pb if x not in sa], [x for x in pa if x not in sb]
        for r in list(removed):  # a long phrase with a couple of words changed: show just those words
            score = lambda a: difflib.SequenceMatcher(None, r.split(), a.split(), autojunk=False).ratio()
            best = max(added, key=score, default=None)
            if best is not None and score(best) >= 0.5:
                _word_ops(r, best, out)
                added.remove(best)
                removed.remove(r)
        out["added"] = added + out["added"]
        out["removed"] = removed + out["removed"]
        return out
    _word_ops(norm_prompt(base), norm_prompt(other), out)
    return out


def _value(e: dict, field: str):
    if field == "size":
        return f"{e.get('width')}×{e.get('height')}" if e.get("width") else None
    if field == "loras":
        return "; ".join(f"{l['name']}:{l['weight']}" for l in e.get("loras") or []) or None
    return e.get(field)


def group(entries: list[dict], mode: str = "similar") -> list[dict]:
    """Images with metadata -> [{id, base, count, variants: [{id, prompt, count, diff, shared, varying, images}]}]."""
    exact: dict[str, list] = {}
    for e in entries:
        exact.setdefault(norm_prompt(e.get("prompt", "")), []).append(e)
    groups = sorted(exact.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    threshold = SIMILARITY.get(mode, 0.8)
    families: list[dict] = []
    by_word: dict[str, list[int]] = {}  # word -> families whose base prompt has it
    for key, imgs in groups:
        prompt = imgs[0].get("prompt", "")
        words = set(key.split())
        home = None
        if threshold <= 1 and words:
            hits: dict[int, int] = {}
            for w in words:
                for fi in by_word.get(w, ()):
                    hits[fi] = hits.get(fi, 0) + 1
            best = 0.0
            for fi, n in hits.items():
                f = families[fi]
                # shared words / all words caps how similar two prompts can be: skip hopeless pairs
                if n / len(words | f["words"]) < threshold - 0.2:
                    continue
                s = similarity(f["base"], prompt)
                if s >= threshold and s > best:
                    home, best = f, s
        if home is None:
            home = {"base": prompt, "variants": [], "words": words}
            for w in words:
                by_word.setdefault(w, []).append(len(families))
            families.append(home)
        home["variants"].append({"prompt": prompt, "images": imgs})
    out = []
    for fi, f in enumerate(sorted(families, key=lambda f: -sum(len(v["images"]) for v in f["variants"])), 1):
        variants = []
        for vi, v in enumerate(f["variants"], 1):
            imgs = sorted(v["images"], key=lambda e: e["file"].lower())
            shared, varying = {}, []
            for field in FIELDS:
                vals = {json.dumps(_value(e, field), sort_keys=True, default=str) for e in imgs}
                if len(vals) == 1:
                    val = _value(imgs[0], field)
                    if val not in (None, ""):
                        shared[field] = val
                else:
                    varying.append(field)
            variants.append({"id": f"f{fi:03d}-v{vi}", "prompt": v["prompt"], "count": len(imgs),
                             "diff": None if vi == 1 else diff(f["base"], v["prompt"]),
                             "shared": shared, "varying": varying, "images": imgs})
        out.append({"id": f"f{fi:03d}", "base": f["base"], "count": sum(v["count"] for v in variants), "variants": variants})
    return out


# ---------------------------------------------------------------- writing
def _size(mb: float) -> str:
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB" if mb >= 10 else f"{mb:.1f} MB" if mb >= 1 else f"{mb * 1024:.0f} KB"


def _md_escape(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _fmt_diff(d: dict) -> str:
    bits = [f"`+ {x}`" for x in d["added"]] + [f"`− {x}`" for x in d["removed"]] + [f"`{a}` → `{b}`" for a, b in d["replaced"]]
    return " ".join(bits) or "same words, different order or punctuation"


def write_report(folder: str, out_dir: str, families: list[dict], no_meta: list[dict], stats: dict) -> None:
    name = os.path.basename(folder.rstrip("/\\")) or folder
    L = [f"# Image archive: {name}", "",
         f"Made by Model Librarian on {time.strftime('%Y-%m-%d %H:%M')} from `{folder}`.", "",
         f"- **{stats['images']}** images · **{stats['with_meta']}** with generation data · "
         f"**{len(families)}** prompt families · **{stats['variants']}** prompt variants · **{len(no_meta)}** without data",
         f"- Originals: {_size(stats['original_mb'])} · this archive: {_size(stats['archive_mb'])}", "",
         "Each thumbnail in `thumbs/` carries its image's workflow: drop it onto ComfyUI to load it, seed included.", ""]
    for f in families:
        L += ["---", "", f"## {f['id']} · {f['count']} image{'s' if f['count'] != 1 else ''} · {len(f['variants'])} variant{'s' if len(f['variants']) != 1 else ''}", "",
              "```text", f["base"].strip() or "(empty prompt)", "```", ""]
        for v in f["variants"]:
            title = "Base prompt" if v["diff"] is None else _fmt_diff(v["diff"])
            L += [f"### {v['id']} · {v['count']} image{'s' if v['count'] != 1 else ''} · {title}", ""]
            if v["shared"]:
                L.append("Shared: " + " · ".join(f"**{k}** {_md_escape(val)}" for k, val in v["shared"].items()))
                L.append("")
            wf = next((e for e in v["images"] if e.get("_workflow")), None)
            if wf:
                L += [f"Workflow: [`workflows/{v['id']}.json`](workflows/{v['id']}.json)", ""]
            cols = ["", "File"] + [c for c in v["varying"] if c != "negative"] + (["negative"] if "negative" in v["varying"] else [])
            L.append("| " + " | ".join(cols) + " |")
            L.append("|" + "---|" * len(cols))
            for e in v["images"]:
                thumb = f'<img src="thumbs/{e["thumb"]}" width="96">' if e.get("thumb") else ""
                row = [thumb, f"`{_md_escape(e['file'])}`"] + [_md_escape(_value(e, c) if _value(e, c) is not None else "") for c in cols[2:]]
                L.append("| " + " | ".join(row) + " |")
            L.append("")
    if no_meta:
        L += ["---", "", f"## Without generation data ({len(no_meta)})", ""]
        L += [f"- `{_md_escape(e['file'])}` — {e.get('error', '')}" for e in no_meta]
        L.append("")
    _atomic(os.path.join(out_dir, "report.md"), "\n".join(L))


CSV_COLS = ["file", "family", "variant", "prompt", "negative", "seed", "model", "model_hash", "loras", "sampler", "scheduler",
            "steps", "cfg", "width", "height", "denoise", "vae", "format", "date", "thumb", "workflow"]


def write_tables(out_dir: str, families: list[dict], no_meta: list[dict]) -> None:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLS)
    lines = []
    for f in families:
        for v in f["variants"]:
            for e in v["images"]:
                w.writerow([e["file"], f["id"], v["id"], e.get("prompt"), e.get("negative"), e.get("seed"), e.get("model"), e.get("model_hash"),
                            _value(e, "loras"), e.get("sampler"), e.get("scheduler"), e.get("steps"), e.get("cfg"), e.get("width"), e.get("height"),
                            e.get("denoise"), e.get("vae"), e.get("format"), time.strftime("%Y-%m-%d %H:%M", time.localtime(e["mtime"])),
                            e.get("thumb") and f"thumbs/{e['thumb']}", f"workflows/{v['id']}.json" if any(x.get("_workflow") for x in v["images"]) else ""])
                lines.append(json.dumps({"file": e["file"], "family": f["id"], "variant": v["id"], "thumb": e.get("thumb"),
                                         "recipe": e.get("recipe")}, ensure_ascii=False))
    for e in no_meta:
        w.writerow([e["file"]] + [""] * (len(CSV_COLS) - 1))
    _atomic(os.path.join(out_dir, "images.csv"), "\ufeff" + buf.getvalue())  # BOM: Excel opens it as UTF-8
    _atomic(os.path.join(out_dir, "recipes.jsonl"), "\n".join(lines) + ("\n" if lines else ""))
    wdir = os.path.join(out_dir, "workflows")
    os.makedirs(wdir, exist_ok=True)
    keep = set()
    for f in families:
        for v in f["variants"]:
            e = next((x for x in v["images"] if x.get("_workflow")), None)
            if e:
                name = f"{v['id']}.json"
                keep.add(name)
                _atomic(os.path.join(wdir, name), json.dumps(e["_workflow"], ensure_ascii=False))
    for old in os.listdir(wdir):  # ids shift between runs: drop files no variant uses any more
        if old.endswith(".json") and old not in keep:
            os.remove(os.path.join(wdir, old))


def _atomic(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


# ---------------------------------------------------------------- the job
def _walk(folder: str, recursive: bool):
    for dp, dns, fns in os.walk(folder):
        dns[:] = sorted(d for d in dns if d != OUT and not d.startswith(".")) if recursive else []
        for fn in sorted(fns):
            if fn.lower().endswith(IMAGE_EXTS + VIDEO_EXTS):
                p = os.path.join(dp, fn)
                yield p, os.path.relpath(p, folder).replace("\\", "/")


def _reachable(path: str) -> bool:
    """Is the drive (or network share) the path is on there at all?"""
    anchor = os.path.splitdrive(os.path.abspath(path))[0]
    return bool(anchor) and os.path.exists(anchor + os.sep)


def _moved_key(index: dict, rel: str) -> str:
    key, n = f"{rel}#moved", 2
    while key in index:
        key, n = f"{rel}#moved{n}", n + 1
    return key


def _rekey_thumb(e: dict, key: str, out_dir: str) -> dict:
    """The entry under a new index key, its thumbnail renamed to match (thumb names come from the key)."""
    e = dict(e)
    if e.get("thumb"):
        new = _thumb_name(key)
        try:
            os.replace(os.path.join(out_dir, "thumbs", e["thumb"]), os.path.join(out_dir, "thumbs", new))
            e["thumb"] = new
        except OSError:
            pass
    return e


def _load_index(out_dir: str) -> dict:
    try:
        with open(os.path.join(out_dir, "index.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d.get("files") or {}
    except (OSError, ValueError):
        return {}


def _save_index(out_dir: str, files: dict, opts: dict) -> None:
    _atomic(os.path.join(out_dir, "index.json"), json.dumps({"version": 1, "options": opts, "files": files}, ensure_ascii=False))


def run(folder: str, recursive: bool = True, thumbs: bool = True, embed: bool = True, mode: str = "similar",
        progress=None, cancelled=lambda: False) -> dict:
    """Scan `folder` and (re)write its archive. -> summary."""
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        raise ValueError(f"Not a folder: {folder}")
    out_dir = os.path.join(folder, OUT)
    os.makedirs(os.path.join(out_dir, "thumbs"), exist_ok=True)
    opts = {"recursive": recursive, "thumbs": thumbs, "embed": embed}
    old = _load_index(out_dir)
    files = list(_walk(folder, recursive))
    report = progress or (lambda **kw: None)
    report(phase="reading", total=len(files), done=0)
    index, todo = {}, []
    for p, rel in files:
        prev = old.get(rel)
        try:
            st = os.stat(p)
        except OSError:
            continue
        if prev and prev.get("moved") and (prev.get("size") != st.st_size or prev.get("mtime") != st.st_mtime) \
                and (os.path.isfile(prev["moved"]) or not _reachable(prev["moved"])):
            # a new file took a moved original's name (ComfyUI numbers saves again once the folder is emptier):
            # the original keeps its own entry and thumbnail
            key = _moved_key(old, rel)
            old[key] = _rekey_thumb(prev, key, out_dir)
            prev = None
        thumb_ok = not thumbs or (prev or {}).get("thumb") or (prev or {}).get("thumb_error") or (prev or {}).get("error")
        if prev and prev.get("size") == st.st_size and prev.get("mtime") == st.st_mtime and prev.get("opts_embed") == embed and thumb_ok:
            index[rel] = {k: v for k, v in prev.items() if k != "moved"}  # back in place (a move was undone)
        else:
            todo.append((p, rel))
    # originals moved to another drive (move_originals) stay in the archive while they're there, and
    # while that drive isn't connected (they're only dropped once the drive is there and the file isn't)
    for rel, prev in list(old.items()):
        if rel not in index and prev.get("moved") and (os.path.isfile(prev["moved"]) or not _reachable(prev["moved"])):
            index[rel] = prev
            files.append((prev["moved"], rel))
    done = len(files) - len(todo)
    report(done=done, reused=done)
    wf_cache: dict[str, object] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(read_file, p, rel, out_dir, thumbs, embed): rel for p, rel in todo}
        for i, fut in enumerate(concurrent.futures.as_completed(futs)):
            if cancelled():
                for f in futs:
                    f.cancel()
                break
            rel = futs[fut]
            try:
                e = fut.result()
            except Exception as ex:
                e = {"file": rel, "size": 0, "mtime": 0, "error": f"couldn't read it: {ex}"}
            e["opts_embed"] = embed
            wf = e.pop("_workflow", None)
            if wf is not None:
                wf_cache[rel] = wf
                e["has_workflow"] = True
            index[rel] = e
            done += 1
            if i % 25 == 0:
                report(done=done, current=rel)
            if i and i % 500 == 0:
                _save_index(out_dir, index, opts)  # a cancelled or crashed run resumes from here
    _save_index(out_dir, index, opts)
    if cancelled():
        return {"cancelled": True, "done": done, "total": len(files)}
    report(phase="grouping", current=None)
    present = {rel for _, rel in files}
    entries = [dict(e) for rel, e in index.items() if rel in present]
    for e in entries:
        if e.get("has_workflow") and e["file"] in wf_cache:
            e["_workflow"] = wf_cache[e["file"]]
    with_meta = [e for e in entries if not e.get("error")]
    no_meta = sorted((e for e in entries if e.get("error")), key=lambda e: e["file"].lower())
    _workflows_for(folder, with_meta, wf_cache)
    families = group(with_meta, mode)
    # thumbnails of files that are gone
    used = {e.get("thumb") for e in entries}
    tdir = os.path.join(out_dir, "thumbs")
    for name in os.listdir(tdir):
        if name.endswith(".webp") and name not in used:
            os.remove(os.path.join(tdir, name))
    report(phase="writing")
    stats = {"images": len(entries), "with_meta": len(with_meta), "variants": sum(len(f["variants"]) for f in families),
             "original_mb": sum(e.get("size", 0) for e in entries) / 1024 ** 2, "moved": sum(1 for e in entries if e.get("moved"))}
    write_tables(out_dir, families, no_meta)
    stats["archive_mb"] = sum(os.path.getsize(os.path.join(dp, fn)) for dp, _, fns in os.walk(out_dir) for fn in fns) / 1024 ** 2
    write_report(folder, out_dir, families, no_meta, stats)
    summary = {"folder": folder, "out_dir": out_dir, **stats, "families": len(families), "no_meta": len(no_meta),
               "top": [{"id": f["id"], "base": f["base"][:300], "count": f["count"], "variants": len(f["variants"]),
                        "thumbs": [e["thumb"] for v in f["variants"] for e in v["images"] if e.get("thumb")][:6],
                        "files": [e["file"] for v in f["variants"] for e in v["images"] if e.get("thumb")][:6]}
                       for f in families[:60]],
               "finished": time.time()}
    _atomic(os.path.join(out_dir, "summary.json"), json.dumps(summary, ensure_ascii=False))
    return summary


def _workflows_for(folder: str, entries: list[dict], cache: dict) -> None:
    """Re-reads the workflow of reused files for the variants that need one (first image of each)."""
    # cheap: only files with a workflow whose graph wasn't read this run, and only one per prompt
    seen = set()
    for e in entries:
        key = norm_prompt(e.get("prompt", ""))
        if not e.get("has_workflow") or key in seen:
            continue
        seen.add(key)
        if "_workflow" in e:
            continue
        p = e.get("moved") or os.path.join(folder, e["file"])
        try:
            if e.get("video"):
                from . import videometa
                text = videometa.read(p).get("text") or {}
            else:
                with open(p, "rb") as f:
                    text = imagemeta.read(f.read()).get("text") or {}
            raw = text.get("workflow") or text.get("prompt")
            if raw:
                e["_workflow"] = json.loads(raw)
        except (OSError, ValueError):
            continue


def job_status() -> dict:
    return {k: v for k, v in _job.items() if not k.startswith("_")}


def start(folder: str, **opts) -> dict:
    """Runs the scan in a background thread (it's all file reading and image work)."""
    folder = os.path.abspath(str(folder or "").strip().strip('"'))
    if not os.path.isdir(folder):
        raise ValueError("That folder doesn't exist")
    return _start_job(folder, run, **opts)


def cancel() -> None:
    stop = _job.get("_stop")
    if stop:
        stop.set()


# ---------------------------------------------------------------- moving originals off this drive
MOVE_MIN_AGE = 600  # files changed in the last 10 minutes may still be being written: left in place


def default_move_dest(folder: str) -> str:
    """<archive drive>/outputs/<folder name>, when an archive drive is set in Settings."""
    from . import tiering
    d = tiering.archive_dir()
    return os.path.join(d, "outputs", os.path.basename(os.path.abspath(folder).rstrip("\\/"))) if d else ""


def _check_dest(folder: str, dest: str) -> str:
    dest = str(dest or "").strip().strip('"')
    if not dest or not os.path.isabs(dest) or os.path.splitdrive(os.path.abspath(dest))[1] in ("", os.sep, "/"):
        raise ValueError("Choose a folder to move the originals into: a full path, not the root of a drive")
    dest = os.path.abspath(dest)
    f, d = os.path.normcase(folder), os.path.normcase(dest)
    if d == f or d.startswith(f + os.sep) or f.startswith(d + os.sep):
        raise ValueError("The destination can't be the scanned folder, inside it, or above it")
    return dest


def move_plan(folder: str, dest: str) -> dict:
    """What move_originals would do: every archived file still in the folder, unchanged since the
    archive was written and not modified in the last 10 minutes."""
    folder = os.path.abspath(folder)
    dest = _check_dest(folder, dest)
    index = _load_index(os.path.join(folder, OUT))
    if not index:
        raise ValueError("Archive this folder first: only archived files are moved")
    move, changed, recent, conflicts = [], 0, 0, 0
    now = time.time()
    for rel, e in sorted(index.items()):
        if e.get("moved"):
            continue
        src = os.path.join(folder, *rel.split("/"))
        try:
            st = os.stat(src)
        except OSError:
            continue
        if st.st_size != e.get("size") or st.st_mtime != e.get("mtime"):
            changed += 1  # changed since the archive was written: run it again first
        elif now - st.st_mtime < MOVE_MIN_AGE:
            recent += 1
        elif os.path.exists(os.path.join(dest, *rel.split("/"))):
            conflicts += 1
        else:
            move.append({"file": rel, "size": st.st_size, "meta": not e.get("error")})
    return {"folder": folder, "dest": dest, "files": move, "count": len(move), "bytes": sum(m["size"] for m in move),
            "without_meta": sum(1 for m in move if not m["meta"]), "changed": changed, "recent": recent, "conflicts": conflicts}


def _move_file(src: str, dst: str) -> None:
    """Rename on the same drive; otherwise copy (keeping times), check the size, then remove the original."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        raise FileExistsError(dst)
    try:
        os.rename(src, dst)
        return
    except OSError:
        pass
    import shutil
    part = dst + ".mlpart"
    try:
        shutil.copy2(src, part)
        if os.path.getsize(part) != os.path.getsize(src):
            raise OSError("the copy's size doesn't match")
        os.replace(part, dst)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    os.remove(src)


def move_originals(folder: str, dest: str, progress=None, cancelled=lambda: False) -> dict:
    """Moves the archived originals to `dest` (same subfolders). The archive keeps listing them, and
    _ml_archive/moves/<time>.jsonl records every move so undo_move can put them back."""
    plan = move_plan(folder, dest)
    folder, dest = plan["folder"], plan["dest"]
    out_dir = os.path.join(folder, OUT)
    os.makedirs(os.path.join(out_dir, "moves"), exist_ok=True)
    log_name = time.strftime("%Y%m%d-%H%M%S") + ".jsonl"
    index = _load_index(out_dir)
    report = progress or (lambda **kw: None)
    report(phase="moving", total=plan["count"], done=0)
    moved, failed, nbytes = 0, [], 0
    with open(os.path.join(out_dir, "moves", log_name), "a", encoding="utf-8") as log:
        for i, m in enumerate(plan["files"]):
            if cancelled():
                break
            rel = m["file"]
            src, dst = os.path.join(folder, *rel.split("/")), os.path.join(dest, *rel.split("/"))
            try:
                _move_file(src, dst)
            except Exception as ex:
                failed.append({"file": rel, "error": str(ex)})
                continue
            log.write(json.dumps({"file": rel, "from": src, "to": dst, "size": m["size"]}, ensure_ascii=False) + "\n")
            log.flush()
            index[rel]["moved"] = dst
            moved += 1
            nbytes += m["size"]
            if i % 25 == 0:
                report(done=i + 1, current=rel)
            if i and i % 200 == 0:
                _save_index(out_dir, index, {})
    _save_index(out_dir, index, {})
    _refresh_summary(out_dir, index)
    return {"kind": "move", "moved": moved, "bytes": nbytes, "failed": failed[:50], "failed_count": len(failed),
            "dest": dest, "log": log_name, "cancelled": cancelled()}


def undo_move(folder: str, log_name: str, progress=None, cancelled=lambda: False) -> dict:
    """Puts back what one move_originals run moved (files not already back, and whose original spot is free)."""
    folder = os.path.abspath(folder)
    out_dir = os.path.join(folder, OUT)
    if not re.fullmatch(r"\d{8}-\d{6}\.jsonl", log_name or ""):
        raise ValueError("Unknown move log")
    path = os.path.join(out_dir, "moves", log_name)
    try:
        with open(path, encoding="utf-8") as f:
            rows = [json.loads(x) for x in f if x.strip()]
    except (OSError, ValueError) as ex:
        raise ValueError(f"Couldn't read that move log: {ex}") from None
    index = _load_index(out_dir)
    report = progress or (lambda **kw: None)
    report(phase="restoring", total=len(rows), done=0)
    back, failed = 0, []
    for i, r in enumerate(reversed(rows)):
        if cancelled():
            break
        try:
            here, there = os.path.isfile(r["from"]), os.path.isfile(r["to"])
            if here and not there:
                continue  # already back
            if here and there:  # a newer file took its name meanwhile: never overwritten
                raise FileExistsError(f"a newer file has its name in the folder now; the original stays at {r['to']}")
            if not there:  # the log is kept: plug the drive in and Undo again
                raise FileNotFoundError(f"not at {r['to']} (is that drive connected?)")
            _move_file(r["to"], r["from"])
        except Exception as ex:
            failed.append({"file": r.get("file"), "error": str(ex)})
            continue
        if r.get("file") in index:
            index[r["file"]].pop("moved", None)
        back += 1
        if i % 25 == 0:
            report(done=i + 1, current=r.get("file"))
    _save_index(out_dir, index, {})
    _refresh_summary(out_dir, index)
    if not failed and not cancelled():
        os.replace(path, path + ".undone")
    return {"kind": "undo", "restored": back, "failed": failed[:50], "failed_count": len(failed), "cancelled": cancelled()}


def move_logs(folder: str) -> list[dict]:
    """The moves that can still be undone, newest first."""
    d = os.path.join(os.path.abspath(folder), OUT, "moves")
    out = []
    try:
        names = sorted((n for n in os.listdir(d) if n.endswith(".jsonl")), reverse=True)
    except OSError:
        return []
    for n in names:
        try:
            with open(os.path.join(d, n), encoding="utf-8") as f:
                rows = [json.loads(x) for x in f if x.strip()]
        except (OSError, ValueError):
            continue
        if rows:
            out.append({"log": n, "count": len(rows), "bytes": sum(r.get("size", 0) for r in rows),
                        "dest": os.path.dirname(rows[0]["to"]) if len(rows) == 1 else os.path.commonpath([r["to"] for r in rows])})
    return out


def _refresh_summary(out_dir: str, index: dict) -> None:
    """Keeps summary.json's moved count right after a move or undo (the rest is unchanged)."""
    p = os.path.join(out_dir, "summary.json")
    try:
        with open(p, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        return
    s["moved"] = sum(1 for e in index.values() if e.get("moved"))
    _atomic(p, json.dumps(s, ensure_ascii=False))


def _start_job(folder: str, fn, **kw) -> dict:
    with _lock:
        if _job.get("status") == "running":
            return job_status()
        _job.clear()
        _job.update(status="running", folder=folder, phase="starting", done=0, total=0, current=None, started=time.time())
        stop = threading.Event()
        _job["_stop"] = stop

    def work():
        try:
            res = fn(folder, progress=lambda **k: _job.update(k), cancelled=stop.is_set, **kw)
            _job.update(status="cancelled" if res.get("cancelled") else "done", result=res, phase=None, current=None)
        except Exception as ex:
            _job.update(status="error", error=str(ex), phase=None, current=None)

    threading.Thread(target=work, daemon=True, name="smf-archive").start()
    return job_status()


def start_move(folder: str, dest: str) -> dict:
    folder = os.path.abspath(str(folder or "").strip().strip('"'))
    move_plan(folder, dest)  # refuses bad destinations up front
    return _start_job(folder, move_originals, dest=dest)


def start_undo(folder: str, log_name: str) -> dict:
    folder = os.path.abspath(str(folder or "").strip().strip('"'))
    if not os.path.isfile(os.path.join(folder, OUT, "moves", str(log_name or ""))):
        raise ValueError("Unknown move log")
    return _start_job(folder, undo_move, log_name=log_name)


def summary(folder: str) -> dict | None:
    try:
        with open(os.path.join(os.path.abspath(folder), OUT, "summary.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def thumb_path(folder: str, name: str) -> str | None:
    if not re.fullmatch(r"[0-9a-f]{16}\.webp", name or ""):
        return None
    p = os.path.join(os.path.abspath(folder), OUT, "thumbs", name)
    return p if os.path.isfile(p) else None

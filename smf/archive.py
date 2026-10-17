"""Archive: a folder of generated images -> what made each one, consolidated.

Scans a folder (and its subfolders), reads the generation data of every image
and video with the recipe readers, and writes `_ml_archive/` inside it:

  report.md      prompt families -> variants -> one row per image (seed, model, what differs)
  images.csv     one row per image, every field
  recipes.jsonl  the recipe of every image (shared recipe/1 format, without the workflow)
  workflows/     one ComfyUI workflow per prompt variant
  thumbs/        a small WebP per image that carries its own workflow, prompt and recipe:
                 drop one on ComfyUI to get that exact image's workflow back
  index.json     what was read, so a re-run only reads new or changed files

Prompts that differ only by a few words are grouped into one family (the
variant with most images is its base; the others show what changed).
Nothing in the scanned folder is changed outside `_ml_archive/`.
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


def _thumb(data: bytes, meta: dict, rec: dict | None, dest: str, embed: bool) -> int:
    """512 px WebP of the image, carrying its workflow, prompt, recipe and A1111 text. -> bytes written."""
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(data)) as im:
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
    if thumbs and data is not None:
        name = hashlib.sha1(rel.replace("\\", "/").lower().encode()).hexdigest()[:16] + ".webp"
        try:
            e["thumb_bytes"] = _thumb(data, meta, e.get("recipe"), os.path.join(out_dir, "thumbs", name), embed)
            e["thumb"] = name
        except Exception as ex:
            e["thumb_error"] = str(ex)
    return e


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
        thumb_ok = not thumbs or (prev or {}).get("thumb") or (prev or {}).get("video") or (prev or {}).get("error")
        if prev and prev.get("size") == st.st_size and prev.get("mtime") == st.st_mtime and prev.get("opts_embed") == embed and thumb_ok:
            index[rel] = prev
        else:
            todo.append((p, rel))
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
             "original_mb": sum(e.get("size", 0) for e in entries) / 1024 ** 2}
    write_tables(out_dir, families, no_meta)
    stats["archive_mb"] = sum(os.path.getsize(os.path.join(dp, fn)) for dp, _, fns in os.walk(out_dir) for fn in fns) / 1024 ** 2
    write_report(folder, out_dir, families, no_meta, stats)
    summary = {"folder": folder, "out_dir": out_dir, **stats, "families": len(families), "no_meta": len(no_meta),
               "top": [{"id": f["id"], "base": f["base"][:300], "count": f["count"], "variants": len(f["variants"]),
                        "thumbs": [e["thumb"] for v in f["variants"] for e in v["images"] if e.get("thumb")][:6]}
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
        p = os.path.join(folder, e["file"])
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
    with _lock:
        if _job.get("status") == "running":
            return job_status()
        folder = os.path.abspath(str(folder or "").strip().strip('"'))
        if not os.path.isdir(folder):
            raise ValueError("That folder doesn't exist")
        _job.clear()
        _job.update(status="running", folder=folder, phase="listing", done=0, total=0, current=None, started=time.time())
        stop = threading.Event()
        _job["_stop"] = stop

    def work():
        try:
            res = run(folder, progress=lambda **kw: _job.update(kw), cancelled=stop.is_set, **opts)
            _job.update(status="cancelled" if res.get("cancelled") else "done", result=res, phase=None, current=None)
        except Exception as ex:
            _job.update(status="error", error=str(ex), phase=None, current=None)

    threading.Thread(target=work, daemon=True, name="smf-archive").start()
    return job_status()


def cancel() -> None:
    stop = _job.get("_stop")
    if stop:
        stop.set()


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
